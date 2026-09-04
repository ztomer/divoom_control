# MCP Server (R15 §5)

The divoom-control project ships an [MCP](https://modelcontextprotocol.io/)
(Model Context Protocol) server. The server speaks JSON-RPC 2.0 over
stdio and exposes 12 device-control tools. Point any MCP-compatible
client at this machine's `divoom-control` binary and you can drive
your Divoom device with natural language.

## Architecture (R28): the MCP server is a daemon client

The MCP server does **not** open its own BLE connection. The daemon is the sole
owner of the device (R17 single-owner model), so the MCP server builds its tool
catalog against a `DaemonDeviceProxy` and routes every tool call through the
daemon's `device_call` RPC. It connects to the local daemon socket (auto-spawning
one if none is running) or, with `--host`, to a remote daemon over TCP.

Consequence: **`--mac` is optional** — the daemon already knows the device. (Pre-
R28 the server called `_resolve_device()` and grabbed its own BLE connection,
which fought the daemon and failed with `DeviceConnectionError: ... not found`.)

## Quick start

```bash
# CLI path (scriptable). No --mac needed; auto-spawns a local daemon if needed.
divoom-control mcp-server

# Pin a device (only matters if a daemon has to be spawned):
divoom-control mcp-server --mac 11:75:58:3f:fd:aa

# Target a remote/headless daemon over TCP (R19 network server):
divoom-control mcp-server --host 192.168.1.50 --port 9009 --token <secret>

# GUI path (Settings → Connectivity → MCP Server → Start)
# The GUI spawns the same subprocess and tails the log file.
```

Flags: `--socket` (daemon Unix socket, default `/tmp/divoom.sock`),
`--host`/`--port`/`--token` (remote daemon; `--token` falls back to
`DIVOOM_DAEMON_TOKEN`).

The server reads JSON-RPC messages from stdin and writes responses
to stdout. It runs until stdin closes (the parent MCP client closes
its end when it wants to stop us).

## Tool catalog (initial)

| Tool | Args | Returns |
|------|------|---------|
| `set_volume` | `{level: int 0-15}` | `{ok, level}` |
| `set_brightness` | `{level: int 0-100}` | `{ok, level}` |
| `set_light_mode` | `{mode: clock\|lightning\|cloud\|vj\|visualizer\|design\|scoreboard\|animation}` | `{ok, mode, channel}` |
| `set_weather` | `{temperature_c: int -127..128, weather: clear\|cloudy\|thunderstorm\|rain\|snow\|fog}` | `{ok, temperature_c, weather}` |
| `set_alarm` | `{index: 0-9, hour: 0-23, minute: 0-59, weekday_mask: 0-127, enabled: bool}` | `{ok, ...}` |
| `set_radio` | `{freq_x10: 875-1080}` | `{ok, freq_x10}` |
| `set_low_power` | `{enabled: bool}` | `{ok, enabled}` |
| `set_screen_orientation` | `{degrees: 0\|90\|180\|270, mirror: bool}` | `{ok, degrees, mirror}` |
| `show_image` | `{file: local_path}` | `{ok, file}` |
| `play_sound` | `{duration_ms: 100-3000}` | `{ok, duration_ms}` (best-effort) |
| `get_capabilities` | `{}` | `{panel_resolution, has_speaker, has_clock, ...}` |
| `get_device_state` | `{}` | `{volume, brightness, light_mode, screen_orientation, mirror}` |

Out-of-range values and unknown enum strings are returned as
`isError: true` content blocks with a human-readable message. The
client can show the message to the user verbatim.

## Client setup

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "divoom-control",
      "args": ["mcp-server", "--mac", "11:75:58:3f-fd-aa"]
    }
  }
}
```

If `divoom-control` isn't on PATH, use the full path:

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "/usr/local/bin/divoom-control",
      "args": ["mcp-server", "--mac", "11-75-58-3f-fd-aa"]
    }
  }
}
```

### Cursor

Cursor reads MCP config from `~/.cursor/mcp.json` (macOS) or
`%USERPROFILE%\.cursor\mcp.json` (Windows):

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "divoom-control",
      "args": ["mcp-server", "--mac", "11-75-58-3f-fd-aa"]
    }
  }
}
```

Restart Cursor after editing the config.

### Cline (VS Code extension)

Cline reads its MCP config from the VS Code settings UI
("Cline: MCP Servers" → "Edit MCP Settings"). The format is the
same — add a `divoom-control` entry under `mcpServers`.

### Continue (VS Code / JetBrains)

Continue reads MCP config from `~/.continue/config.json`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "name": "divoom-control",
        "command": "divoom-control",
        "args": ["mcp-server", "--mac", "11-75-58-3f-fd-aa"]
      }
    ]
  }
}
```

(Continue's schema may vary by version; the `name`/`command`/`args`
shape is the contract.)

## Verifying it works

Once the client is configured, ask it to do something:

> "Set the volume to 8 and switch to the lightning channel."

The client will translate that into two `tools/call` requests:
`set_volume {level: 8}` and `set_light_mode {mode: lightning}`. The
device should respond within ~50 ms and you'll see the new state on
the panel.

## Logs

When started from the GUI, logs go to
`~/.config/divoom-control/mcp-server.log`. The status display in
Settings → Connectivity tails the last 20 lines on a 5-second
poll so crashes surface quickly.

When started from the CLI, logs go to your terminal's stderr (the
subprocess never writes to stdout — that stream is reserved for
JSON-RPC responses).

## Wire format

We follow the [canonical MCP 2024-11-05 spec](https://spec.modelcontextprotocol.io/2024-11-05/).

**Initialize** (client → server):

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize",
 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "claude-desktop", "version": "1.0.0"}}}
```

**Initialize** (server → client):

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "protocolVersion": "2024-11-05",
  "capabilities": {"tools": {}},
  "serverInfo": {"name": "divoom-control", "version": "0.15.0"}}}
```

**List tools** (request): `{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}`

**List tools** (response): `{"jsonrpc": "2.0", "id": 2, "result": {"tools": [...]}}`

**Call a tool** (request):

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "set_volume", "arguments": {"level": 8}}}
```

**Call a tool** (response):

```json
{"jsonrpc": "2.0", "id": 3, "result": {
  "content": [{"type": "text", "text": "{\"ok\": true, \"level\": 8}"}]}}
```

Errors use the standard JSON-RPC error codes:
`-32700` (parse), `-32600` (invalid request), `-32601` (method
not found), `-32602` (invalid params), `-32603` (internal error).
Tool-level domain errors (out-of-range, unknown enum) come back
as `isError: true` content blocks, not protocol errors — this
matches the MCP spec and lets the LLM see the message and
self-correct.

## Troubleshooting

- **"divoom-control: command not found"** — install the package
  editable: `pip install -e .` (R14 §4). Or use the full path in
  the MCP config.
- **Subprocess dies immediately** — check
  `~/.config/divoom-control/mcp-server.log` for the Python traceback.
  Most common cause: the MAC is wrong or the device is out of range.
- **No response from a tool call** — make sure you sent the request
  to *this* subprocess's stdin, not the GUI's. The GUI's stdin is
  not connected to the MCP server.

## Why subprocess, not in-process

The GUI uses pywebview, which owns the main event loop. An
in-process stdio server would fight pywebview over file descriptors
and risk deadlocking the GUI. Spawning the server as a subprocess
keeps the streams clean: stdin/stdout are owned by the MCP client
parent process, stderr is logged to a file.

This also means a bug in the MCP server can't take down the GUI —
the worst case is a stuck subprocess that the user can stop from
Settings → Connectivity.
