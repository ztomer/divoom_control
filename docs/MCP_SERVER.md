# MCP Server

The `divoom-control` project ships a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server speaking JSON-RPC 2.0 over standard I/O (stdio) and exposing 14 device-control tools, allowing AI coding assistants and automation clients to monitor and control Divoom devices. Protocol negotiation follows SEP-2575: the server answers `initialize` with the client's requested `protocolVersion` when it is one it supports (`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, `2026-07-28`), else the latest (`2026-07-28`). Extra `params` members such as `_meta` are tolerated.

## Architecture

The MCP server operates as a thin client to the `divoomd` background daemon:
- **Single-Owner Device Model**: The daemon owns the active Bluetooth (BLE/SPP) or LAN connection. The MCP server does not open its own Bluetooth connection.
- **Daemon Routing**: Every MCP tool call is forwarded to the daemon socket (Unix domain socket `/tmp/divoom.sock` by default, or remote TCP via `--host`/`--port`/`--token`).
- **Device Targeting**: Because the daemon manages the active connection, specifying a MAC address is not required during normal operation.
- **One Implementation**: the server is the Rust binary `divoomd mcp`, bundled with the application. There was a second, Python implementation (`divoom-control mcp-server`, routing through `DaemonDeviceProxy`) until 2026-09-25; it was deleted because the native catalog is a strict superset of it — same 13 tools plus `list_screens` — and two implementations of one MCP surface drift (they already had). The `divoom-control mcp-server` command still exists and is still what MCP client configs name, but it is now a handoff: it ensures a daemon is running and then `execv`s `divoomd mcp`, so a client config needs no change.

## Quick Start

### Running the Server

Either of these is the same process:

```bash
divoomd mcp                          # the server itself

divoom-control mcp-server            # ensures a daemon, then hands off to it
```

The second form is what an MCP client config should name, because it also
auto-spawns the daemon when none is running (`divoomd mcp` connects to a daemon
and does not start one). It `execv`s the native binary, so the daemon target
below reaches the server through the environment.

```bash
# Connect to a remote daemon over TCP:
divoom-control mcp-server --host 192.168.1.50 --port 9009 --token <secret>
```

Command-line options:
- `--socket <path>`: Path to local daemon Unix domain socket (default: `/tmp/divoom.sock`).
- `--host <ip_or_name>`: Remote daemon TCP host (sets `DIVOOM_DAEMON_HOST`).
- `--port <number>`: Remote daemon TCP port (default: `9009`).
- `--token <secret>`: Shared secret token for authenticated TCP connections.

## Tool Catalog

The server exposes 14 tools via `tools/list`:

| Tool | Arguments | Description / Returns |
|------|-----------|------------------------|
| `set_volume` | `{level: int (0..15)}` | Set speaker output volume. Returns `{ok, level}`. |
| `set_brightness` | `{level: int (0..100)}` | Set display brightness percentage. Returns `{ok, level}`. |
| `set_light_mode` | `{mode: string}` | Switch active channel: `clock`, `lightning`, `cloud`, `vj`, `visualizer`, `design`, `scoreboard`, `animation`. Returns `{ok, mode, channel}`. |
| `set_weather` | `{temperature_c: int (-127..128), weather: string}` | Push temperature and weather condition (`clear`, `cloudy`, `thunderstorm`, `rain`, `snow`, `fog`). Returns `{ok, temperature_c, weather}`. |
| `set_alarm` | `{index: int (0..9), hour: int (0..23), minute: int (0..59), weekday_mask?: int (0..127), enabled?: bool}` | Configure one of 10 device alarms. Returns `{ok, ...}`. |
| `set_radio` | `{freq_x10: int (875..1080)}` | Tune FM radio frequency (e.g. 101.1 MHz = 1011). Returns `{ok, freq_x10}`. |
| `set_low_power` | `{enabled: bool}` | Toggle low-power standby mode. Returns `{ok, enabled}`. |
| `set_screen_orientation` | `{degrees: int (0\|90\|180\|270), mirror?: bool}` | Rotate or flip panel display orientation. Returns `{ok, degrees, mirror}`. |
| `show_image` | `{file: string}` | Decode a local image file (PNG/JPEG/GIF) and display it on the panel. Returns `{ok, file}`. |
| `push_animation` | `{file?: string, data?: string}` | Push an animation or image via local file path or base64-encoded data. |
| `play_sound` | `{duration_ms: int (100..3000)}` | Trigger hardware buzzer alert tone. Returns `{ok, duration_ms}`. |
| `get_capabilities` | `{}` | Query device connection state, transport type, and MAC address. |
| `get_device_state` | `{}` | Read current volume, brightness, active light mode, orientation, and mirror settings. Values are `null` when the daemon cannot be reached, so absent data is never shown as a real reading. |
| `list_screens` | `{}` | List every known display screen: resolution, spatial coordinates, room, and wall grouping. The one tool the Python server never had. |

### Validation and Error Handling
- Protocol-level validation errors (missing arguments, invalid JSON) return standard JSON-RPC error codes (`-32602`, `-32700`, etc.).
- Domain errors (values out of range, unparseable images, device communication timeouts) return a tool result with `isError: true` and an explanatory error message, enabling clients to recover and self-correct.

## Client Configuration

Configure the MCP server in your client of choice.

### Cursor
Add to `~/.cursor/mcp.json` (macOS/Linux) or `%USERPROFILE%\.cursor\mcp.json` (Windows):

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "divoomd",
      "args": ["mcp"]
    }
  }
}
```

Or using the Python executable if running in a virtual environment:

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "divoom-control",
      "args": ["mcp-server"]
    }
  }
}
```

### Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "divoomd",
      "args": ["mcp"]
    }
  }
}
```

### VS Code / Cline
In VS Code settings under "Cline: MCP Servers" (or `cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "divoom-control": {
      "command": "divoomd",
      "args": ["mcp"]
    }
  }
}
```

### Continue (VS Code / JetBrains)
Add to `~/.continue/config.json`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "name": "divoom-control",
        "command": "divoomd",
        "args": ["mcp"]
      }
    ]
  }
}
```

## Transport & Process Model

- **Stdio Transport**: Stdin and stdout are strictly reserved for newline-delimited JSON-RPC messages. The MCP server process must be launched directly by the MCP client with connected pipes.
- **Logging**: Informational and debug logs are sent to `stderr` to prevent corrupting the JSON-RPC stream.
- **Lifecycle**: The server runs until stdin is closed by the parent process (client disconnect) or a termination signal is received.

## Wire Protocol Reference

Negotiated per SEP-2575 (supported: `2024-11-05`, `2025-03-26`,
`2025-06-18`, `2025-11-25`, `2026-07-28`; latest `2026-07-28`):

### Initialize Request
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2026-07-28",
    "capabilities": {},
    "clientInfo": {
      "name": "mcp-client",
      "version": "1.0.0"
    }
  }
}
```

### Initialize Response
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2026-07-28",
    "capabilities": {
      "tools": {}
    },
    "serverInfo": {
      "name": "divoom-control",
      "version": "0.34.0"
    }
  }
}
```

### Tool Execution Request
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "set_brightness",
    "arguments": {
      "level": 75
    }
  }
}
```

### Tool Execution Response
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"ok\": true, \"level\": 75}"
      }
    ]
  }
}
```
