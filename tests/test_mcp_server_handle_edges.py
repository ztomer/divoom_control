"""handle() / handle_request_bytes() / run_stdio() edge-case coverage for
the MCP server (split from test_mcp_server.py)."""
from __future__ import annotations

import json

import pytest

from divoom_lib.mcp_server import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    MCPServer,
    Tool,
)
from tests.support.mcp_server_common import (  # noqa: F401
    _async_return,
    _build_server,
    _fake_divoom,
)


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
