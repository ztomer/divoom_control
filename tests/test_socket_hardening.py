"""Socket-protocol client hardening: the client-side reply-size cap.

The rest of this suite (every test that drives a real in-process SocketServer)
depends on the archived divoom_client.socket_server module and moved to
archive/tests/ (removed in R66; in git history) test_socket_hardening.py, which kept the original name since it
carries the bulk of the file's tests.
"""
import sys
from pathlib import Path

from divoom_client.daemon_protocol import DaemonClient

sys.path.append(str(Path(__file__).parent.parent))


# ── client-side reply cap (H2 client) ──────────────────────────────────────

def test_client_caps_oversized_reply(monkeypatch):
    from divoom_client import daemon_protocol

    class _FloodSock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def settimeout(self, _t): pass
        def sendall(self, _d): pass
        def recv(self, n): return b"a" * n          # never a newline → would grow forever

    monkeypatch.setattr(daemon_protocol, "MAX_REPLY_BYTES", 4096)
    monkeypatch.setattr(DaemonClient, "_connect", lambda self: _FloodSock())
    c = DaemonClient("/tmp/whatever.sock")
    reply = c.send_command("device_status")
    assert reply["success"] is False and "max size" in reply["error"]
