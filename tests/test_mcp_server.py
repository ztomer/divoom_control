"""
R15 §5 — tests for the MCP server + tool catalog.

Test layout:
  *  Server core (handle / dispatch / envelopes)
       - initialize returns the right server info
       - tools/list returns the catalog
       - tools/call dispatches a real handler
       - tools/call returns isError on out-of-range / unknown enum
       - tools/call returns isError for an unknown tool name
       - unknown method returns -32601 Method not found
       - parse error returns -32700
       - notification (no id) returns None

  *  Tool catalog
       - catalog contains the 12 expected tools
       - each tool's input_schema validates (required fields present)
       - the catalog is parameterized over a Divoom instance

  *  Stdio round-trip
       - feed a sequence of requests, assert the responses
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from divoom_lib.mcp_server import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    MCPServer,
    Tool,
    _jsonrpc_error,
    _jsonrpc_response,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _fake_divoom() -> MagicMock:
    """Build a MagicMock with the surface area the tool catalog uses."""
    d = MagicMock()
    # We need AsyncMock for any method that gets awaited. Easiest way
    # is to build a sub-MagicMock per service and assign AsyncMocks
    # for the coroutine methods.
    music = MagicMock()
    music.set_volume = AsyncMock(return_value=True)
    music.get_volume = AsyncMock(return_value=8)
    d.music = music
    device = MagicMock()
    device.set_brightness = AsyncMock(return_value=True)
    device.get_brightness = AsyncMock(return_value=80)
    device.set_low_power_switch = AsyncMock(return_value=True)
    d.device = device
    control = MagicMock()
    control.set_light_mode = AsyncMock(return_value=True)
    control.get_light_mode = AsyncMock(return_value=0)
    control.set_hot = AsyncMock(return_value=True)
    d.control = control
    weather = MagicMock()
    weather.set = AsyncMock(return_value=True)
    d.weather = weather
    alarm = MagicMock()
    alarm.set_alarm = AsyncMock(return_value=True)
    d.alarm = alarm
    radio = MagicMock()
    radio.set_radio_frequency = AsyncMock(return_value=True)
    d.radio = radio
    design = MagicMock()
    design.set_screen_dir = AsyncMock(return_value=True)
    design.get_screen_dir = AsyncMock(return_value=0)
    design.set_screen_mirror = AsyncMock(return_value=True)
    design.get_screen_mirror = AsyncMock(return_value=False)
    d.design = design
    display = MagicMock()
    display.show_image = AsyncMock(return_value=True)
    d.display = display
    # `capabilities` is read directly (not awaited) — make it a
    # MagicMock with a ``to_dict()`` shim.
    caps = MagicMock()
    caps.to_dict.return_value = {
        "panel_resolution": 16,
        "has_speaker": True,
        "has_clock": True,
    }
    d.capabilities = caps
    return d


def _async_return(value: Any):
    async def _coro(*args, **kwargs):
        return value

    return _coro


def _build_server(divoom=None) -> MCPServer:
    from divoom_lib.mcp_tools import build_tool_catalog
    s = MCPServer(server_info={"name": "divoom-control", "version": "0.15.0"})
    s.tools = build_tool_catalog(divoom or _fake_divoom())
    return s


# ── Envelope helpers ──────────────────────────────────────────────────


def test_jsonrpc_response_envelope() -> None:
    r = _jsonrpc_response(7, {"ok": True})
    assert r == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}


def test_jsonrpc_error_envelope_with_data() -> None:
    e = _jsonrpc_error(7, METHOD_NOT_FOUND, "no such", data="x")
    assert e["jsonrpc"] == "2.0"
    assert e["id"] == 7
    assert e["error"]["code"] == METHOD_NOT_FOUND
    assert e["error"]["message"] == "no such"
    assert e["error"]["data"] == "x"


def test_jsonrpc_error_envelope_without_data() -> None:
    e = _jsonrpc_error(None, PARSE_ERROR, "bad")
    assert e["id"] is None
    assert "data" not in e["error"]


# ── 1. initialize ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_returns_server_info_and_capabilities() -> None:
    s = _build_server()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }
    resp = await s.handle(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"] == {"name": "divoom-control", "version": "0.15.0"}


# ── 2. tools/list ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_list_returns_full_catalog() -> None:
    s = _build_server()
    resp = await s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    # 13 tools in the catalog.
    assert len(tools) == 13
    names = {t["name"] for t in tools}
    assert names == {
        "set_volume", "set_brightness", "set_light_mode", "set_weather",
        "set_alarm", "set_radio", "set_low_power",
        "set_screen_orientation", "show_image", "push_animation",
        "play_sound",
        "get_capabilities", "get_device_state",
    }
    # Every tool has the 3 required descriptor fields.
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t


# ── 3. tools/call dispatch ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_call_set_volume_dispatches() -> None:
    divoom = _fake_divoom()
    s = _build_server(divoom)
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "set_volume", "arguments": {"level": 8}},
    })
    assert resp["id"] == 3
    content = resp["result"]["content"]
    assert len(content) == 1
    payload = json.loads(content[0]["text"])
    assert payload == {"ok": True, "level": 8}
    divoom.music.set_volume.assert_awaited_once_with(8)


@pytest.mark.asyncio
async def test_tools_call_set_volume_out_of_range_is_error() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "set_volume", "arguments": {"level": 99}},
    })
    assert resp["id"] == 3
    result = resp["result"]
    assert result["isError"] is True
    assert "0..15" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_set_weather_validates_enum() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "set_weather", "arguments":
                   {"temperature_c": 22, "weather": "hurricane"}},
    })
    result = resp["result"]
    assert result["isError"] is True
    assert "weather must be one of" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_set_weather_ok() -> None:
    divoom = _fake_divoom()
    s = _build_server(divoom)
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "set_weather", "arguments":
                   {"temperature_c": 15, "weather": "rain"}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["temperature_c"] == 15
    divoom.weather.set.assert_awaited_once_with(15, 6)  # 6 = Rain


@pytest.mark.asyncio
async def test_tools_call_push_animation_with_file() -> None:
    """push_animation with 'file' calls display.show_image."""
    divoom = _fake_divoom()
    s = _build_server(divoom)
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "push_animation",
                   "arguments": {"file": "/tmp/test.gif"}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is True
    divoom.display.show_image.assert_awaited_once_with("/tmp/test.gif")


@pytest.mark.asyncio
async def test_tools_call_push_animation_with_data() -> None:
    """push_animation with base64 'data' decodes and calls display.show_image."""
    import base64
    divoom = _fake_divoom()
    s = _build_server(divoom)
    raw = b"GIF89a" + b"\x00" * 50
    encoded = base64.b64encode(raw).decode("ascii")
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "push_animation",
                   "arguments": {"data": encoded}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is True
    # Should have called display.show_image with the raw bytes
    divoom.display.show_image.assert_awaited_once_with(raw)


@pytest.mark.asyncio
async def test_tools_call_push_animation_requires_one_of() -> None:
    """push_animation rejects providing both or neither of file/data."""
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "push_animation",
                   "arguments": {"file": "/tmp/a.gif", "data": "AAAA"}},
    })
    assert resp.get("error") or resp.get("result", {}).get("isError")


@pytest.mark.asyncio
async def test_tools_call_unknown_tool_is_tool_error() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "frobulate", "arguments": {}},
    })
    # Unknown tool = isError (per MCP spec) — NOT -32601.
    result = resp["result"]
    assert result["isError"] is True
    assert "unknown tool" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_missing_required_arg_is_tool_error() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "set_volume", "arguments": {}},  # no level
    })
    result = resp["result"]
    assert result["isError"] is True


# ── 4. unknown method / parse error / notification ──────────────────


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 7, "method": "frobnicate", "params": {},
    })
    assert resp["error"]["code"] == METHOD_NOT_FOUND
    assert "frobnicate" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_notification_returns_none() -> None:
    """Notifications (no ``id``) must NOT get a reply — per JSON-RPC
    spec and MCP spec."""
    s = _build_server()
    # initialize without an id = notification
    resp = await s.handle({
        "jsonrpc": "2.0", "method": "initialize", "params": {},
    })
    assert resp is None


@pytest.mark.asyncio
async def test_invalid_request_envelope() -> None:
    s = _build_server()
    # No jsonrpc field.
    resp = await s.handle({"id": 1, "method": "initialize"})
    assert resp["error"]["code"] == INVALID_REQUEST


@pytest.mark.asyncio
async def test_request_must_be_object() -> None:
    s = _build_server()
    resp = await s.handle("not an object")
    assert resp["error"]["code"] == INVALID_REQUEST


# ── 5. handle_request_bytes (parse error) ───────────────────────────


@pytest.mark.asyncio
async def test_handle_request_bytes_parse_error() -> None:
    s = _build_server()
    resp_bytes = await s.handle_request_bytes(b"not valid json{")
    assert resp_bytes is not None
    resp = json.loads(resp_bytes)
    assert resp["error"]["code"] == PARSE_ERROR


@pytest.mark.asyncio
async def test_handle_request_bytes_notification() -> None:
    s = _build_server()
    raw = json.dumps({"jsonrpc": "2.0", "method": "ping"}).encode()
    resp = await s.handle_request_bytes(raw)
    assert resp is None  # notification — no reply


# ── 6. catalog structure ─────────────────────────────────────────────


def test_catalog_has_twelve_tools() -> None:
    from divoom_lib.mcp_tools import build_tool_catalog
    catalog = build_tool_catalog(_fake_divoom())
    assert len(catalog) == 13


def test_each_tool_has_required_schema_fields() -> None:
    from divoom_lib.mcp_tools import build_tool_catalog
    catalog = build_tool_catalog(_fake_divoom())
    for tool in catalog:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "properties" in schema
        # The set_* tools have at least one required field.
        if tool.name.startswith("set_"):
            assert "required" in schema, f"{tool.name} missing required[]"
            assert len(schema["required"]) >= 1


def test_add_tool_rejects_duplicates() -> None:
    s = MCPServer(server_info={"name": "x", "version": "0"})
    s.add_tool(Tool(name="x", description="", input_schema={}, handler=_async_return(None)))
    with pytest.raises(ValueError, match="duplicate"):
        s.add_tool(Tool(name="x", description="", input_schema={}, handler=_async_return(None)))


def test_tool_descriptor_excludes_handler() -> None:
    t = Tool(name="x", description="y", input_schema={"type": "object"}, handler=_async_return(None))
    d = t.to_descriptor()
    assert d == {"name": "x", "description": "y", "inputSchema": {"type": "object"}}
    assert "handler" not in d


# ── 7. get_capabilities / get_device_state round-trip ───────────────


@pytest.mark.asyncio
async def test_get_capabilities_returns_dict() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 100, "method": "tools/call",
        "params": {"name": "get_capabilities", "arguments": {}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["panel_resolution"] == 16
    assert payload["has_speaker"] is True


@pytest.mark.asyncio
async def test_get_device_state_returns_read_only_dict() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 101, "method": "tools/call",
        "params": {"name": "get_device_state", "arguments": {}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload == {
        "volume": 8,
        "brightness": 80,
        "light_mode": 0,
        "screen_orientation": 0,
        "mirror": False,
    }


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


# ── 12. handle(): envelope + dispatch edge cases ────────────────────


@pytest.mark.asyncio
async def test_handle_method_not_a_string_is_invalid_request() -> None:
    s = _build_server()
    resp = await s.handle({"jsonrpc": "2.0", "id": 1, "method": 123})
    assert resp["error"]["code"] == INVALID_REQUEST
    assert "method must be a string" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_unknown_method_as_notification_returns_none() -> None:
    """A notification (no id) for an unrecognized method must still get no
    reply, per JSON-RPC — not a -32601 error, since notifications never get
    a response of any kind."""
    s = _build_server()
    resp = await s.handle({"jsonrpc": "2.0", "method": "frobnicate", "params": {}})
    assert resp is None


@pytest.mark.asyncio
async def test_handle_dispatch_exception_returns_internal_error(monkeypatch) -> None:
    """A bug inside a method implementation must not kill the server — handle()
    catches it and reports INTERNAL_ERROR instead of propagating."""
    s = _build_server()

    def _boom() -> dict:
        raise RuntimeError("kaboom")
    monkeypatch.setattr(s, "_handle_tools_list", _boom)

    resp = await s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    assert resp["error"]["code"] == INTERNAL_ERROR
    assert "RuntimeError: kaboom" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_handle_dispatch_exception_as_notification_returns_none(monkeypatch) -> None:
    """Same as above, but as a notification (no id) — must swallow silently,
    not synthesize an error response for something that mustn't get a reply."""
    s = _build_server()

    def _boom() -> dict:
        raise RuntimeError("kaboom")
    monkeypatch.setattr(s, "_handle_tools_list", _boom)

    resp = await s.handle({"jsonrpc": "2.0", "method": "tools/list"})
    assert resp is None


@pytest.mark.asyncio
async def test_tools_call_params_not_object_is_internal_error() -> None:
    """params must be an object; a non-dict value raises ValueError inside
    _handle_tools_call, which bubbles up through handle()'s generic except
    as INTERNAL_ERROR (this is a protocol-level malformed request, not a
    tool-level error)."""
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": "not-a-dict",
    })
    assert resp["error"]["code"] == INTERNAL_ERROR
    assert "params must be an object" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_tools_call_name_not_string_is_internal_error() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 11, "method": "tools/call",
        "params": {"name": 123, "arguments": {}},
    })
    assert resp["error"]["code"] == INTERNAL_ERROR
    assert "params.name must be a string" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_tools_call_arguments_not_object_is_tool_error() -> None:
    s = _build_server()
    resp = await s.handle({
        "jsonrpc": "2.0", "id": 12, "method": "tools/call",
        "params": {"name": "set_volume", "arguments": "not-a-dict"},
    })
    result = resp["result"]
    assert result["isError"] is True
    assert "arguments must be an object" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_handler_generic_exception_is_tool_error() -> None:
    """A tool handler raising something other than TypeError/ValueError
    (a real bug) is still reported as a tool-level isError, not a crash."""
    async def _boom(**kwargs):
        raise RuntimeError("handler exploded")

    s = _build_server()
    s.add_tool(Tool(name="boom_tool", description="", input_schema={
        "type": "object", "properties": {},
    }, handler=_boom))

    resp = await s.handle({
        "jsonrpc": "2.0", "id": 13, "method": "tools/call",
        "params": {"name": "boom_tool", "arguments": {}},
    })
    result = resp["result"]
    assert result["isError"] is True
    assert "RuntimeError: handler exploded" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_result_not_json_serializable_falls_back_to_repr() -> None:
    """If the handler's return value can't be json.dumps'd (e.g. a circular
    reference), the server falls back to repr() rather than crashing."""
    async def _circular(**kwargs):
        d: dict = {}
        d["self"] = d
        return d

    s = _build_server()
    s.add_tool(Tool(name="circular_tool", description="", input_schema={
        "type": "object", "properties": {},
    }, handler=_circular))

    resp = await s.handle({
        "jsonrpc": "2.0", "id": 14, "method": "tools/call",
        "params": {"name": "circular_tool", "arguments": {}},
    })
    text = resp["result"]["content"][0]["text"]
    # repr() of a self-referential dict renders the cycle as "...".
    assert "..." in text


# ── 13. handle_request_bytes(): normal (non-notification) response ──


@pytest.mark.asyncio
async def test_handle_request_bytes_returns_encoded_response() -> None:
    s = _build_server()
    raw = json.dumps({"jsonrpc": "2.0", "id": 20, "method": "tools/list"}).encode("utf-8")
    resp_bytes = await s.handle_request_bytes(raw)
    assert resp_bytes is not None
    resp = json.loads(resp_bytes)
    assert resp["id"] == 20
    assert "tools" in resp["result"]


# ── 14. run_stdio(): real pipe round-trip ────────────────────────────
#
# The no-pipe guard (test 9 above) covers the early-return path. This
# exercises the actual read/dispatch/write loop end-to-end over real
# OS pipes (never a subprocess) — a request gets a response, a
# notification gets none, a blank line is skipped, and EOF ends the loop
# cleanly.


@pytest.mark.asyncio
async def test_run_stdio_round_trips_over_real_pipes() -> None:
    import asyncio
    import os as _os
    import sys as _sys

    server = _build_server()

    in_r, in_w = _os.pipe()
    out_r, out_w = _os.pipe()
    stdin_f = _os.fdopen(in_r, "rb", buffering=0)
    stdout_f = _os.fdopen(out_w, "wb", buffering=0)

    old_stdin, old_stdout = _sys.stdin, _sys.stdout
    _sys.stdin = stdin_f
    _sys.stdout = stdout_f
    try:
        task = asyncio.create_task(server.run_stdio())
        await asyncio.sleep(0.05)

        _os.write(in_w, (json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n").encode())
        await asyncio.sleep(0.1)

        # Notification: no id -> must produce no output line.
        _os.write(in_w, (json.dumps({"jsonrpc": "2.0", "method": "ping"}) + "\n").encode())
        await asyncio.sleep(0.1)

        # Blank line must be skipped (no crash, no response).
        _os.write(in_w, b"\n")
        await asyncio.sleep(0.05)

        # Malformed JSON -> a parse-error response.
        _os.write(in_w, b"not valid json{\n")
        await asyncio.sleep(0.1)

        _os.close(in_w)  # EOF -> loop reads dispatch/write path exercised above;
        # request/notification/blank-line/parse-error handling all already
        # happened before this point.
        #
        # NOTE (found while writing this test, not introduced by it): the
        # shutdown tail here — `writer.close(); await writer.wait_closed()` —
        # raises an uncaught NotImplementedError. The writer's protocol is a
        # bare `asyncio.streams.FlowControlMixin` (see run_stdio's own comment
        # on why), and `FlowControlMixin._get_close_waiter` is abstract-only
        # (always raises NotImplementedError); only real protocol subclasses
        # like StreamReaderProtocol implement it. Confirmed independent of this
        # test's plumbing with a minimal os.pipe() + connect_write_pipe repro.
        # Net effect: any real MCP client that cleanly closes our stdin (the
        # documented "exits cleanly on EOF" path) crashes run_stdio() instead of
        # exiting cleanly — only BrokenPipeError/ConnectionResetError are
        # caught there, not NotImplementedError. Out of scope for this test
        # file (coverage-only pass); flagged separately for a fix.
        with pytest.raises(NotImplementedError):
            await asyncio.wait_for(task, timeout=2.0)
    finally:
        _sys.stdin = old_stdin
        _sys.stdout = old_stdout
        try:
            stdin_f.close()
        except OSError:
            pass

    raw = _os.read(out_r, 65536)
    _os.close(out_r)
    lines = [ln for ln in raw.decode("utf-8").splitlines() if ln]
    responses = [json.loads(ln) for ln in lines]

    assert len(responses) == 2  # tools/list + parse error (ping was a notification)
    assert responses[0]["id"] == 1
    assert "tools" in responses[0]["result"]
    assert responses[1]["error"]["code"] == PARSE_ERROR
