"""Bulletproof daemon-client hardening (R57) — the client must NEVER hang,
raise, or leak a half-open socket when the daemon is wedged/silent.

These are the Python side of the wedge matrix in
``docs/archive/rounds/PLANNING_ROUND57.md``:
they prove ``DaemonClient.send_command`` returns an error dict within its read
timeout against a daemon that (a) accepts but never replies, (b) sends a
never-newline-terminated frame, (c) accepts then immediately closes, or (d) is
absent. The Rust daemon side (wedged ``BleCentral``) is covered in
``divoomd/src/central.rs``; together they guarantee a dead central
can't wedge the whole toolchain.

Deterministic: no hardware, a tiny fake daemon per case.
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_client.daemon_protocol import DaemonClient


def _sock_path() -> str:
    return f"/tmp/divoom_wedge_{os.getpid()}.sock"


def _serve(sp, on_accept):
    """Listen, accept ONE connection, hand it to ``on_accept(conn)``."""
    if os.path.exists(sp):
        os.remove(sp)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sp)
    srv.listen(1)
    srv.settimeout(5.0)
    try:
        conn, _ = srv.accept()
        on_accept(conn)
    finally:
        srv.close()


def _start(sp, on_accept):
    ready = threading.Event()
    t = threading.Thread(target=_serve, args=(sp, on_accept), daemon=True)
    t.start()
    # Give the listener a moment to bind before the client connects.
    time.sleep(0.2)
    return t


def _cleanup(sp, t):
    t.join(timeout=5.0)
    if os.path.exists(sp):
        os.remove(sp)


def test_send_command_does_not_hang_on_silent_daemon():
    """A daemon that accepts but never replies must fail within read_timeout,
    not block forever. This is the exact client-side failure mode of a wedged
    ``BleCentral`` daemon (R57 #1)."""
    sp = _sock_path()
    # Accept then hold the connection open; never send a reply. The client's
    # read_timeout must fire well before this sleep ends.
    t = _start(sp, lambda conn: time.sleep(1.0))

    start = time.monotonic()
    try:
        reply = DaemonClient(sp, timeout=0.5).send_command("get_status", read_timeout=0.5)
    finally:
        elapsed = time.monotonic() - start
        _cleanup(sp, t)

    assert reply.get("success") is False
    assert "error" in reply
    # Bounded by read_timeout, with a generous wall-clock ceiling to catch hangs.
    assert elapsed < 2.0, f"send_command hung for {elapsed:.1f}s"


def test_send_command_does_not_hang_on_unterminated_frame():
    """A daemon that sends bytes with no newline must still time out cleanly
    (never grow an unbounded buffer, never hang). R57 #2."""
    sp = _sock_path()

    def on_accept(conn):
        # Send an incomplete frame (no trailing newline) then hold.
        conn.sendall(b'{"success": false')  # never terminated
        time.sleep(1.0)

    t = _start(sp, on_accept)
    start = time.monotonic()
    try:
        reply = DaemonClient(sp, timeout=0.5).send_command("get_status", read_timeout=0.5)
    finally:
        elapsed = time.monotonic() - start
        _cleanup(sp, t)

    assert reply.get("success") is False
    assert "error" in reply
    assert elapsed < 2.0, f"send_command hung for {elapsed:.1f}s"


def test_send_command_immediate_close_returns_no_reply():
    """A daemon that accepts then immediately closes must return a clean error
    (not raise, not hang). R57 #3."""
    sp = _sock_path()

    def on_accept(conn):
        conn.recv(4096)  # drain the request
        conn.close()     # then drop the connection

    t = _start(sp, on_accept)
    start = time.monotonic()
    try:
        reply = DaemonClient(sp, timeout=0.5).send_command("get_status", read_timeout=5.0)
    finally:
        elapsed = time.monotonic() - start
        _cleanup(sp, t)

    assert reply.get("success") is False
    # EOF before a newline-terminated frame -> "no reply".
    assert "no reply" in reply.get("error", "")
    assert elapsed < 2.0, f"send_command hung for {elapsed:.1f}s"


def test_send_command_absent_socket_errors_fast():
    """A truly absent daemon (no listener) must return an error quickly via the
    connect-retry budget, never hang. R57 #4."""
    sp = f"/tmp/divoom_absent_{os.getpid()}.sock"
    if os.path.exists(sp):
        os.remove(sp)

    start = time.monotonic()
    reply = DaemonClient(sp, timeout=0.5).send_command("ping", connect_retries=2)
    elapsed = time.monotonic() - start

    assert reply.get("success") is False
    assert "error" in reply
    # connect_retries * backoff is sub-second; assert comfortably bounded.
    assert elapsed < 2.0, f"send_command hung for {elapsed:.1f}s"


def test_send_command_garbage_json_line_is_skipped_cleanly():
    """A daemon that streams a malformed line then closes must surface an error
    (the framing skips the bad line, finds no complete message) — not raise.
    R57 #5."""
    sp = _sock_path()

    def on_accept(conn):
        conn.recv(4096)
        conn.sendall(b"this is not json\n")  # malformed, skipped by iter_messages
        conn.close()

    t = _start(sp, on_accept)
    try:
        reply = DaemonClient(sp, timeout=0.5).send_command("get_status", read_timeout=5.0)
    finally:
        _cleanup(sp, t)

    assert reply.get("success") is False
    assert "no reply" in reply.get("error", "")
