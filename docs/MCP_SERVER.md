# MCP Server

The `divoom-control` project ships a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server conforming to the MCP 2024-11-05 specification. The server speaks JSON-RPC 2.0 over standard I/O (stdio) and exposes 13 device-control tools, allowing AI coding assistants and automation clients to monitor and control Divoom devices.

## Architecture

The MCP server operates as a thin client to the `divoomd` background daemon:
- **Single-Owner Device Model**: The daemon owns the active Bluetooth (BLE/SPP) or LAN connection. The MCP server does not open its own Bluetooth connection.
- **Daemon Routing**: Every MCP tool call is forwarded to the daemon socket (Unix domain socket `/tmp/divoom.sock` by default, or remote TCP via `--host`/`--port`/`--token`).
- **Device Targeting**: Because the daemon manages the active connection, specifying a MAC address is not required during normal operation.
- **Implementations**:
  - **Native (`divoomd mcp`)**: Compiled Rust implementation bundled within the application. Minimal resource footprint and fast startup.
  - **Python (`divoom-control mcp-server`)**: Python CLI implementation routing through `DaemonDeviceProxy`.

## Quick Start

### Running the Native Server (Recommended)
```bash
divoomd mcp
```

### Running the Python CLI Server
```bash
# Connect to local daemon (auto-spawns daemon if not running):
divoom-control mcp-server

# Connect to a remote daemon over TCP:
divoom-control mcp-server --host 192.168.1.50 --port 9009 --token <secret>
```

Command-line options (Python CLI):
- `--socket <path>`: Path to local daemon Unix domain socket (default: `/tmp/divoom.sock`).
- `--host <ip_or_name>`: Remote daemon TCP host (sets `DIVOOM_DAEMON_HOST`).
- `--port <number>`: Remote daemon TCP port (default: `9009`).
- `--token <secret>`: Shared secret token for authenticated TCP connections.

## Tool Catalog

The server exposes 13 tools via `tools/list`:

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
| `get_device_state` | `{}` | Read current volume, brightness, active light mode, orientation, and mirror settings. |

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

Conforms to standard MCP 2024-11-05:

### Initialize Request
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
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
    "protocolVersion": "2024-11-05",
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
