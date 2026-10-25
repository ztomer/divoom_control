"""The hardware packet's Phase 4 exit check (`scripts/hw_mcp_lease.py`).

Two layers. The first drives the check's machine half with a fake daemon and a
fake MCP session, so every way it must refuse to grade -- a 16x16 panel, a
Wi-Fi panel, a lease that does not keep a second caller out, a lapsed lease
that still renews -- is pinned without hardware.

The second runs the check EXACTLY as the owner will (`run_packet`, the real
`divoomd mcp` entry point resolved the way the GUI resolves it) against a real
daemon with a mock 64x64 panel: everything up to the glass. With nobody at a
terminal the LOOK is UNKNOWN, never PASS -- the packet's own rule.
"""
from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tools"))

hw = pytest.importorskip("hw_verify")
packet = pytest.importorskip("hw_packet")
lease_mod = pytest.importorskip("hw_mcp_lease")

MAC = "AA:BB"
STATUS_64 = {"success": True, "connected": True, "mac": MAC, "lan_ip": None,
             "width": 64, "height": 64}


class FakeClient:
    def __init__(self, status):
        self.status = status
        self.commands = []

    def device_status(self, mac=None):
        return self.status

    def send_command(self, command, args=None):
        self.commands.append((command, args))
        if command == "device_status":
            return self.status
        if command == "get_device_activity":
            png = lease_mod.expect.raw_to_png(bytes((9, 200, 9)) * 4096, 64)
            import base64
            return {"success": True, "activity": {MAC: {
                "kind": "sysmon",
                "preview": "data:image/png;base64," + base64.b64encode(png).decode()}}}
        return {"success": True}


class FakeSession:
    """`divoomd mcp` as an honest daemon answers, unless told otherwise."""

    def __init__(self, **wrong):
        self.wrong = wrong
        self.calls = []
        self.closed = False

    def call(self, name, args):
        self.calls.append(name)
        if name in self.wrong:
            return self.wrong[name]
        return {
            "get_capabilities": (False, {"width": 64, "height": 64}),
            "lease_acquire": (False, {"lease": "lease-1"}),
            "push_animation": (False, {"size": 64, "frames": 4}),
            "show_text": (True, {"error": "the screen is leased to hw_verify agent"}),
            "lease_renew": (True, {"error": "no such lease"}),
        }[name]

    def close(self):
        self.closed = True


def _run(status, session, tmp_path):
    check = packet.McpLeaseCheck(
        id="mcp_lease", title="t", ttl_ms=10,
        session_factory=lambda: session)
    ctx = {"mac": MAC, "size": 64, "frames_dir": str(tmp_path),
           "job_settle": 0, "lapse_margin": 0, "socket": "unused"}
    client = FakeClient(status)
    fired, detail = check.drive(client, ctx)
    return fired, detail, check.expectation(client, ctx), client


@pytest.fixture(autouse=True)
def _no_frame_wait(monkeypatch):
    # The fake's activity answers at once; the real-daemon tests raise it.
    monkeypatch.setattr(lease_mod.expect, "FRAME_WAIT", 0.0)


def test_a_16x16_panel_is_a_skip_that_names_the_size(tmp_path):
    session = FakeSession()
    _, _, exp, _ = _run({**STATUS_64, "width": 16, "height": 16}, session, tmp_path)
    assert exp.verdict == "SKIP"
    assert "64x64" in exp.detail and "16x16" in exp.detail
    assert session.calls == [], "nothing is leased on a panel the exit is not about"


def test_a_wifi_panel_is_a_skip_that_names_the_missing_draw_path(tmp_path):
    session = FakeSession()
    status = {**STATUS_64, "lan_ip": "192.168.0.9", "width": None, "height": None}
    _, _, exp, _ = _run(status, session, tmp_path)
    assert exp.verdict == "SKIP"
    assert "P6.2" in exp.detail and "Wi-Fi" in exp.detail
    assert session.calls == []


def test_a_clean_run_asks_a_person_with_the_frames_to_compare(tmp_path):
    session = FakeSession()
    fired, _, exp, client = _run(STATUS_64, session, tmp_path)
    assert fired and exp.verdict == "", exp.detail
    assert session.closed
    assert ("live_job_start", {"mac": MAC, "kind": "sysmon",
                               "params": {"size": 64}}) in client.commands
    assert session.calls == ["get_capabilities", "lease_acquire", "push_animation",
                             "show_text", "lease_renew"]
    for i in range(len(lease_mod.AGENT_FRAMES)):
        assert (tmp_path / f"mcp_lease_agent_{i}.png").is_file()
    assert (tmp_path / "mcp_lease_widget.png").is_file()
    assert "the widget came back" in exp.text


@pytest.mark.parametrize("wrong, says", [
    ({"show_text": (False, {"ok": True})}, "not refused"),
    ({"lease_renew": (False, {"ttl_ms": 10})}, "still be renewed"),
    ({"push_animation": (False, {"size": 32, "frames": 4})}, "was not 64 px"),
    ({"push_animation": (False, {"size": 64, "frames": 1})}, "was not 64 px"),
    ({"lease_acquire": (True, {"error": "busy"})}, "not granted"),
    ({"get_capabilities": (False, {"width": 16, "height": 16})}, "does not say 64x64"),
])
def test_each_machine_fault_is_a_fail_with_the_reply(tmp_path, wrong, says):
    _, _, exp, _ = _run(STATUS_64, FakeSession(**wrong), tmp_path)
    assert exp.verdict == "FAIL", exp
    assert says in exp.detail


def test_the_declared_tool_names_are_the_ones_called():
    """`MCP_TOOLS` is what the names gate checks; it must be what is sent."""
    source = inspect.getsource(lease_mod.run_scenario)
    called = set(re.findall(r'session\.call\(\s*"([a-z_]+)"', source))
    assert called == set(lease_mod.MCP_TOOLS)
    sent = set(re.findall(r'client\.send_command\(\s*"([a-z_]+)"', source))
    sent |= set(re.findall(r'client\.send_command\(\s*"([a-z_]+)"',
                           inspect.getsource(packet.McpLeaseCheck.drive)))
    assert sent == set(lease_mod.SOCKET_COMMANDS)


# --- everything up to the glass: the real daemon and the real `divoomd mcp` ---

@pytest.fixture
def daemon():
    from divoom_client.daemon_protocol import DaemonClient
    from tests.support.daemon_binary import find_divoomd

    binary = find_divoomd()
    if binary is None:
        pytest.skip("divoomd for this tree is not built (cargo build -p divoomd)")
    sock = f"/tmp/divoomd_mcp_lease_{os.getpid()}_{uuid.uuid4().hex[:8]}.sock"
    home = tempfile.mkdtemp(prefix="divoom_mcp_lease_home_")
    proc = subprocess.Popen([str(binary), "--socket", sock],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env={**os.environ, "HOME": home})
    try:
        deadline = time.monotonic() + 10
        while not os.path.exists(sock):
            assert time.monotonic() < deadline, "the daemon never made its socket"
            assert proc.poll() is None, "the daemon exited"
            time.sleep(0.05)
        yield DaemonClient(sock), sock, str(binary)
    finally:
        proc.kill()
        proc.wait(timeout=10)
        if os.path.exists(sock):
            os.remove(sock)


def _packet(daemon, name, tmp_path):
    client, sock, binary = daemon
    reply = client.send_command("connect", {"mock": True, "mac": MAC, "name": name})
    assert reply.get("success") is True, reply
    check = packet.McpLeaseCheck(id="mcp_lease", title="P4 exit", ttl_ms=1500)
    results: list = []
    hw.run_packet(client, [check], False, results,
                  {"frames_dir": str(tmp_path), "socket": sock, "divoomd": binary,
                   "job_settle": 1.0, "lapse_margin": 1.5})
    return results


def test_the_owners_command_runs_the_exit_up_to_the_glass(daemon, tmp_path, monkeypatch):
    monkeypatch.setattr(lease_mod.expect, "FRAME_WAIT", 10.0)
    results = _packet(daemon, "Pixoo64-light", tmp_path)
    assert [(r.check, r.verdict) for r in results] == [("mcp_lease", "UNKNOWN")], results
    assert (tmp_path / "mcp_lease_widget.png").is_file()


def test_the_owners_command_refuses_a_16x16_panel(daemon, tmp_path):
    results = _packet(daemon, "Pixoo-light", tmp_path)
    assert [(r.check, r.verdict) for r in results] == [("mcp_lease", "SKIP")], results
    assert "16x16" in results[0].detail
