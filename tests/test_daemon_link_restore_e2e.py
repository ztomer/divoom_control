"""The panels a CLI or an MCP client linked come back after a daemon restart.

P2.7's remainder. The GUI's own relink brings back the panels the GUI
linked; a panel a CLI or an MCP client linked had no client left holding the
memory, so it stayed dark after a daemon restart until a human clicked.

This drives a REAL divoomd over a real Unix socket, twice: the first daemon
is linked to a panel (the mock transport, so no Bluetooth), killed, and the
second daemon is started in its place. The panel must be linked again with
no client asking for it.

No radio, no hardware: the daemon's built-in `mock` transport stands in for a
panel, and the list the daemon writes is named (DIVOOM_LINKS_PATH) so this
test's file is its own — a mock panel is a test double and belongs in a
test's list, never in the user's.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).parent.parent))

from divoom_client import daemon_client
from divoom_client.daemon_client import daemon_alive, spawn_daemon
from divoom_client.daemon_protocol import DaemonClient

# A path of its own: the well-known socket belongs to the user's app, and
# this file must not depend on whatever else is running.
SOCKET_PATH = os.environ.get("DIVOOM_TEST_SOCKET", "/tmp/divoom_link_restore_tests.sock")
LINKS_PATH = os.environ.get("DIVOOM_TEST_LINKS_PATH", "/tmp/divoom_link_restore_tests.json")

_daemon_handle = None


def _terminate_handle(handle) -> None:
    if handle is None:
        return
    if isinstance(handle, subprocess.Popen):
        handle.kill()
        try:
            handle.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return
    try:
        os.kill(handle, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(handle, 0)
    except ChildProcessError:
        pass


def _clear_socket() -> None:
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass


def _start_daemon() -> DaemonClient:
    """Start a daemon that keeps its list in this test's file."""
    global _daemon_handle
    os.environ["DIVOOM_LINKS_PATH"] = LINKS_PATH
    _daemon_handle = spawn_daemon(SOCKET_PATH)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if daemon_alive(SOCKET_PATH):
            break
        time.sleep(0.1)
    else:
        raise AssertionError("daemon failed to come up on the socket")
    client = DaemonClient(SOCKET_PATH)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if client.send_command("get_status").get("success"):
            break
        time.sleep(0.1)
    else:
        raise AssertionError("daemon never answered get_status")
    return client


def _stop_daemon() -> None:
    global _daemon_handle
    _terminate_handle(_daemon_handle)
    _daemon_handle = None
    _clear_socket()


def _linked_macs(client: DaemonClient) -> list[str]:
    status = client.device_status()
    return [d["mac"] for d in (status.get("devices") or []) if d.get("connected")]


def test_a_panel_a_client_linked_comes_back_after_a_daemon_restart():
    try:
        os.remove(LINKS_PATH)
    except OSError:
        pass
    try:
        client = _start_daemon()
        # A client links a panel — the CLI's path and the MCP server's.
        reply = client.send_command("connect", {"mock": True, "mac": "DEV_A"})
        assert reply.get("success") is True, reply
        assert "DEV_A" in _linked_macs(client)

        # The daemon dies. The next one starts with an empty fleet.
        _stop_daemon()
        client = _start_daemon()

        # The daemon brings the panel back by itself — no client asked.
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if "DEV_A" in _linked_macs(client):
                break
            time.sleep(0.2)
        assert "DEV_A" in _linked_macs(client), (
            "the panel the daemon held did not come back after the restart"
        )
    finally:
        _stop_daemon()
        os.environ.pop("DIVOOM_LINKS_PATH", None)
        try:
            os.remove(LINKS_PATH)
        except OSError:
            pass


def test_a_panel_the_user_dropped_does_not_come_back():
    try:
        os.remove(LINKS_PATH)
    except OSError:
        pass
    try:
        client = _start_daemon()
        client.send_command("connect", {"mock": True, "mac": "DEV_B"})
        dropped = client.send_command("disconnect", {"mac": "DEV_B"})
        assert dropped.get("success") is True, dropped

        _stop_daemon()
        client = _start_daemon()

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if "DEV_B" in _linked_macs(client):
                break
            time.sleep(0.2)
        assert "DEV_B" not in _linked_macs(client), (
            "a panel the user dropped came back after the restart"
        )
    finally:
        _stop_daemon()
        os.environ.pop("DIVOOM_LINKS_PATH", None)
        try:
            os.remove(LINKS_PATH)
        except OSError:
            pass


def test_the_client_asks_the_daemon_to_bring_its_panels_back(monkeypatch, tmp_path):
    """The spawn asks the daemon to bring its panels back after a restart.

    The restore reaches for the radio, and the radio is what a daemon WITHOUT
    the Bluetooth grant dies on (SIGABRT, no message). A daemon started by
    hand from a shell has no grant -- the grant belongs to the bundle the app
    installed -- so the restore must not be the first thing that reaches for
    it. The client's spawn IS the one that carries the grant (the daemon is
    disclaimed into its own responsible process), so the client asks.
    """
    rust_bin = tmp_path / "divoomd"
    rust_bin.write_text("")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust_bin))
    seen = {}

    def fake_disclaim(cmd, log_path, env=None):
        seen["env"] = env or {}
        return 666

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", fake_disclaim)
    daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert seen["env"].get("DIVOOM_LINKS_RESTORE") == "1"


def test_the_plain_popen_path_asks_for_the_restore_too(monkeypatch, tmp_path):
    """The plain-Popen path (no disclaimed spawn) asks as well.

    Same contract as the disclaimed path above: the ask is part of the spawn,
    not of one way of making it.
    """
    rust_bin = tmp_path / "divoomd"
    rust_bin.write_text("")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust_bin))

    def boom(cmd, log_path, env=None):
        raise OSError("no disclaimed spawn here")

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", boom)
    fake_popen = MagicMock(return_value="popen-handle")
    monkeypatch.setattr(daemon_client.subprocess, "Popen", fake_popen)
    daemon_client.spawn_daemon(str(tmp_path / "sock"))
    env = fake_popen.call_args.kwargs.get("env") or {}
    assert env.get("DIVOOM_LINKS_RESTORE") == "1"
