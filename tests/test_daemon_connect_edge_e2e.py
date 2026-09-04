"""Hardware-free daemon connect/disconnect edge-case e2e (R57).

Drives a REAL divoomd process (spawned by ``spawn_daemon``) over a real Unix
socket, but uses the daemon's built-in ``mock`` transport (``connect`` with
``{"mock": true}`` → ``MockTransport``) and an unreachable LAN IP for the
"device is off / not there" case. No Bluetooth, no real device.

This is the orchestration half of the bulletproof matrix: the Rust side
(``central.rs`` / ``daemon_connect.rs``) proves the BLE layer can't hang on a
dead central; this file proves the daemon's connect/disconnect/device-lifecycle
state machine stays coherent and responsive across the nasty sequences a user
can actually trigger — mid-flight disconnect, reconnect loops, connect to a
device that isn't there, connect-while-already-connected, and device ops after
disconnect.
"""
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_client.daemon_client import daemon_alive, spawn_daemon
from divoom_client.daemon_protocol import DaemonClient

# R67: this suite used to spawn its daemon on DEFAULT_SOCKET_PATH
# (/tmp/divoom.sock) — the very path the user's app owns. So the whole file
# refused to run whenever Divoom was open, turning eight tests red for an
# environmental reason and burying real failures in the noise. Twice in one
# round the "8 failures" turned out to be nothing but a running app.
#
# The tests do not need the well-known path; they need A path. Using a
# dedicated one makes the suite independent of whatever else is running, and
# keeps the guard below meaningful: a daemon answering HERE really is a
# leftover from a previous run of this file.
DEFAULT_SOCKET_PATH = os.environ.get(
    "DIVOOM_TEST_SOCKET", "/tmp/divoom_e2e_tests.sock"
)

# Handle for the daemon THIS test file spawned — an int pid (disclaimed
# posix_spawn path) or a subprocess.Popen (fallback path). Only ever
# terminate this specific handle, never pattern-match by name: a broad
# `pkill -f divoomd` would also kill the user's own real daemon (e.g. the
# menubar app's), and would silently miss the Python-daemon fallback whose
# command line never contains the literal substring "divoomd".
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
    # Bare pid (int) from the TCC-disclaimed posix_spawn path — still our
    # direct child, so reap it after killing to avoid a zombie.
    try:
        os.kill(handle, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(handle, 0)
    except ChildProcessError:
        pass


def _fresh_client():
    """Kill the daemon THIS file previously spawned (if any), spawn a fresh
    one, return a live ``DaemonClient``."""
    global _daemon_handle
    _terminate_handle(_daemon_handle)
    _daemon_handle = None
    if daemon_alive(DEFAULT_SOCKET_PATH):
        raise RuntimeError(
            f"A daemon is already answering on {DEFAULT_SOCKET_PATH} that this "
            "test did not spawn (leftover process from another run, or the "
            "user's own daemon). Refusing to touch it — stop it manually and "
            "rerun the tests."
        )
    if os.path.exists(DEFAULT_SOCKET_PATH):
        try:
            os.remove(DEFAULT_SOCKET_PATH)
        except OSError:
            pass
    _daemon_handle = spawn_daemon(DEFAULT_SOCKET_PATH)
    # This function runs OUTSIDE the caller's try/finally, so any failure from
    # here on must clean up the handle we just spawned ourselves — otherwise a
    # slow-starting daemon that times out leaks as an orphan for the next test
    # (or the next full run) to trip over, the same failure mode this rewrite
    # was meant to close.
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if daemon_alive(DEFAULT_SOCKET_PATH):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("daemon failed to come up on the socket")
        client = DaemonClient(DEFAULT_SOCKET_PATH)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if client.send_command("get_status").get("success"):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("daemon never answered get_status")
        return client
    except BaseException:
        _terminate_handle(_daemon_handle)
        _daemon_handle = None
        if os.path.exists(DEFAULT_SOCKET_PATH):
            try:
                os.remove(DEFAULT_SOCKET_PATH)
            except OSError:
                pass
        raise


def _kill_daemon():
    global _daemon_handle
    _terminate_handle(_daemon_handle)
    _daemon_handle = None
    if os.path.exists(DEFAULT_SOCKET_PATH):
        try:
            os.remove(DEFAULT_SOCKET_PATH)
        except OSError:
            pass


def test_mock_connect_marks_device_connected():
    c = _fresh_client()
    try:
        res = c.send_command("connect", {"mock": True})
        assert res.get("success") is True, res
        assert res.get("mac") == "MOCK_MAC"
        st = c.device_status()
        assert st.get("connected") is True
        assert st.get("connection_state") == "connected"
    finally:
        _kill_daemon()


def test_disconnect_with_no_device_is_safe():
    c = _fresh_client()
    try:
        # No connect first — disconnect must be a clean success, not a crash.
        res = c.send_command("disconnect")
        assert res.get("success") is True
        st = c.device_status()
        assert st.get("connected") is False
        # And the daemon is still alive/responsive afterwards.
        assert c.send_command("get_status").get("success") is True
    finally:
        _kill_daemon()


def test_device_call_after_disconnect_returns_error_not_crash():
    c = _fresh_client()
    try:
        c.send_command("connect", {"mock": True})
        c.send_command("disconnect")
        # A device op after disconnect must come back as a clean error dict
        # (no exception, no wedge) — the daemon must stay responsive.
        reply = c.device_call("display.show_clock", [2], {})
        assert isinstance(reply, dict)
        assert reply.get("success") is False
        assert c.send_command("get_status").get("success") is True
    finally:
        _kill_daemon()


def test_connect_disconnect_reconnect_loop_stays_responsive():
    c = _fresh_client()
    try:
        for _ in range(5):
            res = c.send_command("connect", {"mock": True})
            assert res.get("success") is True
            assert c.device_status().get("connected") is True
            d = c.send_command("disconnect")
            assert d.get("success") is True
            assert c.device_status().get("connected") is False
        # Still answering after the loop.
        assert c.send_command("get_status").get("success") is True
    finally:
        _kill_daemon()


def test_connect_already_connected_is_idempotent():
    c = _fresh_client()
    try:
        first = c.send_command("connect", {"mock": True})
        assert first.get("success") is True
        # A second connect while already connected must not wedge or error.
        second = c.send_command("connect", {"mock": True})
        assert second.get("success") is True
        assert second.get("mac") == "MOCK_MAC"
        assert c.device_status().get("connected") is True
    finally:
        _kill_daemon()


def test_connect_offline_lan_ip_errors_then_recovers():
    c = _fresh_client()
    try:
        # An unreachable LAN IP exercises the "device is off / not there" path
        # without Bluetooth. Must fail cleanly and leave the daemon usable.
        res = c.send_command("connect", {"lan_ip": "192.168.255.254", "lan_token": 0},
                              read_timeout=10)
        assert res.get("success") is False
        assert "error" in res
        # Daemon still responds and a subsequent (mock) connect works.
        assert c.send_command("get_status").get("success") is True
        ok = c.send_command("connect", {"mock": True})
        assert ok.get("success") is True
    finally:
        _kill_daemon()


def test_midflight_disconnect_does_not_wedge_daemon():
    c = _fresh_client()
    try:
        c.send_command("connect", {"mock": True})
        # Fire a device op on a thread, then disconnect from the main thread
        # "mid-flight". The daemon must serialize them and stay responsive.
        result = {}

        def do_call():
            try:
                result["reply"] = c.device_call("display.show_clock", [2], {})
            except Exception as e:  # noqa: BLE001 - we only assert it didn't wedge
                result["error"] = str(e)

        t = threading.Thread(target=do_call, daemon=True)
        t.start()
        time.sleep(0.05)  # overlap the device op with the disconnect
        d = c.send_command("disconnect")
        assert d.get("success") is True
        t.join(timeout=5.0)
        assert t.is_alive() is False, "device_call hung after disconnect"
        # The daemon is still answering get_status — proof it wasn't wedged.
        assert c.send_command("get_status").get("success") is True
    finally:
        _kill_daemon()


def test_scan_during_connect_rejected_cleanly():
    """Connect (mock) holds the per-call guard; a concurrent ``scan`` must not
    wedge the daemon. Scan uses real BLE, so we only assert the daemon stays
    responsive (the scan result itself is environment-dependent)."""
    c = _fresh_client()
    try:
        c.send_command("connect", {"mock": True})
        # Issue a scan; don't block on it tightly. The daemon must remain alive.
        scan = c.send_command("scan", {"timeout": 2.0, "limit": 20}, read_timeout=8)
        assert isinstance(scan, dict)  # replied (success or error), didn't hang
        assert c.send_command("get_status").get("success") is True
    finally:
        _kill_daemon()
