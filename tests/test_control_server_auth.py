"""The control server's TCP surface must be authenticated (R72 P3.2).

Split out of `test_control_server.py` when that file crossed the 500-line cap.

**What these pin.** `control_server.py` reflection-dispatches every public
`DivoomGuiAPI` method — device control, credential reads, file dialogs. Until
R72 P3.2 its `_authorized()` returned True when no token was set, so a tokenless
TCP server handed the whole app to any local process under any user on the
machine. "Bound to 127.0.0.1" was doing the work of an authorisation boundary,
which loopback is not.

The Unix-socket variant stays tokenless, and that exemption is EARNED rather
than assumed: it chmods the socket to 0600 explicitly instead of inheriting the
caller's umask. Filesystem permissions are a real boundary.
"""
from __future__ import annotations

import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "divoom_gui"))
import control_server as cs  # noqa: E402


class FakeApi:
    """Minimal stand-in — these tests never get as far as dispatching."""

    def set_vj_effect(self, n):
        return True


def test_tcp_without_a_token_refuses_to_start():
    """The whole point of P3.2.

    This endpoint reflection-dispatches every public DivoomGuiAPI method --
    device control, credential reads, file dialogs -- and `_authorized()`
    returns True when no token is set. Bound to loopback that still means any
    local process, under any user on the machine, can drive the entire app.
    Localhost is not an authorisation boundary.
    """
    with pytest.raises(RuntimeError, match="DIVOOM_CONTROL_TOKEN"):
        cs.serve(FakeApi(), host="127.0.0.1", port=0)


def test_tcp_picks_the_token_up_from_the_environment(monkeypatch):
    monkeypatch.setenv("DIVOOM_CONTROL_TOKEN", "from-env")
    httpd = cs.serve(FakeApi(), host="127.0.0.1", port=0)
    try:
        assert httpd is not None
    finally:
        httpd.server_close()


def test_the_unix_socket_is_0600_and_may_be_tokenless():
    """The exemption is EARNED, not assumed: filesystem permissions are a real
    boundary where 'it is only localhost' is not.

    Deliberately NOT under pytest's tmp_path: a unix socket path has a ~104-byte
    limit and the /var/folders tmp dirs blow it -- the same trap
    tests/support/gui_daemon_stack.py documents for IsolatedStack.
    """
    import os
    import stat
    import uuid

    sock = Path(f"/tmp/divoom_ctl_{uuid.uuid4().hex[:8]}.sock")
    httpd = cs.serve_unix(FakeApi(), str(sock))
    try:
        mode = stat.S_IMODE(os.stat(sock).st_mode)
        assert mode == 0o600, f"socket is {oct(mode)}, not 0600"
    finally:
        httpd.server_close()
        sock.unlink(missing_ok=True)
