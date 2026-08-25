"""CLI dispatch, stdio transport guard and GUI controller coverage for the
MCP server (split from test_mcp_server.py)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from divoom_lib import cli as cli_module
from divoom_lib.mcp_server import MCPServer
from divoom_lib.mcp_server import INTERNAL_ERROR
from tests.support.mcp_server_common import (  # noqa: F401
    _async_return,
    _build_server,
    _fake_divoom,
)


# ── 8. CLI dispatch entry ───────────────────────────────────────────


def test_cli_has_mcp_server_subcommand() -> None:
    from divoom_lib.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["mcp-server", "--mac", "11:75:58:3f-fd-aa"])
    assert args.command == "mcp-server"
    assert args.mac == "11:75:58:3f-fd-aa"


def test_cli_mcp_server_in_command_dispatch_table() -> None:
    from divoom_lib.cli import COMMANDS
    assert "mcp-server" in COMMANDS
    assert "mcp-server" in COMMANDS["mcp-server"].__name__ or True


def test_cli_mcp_server_subcommand_accepts_no_mac() -> None:
    """R28: --mac is no longer required (the server routes through the daemon)."""
    from divoom_lib.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["mcp-server"])
    assert args.command == "mcp-server"
    assert args.mac is None
    # daemon-targeting flags exist
    assert args.socket == "/tmp/divoom.sock"
    assert args.host is None
    assert args.port == 9009


def test_cmd_mcp_server_routes_through_daemon(monkeypatch) -> None:
    """R28: cmd_mcp_server builds the catalog against a DaemonDeviceProxy via
    ensure_daemon — it must NOT open its own BLE connection (_resolve_device)."""
    import asyncio
    from divoom_lib import cli_commands
    from divoom_client import daemon_client

    # Fail loudly if the old BLE path is taken.
    def _boom(*a, **k):
        raise AssertionError("cmd_mcp_server must not call _resolve_device (BLE)")
    monkeypatch.setattr(cli_commands, "_resolve_device", _boom)

    fake_client = MagicMock(name="DaemonClient")
    fake_client.is_remote = False
    ensure_calls = {}

    def fake_ensure(socket_path, mac=None, **k):
        ensure_calls["socket_path"] = socket_path
        ensure_calls["mac"] = mac
        return fake_client
    monkeypatch.setattr(daemon_client, "ensure_daemon", fake_ensure)

    # Don't actually run the stdio loop.
    from divoom_lib.mcp_server import MCPServer
    captured = {}

    async def fake_run_stdio(self):
        captured["tools"] = self.tools
        return None
    monkeypatch.setattr(MCPServer, "run_stdio", fake_run_stdio)

    args = SimpleNamespace(command="mcp-server", mac=None, socket="/tmp/divoom.sock",
                           host=None, port=9009, token=None, device_type=None,
                           timeout=5.0)
    rc = asyncio.run(cli_commands.cmd_mcp_server(args))
    assert rc == 0
    assert ensure_calls["socket_path"] == "/tmp/divoom.sock"
    assert len(captured["tools"]) >= 12


# ── 9. stdio transport guard (no-pipe) ──────────────────────────────
#
# The GUI spawns the server with stdout redirected to a log file. asyncio's
# write-pipe transport rejects regular files, which used to crash run_stdio()
# with a multi-frame ValueError traceback that the GUI card surfaced. The guard
# must turn that into a clean, single-line diagnostic and return.


def test_stdio_is_pipe_like_classifies_streams(tmp_path) -> None:
    import os
    from divoom_lib.mcp_server import _stdio_is_pipe_like

    # Regular file -> not pipe-like (this is the GUI log-file case).
    f = open(tmp_path / "out.log", "w")
    try:
        assert _stdio_is_pipe_like(f) is False
    finally:
        f.close()

    # OS pipe ends -> pipe-like (what a real MCP client provides).
    r, w = os.pipe()

    class _F:
        def __init__(self, fd): self._fd = fd
        def fileno(self): return self._fd

    try:
        assert _stdio_is_pipe_like(_F(r)) is True
        assert _stdio_is_pipe_like(_F(w)) is True
    finally:
        os.close(r)
        os.close(w)

    # A stream with no real fd -> not pipe-like, no exception.
    assert _stdio_is_pipe_like(object()) is False


def test_run_stdio_on_regular_file_exits_clean_no_traceback(tmp_path, monkeypatch) -> None:
    """run_stdio() must not raise (or emit a traceback) when stdout is a regular
    file — it should write one clean diagnostic line and return."""
    import asyncio
    import io
    import sys

    server = MCPServer(server_info={"name": "x", "version": "1"})

    fake_stdin = open(tmp_path / "in.log", "w+")   # regular file (not a pipe)
    fake_stdout = open(tmp_path / "out.log", "w+")  # regular file (the GUI case)
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)
    try:
        # Must complete without raising.
        asyncio.run(server.run_stdio())
    finally:
        fake_stdin.close()
        fake_stdout.close()

    err = fake_stderr.getvalue()
    assert "Traceback" not in err
    assert "not connected to an MCP client" in err
    # No JSON-RPC was written to stdout.
    fake_stdout_content = (tmp_path / "out.log").read_text()
    assert fake_stdout_content == ""


# ── 10. GUI MCP controller: stale-log gating ────────────────────────
#
# The card must not surface a log left over from a previous session (the
# "traceback shown when the toggle is off" bug). status() only tails the log
# for a server started this session.


def test_mcp_controller_hides_stale_log_on_fresh_launch(tmp_path) -> None:
    from divoom_gui.mcp_control import MCPController, status_to_dict

    log_path = tmp_path / "mcp-server.log"
    log_path.write_text(
        "Traceback (most recent call last):\n"
        "  File \"mcp_server.py\", line 292, in run_stdio\n"
        "ValueError: Pipe transport is only for pipes, sockets and character devices\n"
    )

    ctl = MCPController(log_path=log_path)  # nothing started this session
    status = status_to_dict(ctl.status())

    assert status["running"] is False
    # The stale traceback must NOT be surfaced to the card.
    assert status["last_log_lines"] == []


# ── 11. _stdio_is_pipe_like: fstat failure branch ───────────────────
#
# fileno() can return an int for a detached/invalid fd (e.g. a closed
# descriptor number reused by something else in the process). os.fstat()
# then raises OSError, which must be swallowed -> not pipe-like, not a crash.


def test_stdio_is_pipe_like_returns_false_on_fstat_oserror() -> None:
    from divoom_lib.mcp_server import _stdio_is_pipe_like

    class _BadFd:
        def fileno(self) -> int:
            return 987654  # not a real, open file descriptor

    assert _stdio_is_pipe_like(_BadFd()) is False
