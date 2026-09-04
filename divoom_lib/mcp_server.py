"""
R15 §5 — MCP server core.

A minimal MCP-compatible JSON-RPC server (stdio transport, spec
2024-11-05). The server holds a list of ``Tool`` definitions and
dispatches incoming ``tools/call`` requests to their handlers.

Wire format (per the canonical MCP 2024-11-05 spec)::

    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

is answered with::

    {"jsonrpc": "2.0", "id": 1, "result": {"tools": [...]}}

A tool call::

    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
     "params": {"name": "set_volume", "arguments": {"level": 8}}}

is answered with::

    {"jsonrpc": "2.0", "id": 2, "result":
        {"content": [{"type": "text", "text": "{\\"ok\\": true}"}]}}

Errors use the standard JSON-RPC error codes:

    -32700  Parse error
    -32600  Invalid request
    -32601  Method not found
    -32602  Invalid params
    -32603  Internal error

Usage (programmatic)::

    from divoom_lib.mcp_server import MCPServer
    from divoom_lib.mcp_tools import build_tool_catalog
    from divoom_lib import Divoom

    server = MCPServer(server_info={"name": "divoom-control", "version": "0.15.0"})
    divoom = Divoom(mac="...")
    await divoom.connect()
    server.tools = build_tool_catalog(divoom)
    await server.run_stdio()

Usage (CLI)::

    divoom-control mcp-server --mac 11:75:58:3f:fd:aa

The server reads JSON-RPC messages from stdin (one per line) and
writes responses to stdout. Logging goes to stderr so the JSON-RPC
stream stays clean.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import stat
import sys
from typing import Any, Awaitable, Callable, Optional


logger = logging.getLogger(__name__)


def _stdio_is_pipe_like(stream: Any) -> bool:
    """True if ``stream``'s fd is a pipe, socket, or character device — the
    only kinds asyncio's ``connect_read_pipe`` / ``connect_write_pipe`` accept.

    A regular file (e.g. stdout redirected to a log file, or ``> out.txt``)
    returns False: asyncio's ``_UnixWritePipeTransport`` raises
    ``ValueError("Pipe transport is only for pipes, sockets and character
    devices")`` for those, which is exactly the crash the GUI's "Start MCP
    server" toggle produced (it spawns us with stdout pointed at a log file).
    A missing / detached fd also returns False."""
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    try:
        mode = os.fstat(fd).st_mode
    except OSError:
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode) or stat.S_ISCHR(mode)


# ── JSON-RPC error codes (standard) ──────────────────────────────────


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ── Tool definition ───────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Tool:
    """A single tool that the MCP server exposes.

    Attributes:
        name: Tool name (must be unique within the catalog).
        description: Human-readable one-liner for clients.
        input_schema: JSON Schema dict for the tool's arguments.
        handler: Async callable ``(divoom, **args) -> Any`` that
            performs the tool's work. The return value is JSON-serialized
            and wrapped in a ``{"type": "text", "text": "..."}`` content
            block.
    """

    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Awaitable[Any]]

    def to_descriptor(self) -> dict:
        """Return the tool's descriptor (name, description, schema) for
        ``tools/list`` responses. Excludes the handler."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ── JSON-RPC envelope helpers ────────────────────────────────────────


def _jsonrpc_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ── Server core ───────────────────────────────────────────────────────


class MCPServer:
    """Minimal MCP server. Holds a tool catalog and dispatches requests.

    The server does NOT own the ``Divoom`` instance — that's the
    caller's responsibility. The catalog is parameterized over the
    Divoom instance by ``build_tool_catalog(divoom)``.
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        server_info: dict,
        protocol_version: str = PROTOCOL_VERSION,
    ) -> None:
        self.server_info = dict(server_info)
        self.protocol_version = protocol_version
        self.tools: list[Tool] = []
        self._initialized = False
        # Cached for tests + the stdio loop.
        self.last_request: Optional[dict] = None
        self.last_response: Optional[dict] = None

    # ── Tool registration ───────────────────────────────────────────

    def add_tool(self, tool: Tool) -> None:
        if any(t.name == tool.name for t in self.tools):
            raise ValueError(f"duplicate tool name: {tool.name!r}")
        self.tools.append(tool)

    def get_tool(self, name: str) -> Optional[Tool]:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    # ── Request dispatch ────────────────────────────────────────────

    async def handle(self, request: Any) -> Optional[dict]:
        """Handle a single decoded JSON-RPC request.

        Returns the response dict, or None for JSON-RPC notifications
        (requests without an ``id`` field — the spec says we must not
        reply to those)."""

        # Validate envelope.
        if not isinstance(request, dict):
            return _jsonrpc_error(None, INVALID_REQUEST, "request must be a JSON object")
        if request.get("jsonrpc") != "2.0":
            return _jsonrpc_error(
                request.get("id"), INVALID_REQUEST, "jsonrpc must be '2.0'"
            )
        method = request.get("method")
        if not isinstance(method, str):
            return _jsonrpc_error(
                request.get("id"), INVALID_REQUEST, "method must be a string"
            )
        req_id = request.get("id")
        is_notification = req_id is None

        try:
            if method == "initialize":
                result = self._handle_initialize(request.get("params") or {})
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = await self._handle_tools_call(request.get("params") or {})
            elif method == "ping":
                result = {}
            else:
                if is_notification:
                    return None
                return _jsonrpc_error(req_id, METHOD_NOT_FOUND, f"method not found: {method!r}")
        except Exception as exc:  # last-ditch — never let a bug kill the server
            logger.exception("handler %s raised", method)
            if is_notification:
                return None
            return _jsonrpc_error(
                req_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"
            )

        if is_notification:
            return None
        return _jsonrpc_response(req_id, result)

    # ── Method implementations ──────────────────────────────────────

    def _handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": self.server_info,
        }

    def _handle_tools_list(self) -> dict:
        return {"tools": [t.to_descriptor() for t in self.tools]}

    async def _handle_tools_call(self, params: dict) -> dict:
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        name = params.get("name")
        if not isinstance(name, str):
            raise ValueError("params.name must be a string")
        tool = self.get_tool(name)
        if tool is None:
            # Per MCP spec, unknown tool calls are reported as tool errors,
            # not protocol errors. We use isError=True to keep the
            # protocol-level response valid.
            return {
                "content": [{"type": "text", "text": f"unknown tool: {name!r}"}],
                "isError": True,
            }
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {
                "content": [{"type": "text", "text": "arguments must be an object"}],
                "isError": True,
            }
        try:
            result = await tool.handler(**arguments)
        except TypeError as exc:
            # Bad argument shape (missing required arg, wrong kwarg).
            return {
                "content": [{"type": "text", "text": f"invalid arguments: {exc}"}],
                "isError": True,
            }
        except ValueError as exc:
            # Domain validation (out-of-range level, etc.).
            return {
                "content": [{"type": "text", "text": f"invalid arguments: {exc}"}],
                "isError": True,
            }
        except Exception as exc:
            logger.exception("tool %s raised", name)
            return {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            }
        # Serialize the result. JSON-friendly values go through json.dumps;
        # everything else through repr so the client at least sees
        # something structured.
        try:
            text = json.dumps(result, default=str)
        except (TypeError, ValueError):
            text = repr(result)
        return {"content": [{"type": "text", "text": text}]}

    # ── Transport ───────────────────────────────────────────────────

    async def run_stdio(self) -> None:
        """Run the server loop reading from stdin / writing to stdout.

        Each stdin line is one JSON-RPC message; each stdout line is
        one response. The loop exits cleanly on EOF (stdin closed —
        what the parent process does when it wants to stop us)."""
        loop = asyncio.get_running_loop()
        # An MCP stdio server only works when stdin *and* stdout are pipes owned
        # by the MCP client that launched us (Claude Desktop, Cursor, ...). If
        # stdout is a regular file — the GUI spawns us with stdout redirected to
        # a log file, or a user runs `divoom-control mcp-server > out.txt` — then
        # `connect_write_pipe` below raises a multi-frame ValueError traceback
        # ("Pipe transport is only for pipes, sockets and character devices").
        # Detect that up front and exit with a single clean diagnostic instead
        # of spewing a traceback into the log the GUI card surfaces.
        if not _stdio_is_pipe_like(sys.stdin) or not _stdio_is_pipe_like(sys.stdout):
            sys.stderr.write(
                "MCP server: stdin/stdout are not connected to an MCP client. "
                "The stdio transport needs pipes owned by the client, so launch "
                "this from your MCP client's config (Claude Desktop, Cursor, ...), "
                "not standalone or from the GUI. See docs/MCP_SERVER.md.\n"
            )
            sys.stderr.flush()
            return
        # No `loop=` kwarg: StreamReader binds to the running loop on its own
        # (the explicit param has been deprecated since 3.8). Verified no
        # DeprecationWarning on 3.14. See REVIEW_2026-06 §0.1 (1.8).
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        # stdout is line-buffered for write; use a small writer.
        # `FlowControlMixin` is a private symbol but has no public equivalent
        # for `connect_write_pipe`; it is stable (not deprecated) on 3.14.
        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)
        while True:
            try:
                line = await reader.readline()
            except (asyncio.IncompleteReadError, ConnectionResetError):
                break
            if not line:
                break  # EOF
            try:
                text = line.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                # Per spec, log and skip — never break the loop on a
                # bad line.
                logger.warning("ignoring non-utf-8 line: %s", exc)
                continue
            if not text:
                continue
            try:
                request = json.loads(text)
            except json.JSONDecodeError as exc:
                response = _jsonrpc_error(None, PARSE_ERROR, f"parse error: {exc}")
            else:
                self.last_request = request
                response = await self.handle(request)
                self.last_response = response
            if response is None:
                # Notification — no reply.
                continue
            data = (json.dumps(response) + "\n").encode("utf-8")
            try:
                writer.write(data)
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                # The MCP client closed our stdout (teardown) — exit the loop
                # cleanly, the same as the read-side EOF guard, instead of letting
                # the write race crash run_stdio with a traceback in the client log.
                break
        writer.close()
        try:
            await writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ── Convenience: feed a single request, get a single response ──

    async def handle_request_bytes(self, raw: bytes) -> Optional[bytes]:
        """Test helper: feed a single JSON-RPC request, return the
        single response (or None for a notification)."""
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as exc:
            return json.dumps(_jsonrpc_error(None, PARSE_ERROR, str(exc))).encode("utf-8")
        response = await self.handle(request)
        if response is None:
            return None
        return json.dumps(response).encode("utf-8")
