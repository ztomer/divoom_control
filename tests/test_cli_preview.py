"""WG.5a: `divoom-control preview` reads what each panel shows, read-only.

Both directions. The real CLI entry point against a real BLE-free `divoomd`
with mock panels: a pushed image comes back as the same pixels, and a panel
nothing was sent to says so. And every state the daemon cannot speak for --
no daemon, a daemon too old to answer, a registered panel with no link, an
unknown `--mac` -- is an entry with `frame: null` and a reason, never a blank
image that looks like data.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess as sp
import sys
import tempfile
import time
from pathlib import Path

import pytest

from divoom_lib.cli_preview import ENTRY_KEYS, collect
from tests.support.daemon_binary import require_divoomd

REPO_ROOT = Path(__file__).resolve().parent.parent
A, B = "AA:00:00:00:00:0A", "BB:00:00:00:00:0B"
UNLINKED = "cc000000-0000-0000-0000-00000000000c"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """App settings that register one panel the daemon never links."""
    ini = tmp_path / "config.ini"
    ini.write_text(f"[gallery]\n{UNLINKED} = 18\n", encoding="utf-8")
    monkeypatch.setenv("DIVOOM_CONTROL_CONFIG", str(ini))
    return ini


@pytest.fixture
def live_daemon(settings):
    from divoom_client.daemon_client import DaemonClient, daemon_alive, spawn_daemon

    require_divoomd()
    sock_dir = tempfile.mkdtemp(prefix="divoom-prev-")
    socket_path = os.path.join(sock_dir, "d.sock")
    handle = spawn_daemon(socket_path)
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not daemon_alive(socket_path):
            time.sleep(0.1)
        client = DaemonClient(socket_path)
        while time.monotonic() < deadline and not client.send_command("get_status").get("success"):
            time.sleep(0.1)
        for mac, name in ((A, "Ditoo-Pro"), (B, "Pixoo64")):
            conn = client.send_command("connect", {"mock": True, "mac": mac, "name": name})
            assert conn.get("success") is True, conn
        yield socket_path, client
    finally:
        if isinstance(handle, sp.Popen):
            handle.terminate()
            try:
                handle.wait(timeout=10)
            except sp.TimeoutExpired:
                handle.kill()
        elif isinstance(handle, int):
            try:
                os.kill(handle, 15)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(handle, 0)
            except ChildProcessError:
                pass


def _run(*argv: str) -> sp.CompletedProcess:
    return sp.run([sys.executable, "-m", "divoom_lib.cli", *argv], capture_output=True,
                  text=True, timeout=60, cwd=REPO_ROOT, stdin=sp.DEVNULL, env=os.environ.copy(), check=False)


def _gradient() -> bytes:
    return bytes(v for y in range(16) for x in range(16) for v in (y * 15, x * 15, 200))


def _assert_absent(entry: dict, state: str) -> None:
    assert entry["state"] == state, entry
    assert entry["frame"] is None, entry
    assert len(entry["reason"] or "") > 20, entry
    assert set(ENTRY_KEYS) <= set(entry), entry


def test_a_pushed_image_comes_back_as_the_same_pixels(live_daemon, tmp_path):
    from PIL import Image

    socket_path, client = live_daemon
    rgb = _gradient()
    reply = client.send_command("device_call", {
        "mac": A, "method": "show_image", "args": [],
        "kwargs": {"w": 16, "h": 16,
                   "frames": [{"rgb_b64": base64.b64encode(rgb).decode(), "time_ms": 100}]},
    })
    assert reply.get("success") is True, reply
    before = client.send_command("mock_sent", {"mac": A})

    proc = _run("preview", "--json", "--socket", socket_path, "--out", str(tmp_path / "out"))
    assert proc.returncode == 0, proc.stderr
    answer = json.loads(proc.stdout)
    assert answer["daemon"] == {"state": "running", "reason": None}
    by_id = {d["id"]: d for d in answer["devices"]}

    a = by_id[A]
    assert a["state"] == "frame" and a["reason"] is None, a
    assert (a["name"], a["width"], a["height"]) == ("Ditoo-Pro", 16, 16), a
    assert a["source"] == "show_image" and 0 <= a["age_s"] < 30, a
    body = a["frame"]["data_url"].split(";base64,", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(body))).convert("RGB")
    assert img.size == (16, 16)
    assert img.tobytes() == rgb, "the preview is the pixels the panel was sent"
    assert Path(a["frame"]["path"]).read_bytes() == base64.b64decode(body)

    _assert_absent(by_id[B], "nothing_sent")
    assert by_id[B]["width"] == 64, by_id[B]
    _assert_absent(by_id[UNLINKED], "not_linked")

    assert client.send_command("mock_sent", {"mac": A}) == before, "a read is not a write"


def test_an_unknown_mac_is_an_absent_entry(live_daemon):
    socket_path, _ = live_daemon
    proc = _run("preview", "--json", "--socket", socket_path, "--mac", "NEVER_LINKED")
    assert proc.returncode == 0, proc.stderr
    (entry,) = json.loads(proc.stdout)["devices"]
    _assert_absent(entry, "unknown")
    assert "NEVER_LINKED" in entry["reason"]


class _Fake:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def send_command(self, command, args=None, **_kw):
        self.sent.append(command)
        return self.reply


def test_no_daemon_reports_every_registered_panel_absent(settings):
    fake = _Fake({"success": False, "error": "refused", "unreachable": True})
    answer = collect(fake)
    assert answer["daemon"]["state"] == "not_running"
    (entry,) = answer["devices"]
    _assert_absent(entry, "daemon_not_running")
    assert fake.sent == ["screen_previews"], "it asks one read-only question"


class _OldDaemon(_Fake):
    """A daemon from before `screen_previews`, with one linked panel."""

    def send_command(self, command, args=None, **_kw):
        self.sent.append(command)
        return {
            "device_status": {"success": True, "devices": [
                {"mac": A, "connected": True, "model": "Pixoo", "width": 16, "height": 16}]},
            "owned_devices": {"success": True, "devices": [{"address": A, "name": "Pixoo-1"}]},
        }.get(command, {"success": False, "code": "unknown_command", "error": "x"})


def test_a_daemon_that_predates_the_command_says_so(settings):
    fake = _OldDaemon(None)
    answer = collect(fake)
    assert answer["daemon"]["state"] == "unsupported"
    linked, registered = answer["devices"]
    _assert_absent(linked, "daemon_unsupported")
    assert (linked["id"], linked["name"], linked["width"]) == (A, "Pixoo-1", 16), linked
    _assert_absent(registered, "daemon_unsupported")
    assert registered["id"] == UNLINKED
    assert fake.sent == ["screen_previews", "device_status", "owned_devices"], "reads only"


def test_a_daemon_that_refuses_is_the_documented_error_state(settings):
    fake = _Fake({"success": False, "error": "busy elsewhere", "code": "busy"})
    answer = collect(fake)
    assert answer["daemon"]["state"] == "error"
    assert "busy elsewhere" in answer["daemon"]["reason"]
    (entry,) = answer["devices"]
    _assert_absent(entry, "error")


def test_every_state_the_command_emits_is_documented():
    """A state the code can produce and the docstring never names is a state
    no consumer was told to expect (the audit's `state: error`, API.DV)."""
    import re

    import divoom_lib.cli_preview as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    code = source[source.index('"""', 3) + 3:]
    emitted = set(re.findall(r'_absent\([^,]+,\s*"([a-z_]+)"', code))
    emitted |= set(re.findall(r'"state":\s*"([a-z_]+)"', code))
    assert {"error", "not_running", "unsupported", "running"} <= emitted, emitted
    for state in emitted:
        assert f"``{state}``" in mod.__doc__ or f'"{state}"' in mod.__doc__, state
