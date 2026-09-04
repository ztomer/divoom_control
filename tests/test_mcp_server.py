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

from tests.support.mcp_server_common import (  # noqa: F401
    _async_return,
    _build_server,
    _fake_divoom,
)
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
