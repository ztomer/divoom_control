"""R61 coverage push: divoom_client.daemon_protocol.DaemonClient branches not
exercised by test_daemon_protocol.py (framing + a real fake-daemon
round-trip), test_daemon_client_wedge.py, or test_daemon_socket_hardening.py.

Gaps closed, all against mocks/monkeypatches or tiny fake sockets — no real
daemon process or hardware:
  * ``DaemonClient.from_env`` — the remote-host/local-socket env-var branch,
    never driven directly by any existing test.
  * ``send_command``'s non-transient connect failure (``OSError``/
    ``ValueError`` from ``_connect()``, e.g. permissions) — must fail fast,
    no retry — and its defensive trailing fallback return (only reachable
    with zero attempts).
  * The large family of thin one-line wrapper methods (``disconnect_device``,
    ``scan``, ``wall_configure``, ``probe_lan``, ``live_job_start/stop/list``,
    ``live_jobs_stop_for``, ``set_device_activity``, ``get_device_activity``,
    ``hot_update_progress``, ``start_notifications``, ``stop_notifications``,
    ``notification_status``) that just delegate to ``send_command`` — never
    called directly by any existing test (only exercised end-to-end against a
    real daemon for a handful of commands).
  * ``subscribe``'s reply-size cap (``MAX_REPLY_BYTES``) — a malformed/never
    -terminated broadcast must not let the buffer grow unbounded.
"""
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import divoom_client.daemon_protocol as daemon_protocol_mod
from divoom_client.daemon_protocol import (
    DaemonClient,
    encode_message,
    iter_messages,
)


# ── from_env ───────────────────────────────────────────────────────────────


def test_from_env_reads_remote_host_port_token(monkeypatch):
    monkeypatch.setenv("DIVOOM_DAEMON_HOST", "10.0.0.5")
    monkeypatch.setenv("DIVOOM_DAEMON_PORT", "1234")
    monkeypatch.setenv("DIVOOM_DAEMON_TOKEN", "secret")
    c = DaemonClient.from_env()
    assert c.host == "10.0.0.5"
    assert c.port == 1234
    assert c.token == "secret"
    assert c.is_remote is True


def test_from_env_defaults_to_local_socket_without_host(monkeypatch):
    monkeypatch.delenv("DIVOOM_DAEMON_HOST", raising=False)
    monkeypatch.delenv("DIVOOM_DAEMON_PORT", raising=False)
    monkeypatch.delenv("DIVOOM_DAEMON_TOKEN", raising=False)
    c = DaemonClient.from_env()
    assert c.host is None
    assert c.port is None
    assert c.token is None
    assert c.is_remote is False


# ── send_command: non-transient failure + defensive fallback ──────────────
#
# `unreachable: True` rides along on every TRANSPORT failure. It is asserted
# here rather than ignored because it is the field callers branch on to tell
# "nothing was listening" from "the daemon answered and said no" — the GUI shows
# a human sentence for the first and the daemon's own words for the second.
# Matching on `error` text instead would make a reworded errno a silent
# behaviour change.


def test_send_command_nontransient_connect_error_is_not_retried(monkeypatch):
    """OSError subclasses NOT in the transient set (e.g. PermissionError) —
    and plain ValueError — must fail immediately with no retry loop."""
    c = DaemonClient("/tmp/divoom_cov_nontransient.sock")
    calls = {"n": 0}

    def bad_connect():
        calls["n"] += 1
        raise PermissionError("denied")

    monkeypatch.setattr(c, "_connect", bad_connect)
    reply = c.send_command("ping", connect_retries=3)
    assert reply == {"success": False, "error": "denied", "unreachable": True}
    assert calls["n"] == 1, "a non-transient connect error must not be retried"


def test_send_command_value_error_from_connect_is_not_retried(monkeypatch):
    c = DaemonClient("/tmp/divoom_cov_valueerror.sock")

    def bad_connect():
        raise ValueError("bad address")

    monkeypatch.setattr(c, "_connect", bad_connect)
    reply = c.send_command("ping")
    assert reply == {"success": False, "error": "bad address", "unreachable": True}


def test_send_command_zero_attempts_hits_defensive_fallback():
    """``connect_retries=-1`` makes ``range(connect_retries + 1)`` empty, so
    the for-loop body never runs at all — the trailing fallback return must
    still produce a clean error dict (not a NameError on an unset last_err)."""
    reply = DaemonClient("/tmp/divoom_cov_unused.sock").send_command(
        "ping", connect_retries=-1)
    assert reply == {"success": False, "error": "daemon unreachable", "unreachable": True}


# ── thin wrapper methods: delegate to send_command with the right shape ───


def test_notification_wrapper_methods_delegate():
    c = DaemonClient("/tmp/divoom_cov_notif.sock")
    with patch.object(c, "send_command", return_value={"success": True}) as sc:
        assert c.start_notifications() == {"success": True}
        sc.assert_called_with("start_notifications")
        assert c.stop_notifications() == {"success": True}
        sc.assert_called_with("stop_notifications")
        assert c.notification_status() == {"success": True}
        sc.assert_called_with("notification_status")


def test_device_lifecycle_wrapper_methods_delegate():
    c = DaemonClient("/tmp/divoom_cov_lifecycle.sock")
    with patch.object(c, "send_command", return_value={"success": True}) as sc:
        c.disconnect_device()
        assert sc.call_args.args[0] == "disconnect"

        c.probe_lan()
        sc.assert_called_with("probe_lan")

        c.scan()
        assert sc.call_args.args[0] == "scan"
        assert set(sc.call_args.args[1].keys()) == {"timeout", "limit"}

        c.scan(timeout=5.0, limit=3)
        assert sc.call_args.args[1] == {"timeout": 5.0, "limit": 3}

        c.wall_configure({"0": "AA:BB"}, cell_size=32)
        assert sc.call_args.args[0] == "wall_configure"
        assert sc.call_args.args[1] == {"slots": {"0": "AA:BB"}, "cell_size": 32}


def test_live_job_wrapper_methods_delegate():
    c = DaemonClient("/tmp/divoom_cov_livejob.sock")
    with patch.object(c, "send_command", return_value={"success": True}) as sc:
        c.live_job_start("AA:BB", "music", {"size": 16})
        sc.assert_called_with(
            "live_job_start", {"mac": "AA:BB", "kind": "music", "params": {"size": 16}})

        c.live_job_stop("AA:BB", "music")
        sc.assert_called_with("live_job_stop", {"mac": "AA:BB", "kind": "music"})

        c.live_job_list("AA:BB")
        sc.assert_called_with("live_job_list", {"mac": "AA:BB"})

        c.live_jobs_stop_for("AA:BB")
        sc.assert_called_with("live_jobs_stop_for", {"mac": "AA:BB"})


def test_activity_and_hot_update_progress_wrapper_methods_delegate():
    c = DaemonClient("/tmp/divoom_cov_activity.sock")
    with patch.object(c, "send_command", return_value={"success": True}) as sc:
        c.set_device_activity("AA:BB", "music", name="Song", preview="data:x")
        sc.assert_called_with(
            "set_device_activity",
            {"mac": "AA:BB", "kind": "music", "name": "Song", "preview": "data:x"})

        c.get_device_activity()
        sc.assert_called_with("get_device_activity", {})

        c.hot_update_progress()
        sc.assert_called_with("hot_update_progress", {})


# ── subscribe: reply-size cap ──────────────────────────────────────────────


def _sock_path() -> str:
    import os
    return f"/tmp/divoom_proto_cov_{os.getpid()}.sock"


def _serve_one(sock_path, handler, ready):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    srv.settimeout(5.0)
    ready.set()
    try:
        conn, _ = srv.accept()
        handler(conn)
    finally:
        srv.close()


def test_subscribe_returns_false_when_reply_exceeds_max_size(monkeypatch):
    """A daemon that streams data without ever sending a newline must not let
    the client's buffer grow unbounded — capped by MAX_REPLY_BYTES."""
    monkeypatch.setattr(daemon_protocol_mod, "MAX_REPLY_BYTES", 16)

    sp = _sock_path()
    import os
    if os.path.exists(sp):
        os.remove(sp)

    def handler(conn):
        conn.recv(4096)
        conn.sendall(b"x" * 64)  # exceeds the (patched) 16-byte cap, no newline
        time.sleep(0.2)
        conn.close()

    ready = threading.Event()
    t = threading.Thread(target=_serve_one, args=(sp, handler, ready), daemon=True)
    t.start()
    ready.wait(2.0)
    try:
        result = DaemonClient(sp).subscribe(lambda e: None)
    finally:
        t.join(timeout=5.0)
        if os.path.exists(sp):
            os.remove(sp)
    assert result is False
