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

The server exposes 25 tools via `tools/list`. Every integer range below is stated once, in `divoomd/src/arg_bounds.rs`: the schema is generated from it, the tool checks it, and the daemon handler that receives the value refuses outside it.

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
| `show_image` | `{file: string, resize?: "fit"\|"fill"\|"exact"\|"none", size?: 8..128}` | Decode a local image file (PNG/JPEG/GIF) and draw it at the panel's own resolution (its `width` from `device_status`; pass `size` for a panel with no model name). `resize` (default `fit`): `fit` keeps the whole image and pads black, `fill` covers and crops, `exact` stretches, `none` requires the image to be the panel's size already and is an error otherwise. Colours are reduced to the 256-colour frame palette only when the image has more. Returns `{ok, file, size, resize}`. |
| `push_animation` | `{file?: string, data?: string, resize?, size?}` | Play an animation from a local file path or base64-encoded data: every frame, each for its own duration (GIF delays, 50 ms minimum), at the panel's resolution under the same `resize` policy as `show_image`. Returns `{ok, size, resize, frames}`. |
| `play_sound` | `{duration_ms: int (100..3000)}` | Trigger hardware buzzer alert tone. Returns `{ok, duration_ms}`. |
| `get_capabilities` | `{mac?}` | Describe one panel (the named one, else the active one): link state, `model`, `width`/`height` and how they were decided (`model_source`), and `features` -- what the vendor app enables for that model (`speaker`, `sd_card`, `temp_sensor`, `wifi`, `clock_style`), `null` for an unrecognised model. No FM-radio flag: the vendor app does not decide FM per model. |
| `get_device_state` | `{}` | Read current volume, brightness, active light mode, orientation, and mirror settings. Values are `null` when the daemon cannot be reached, so absent data is never shown as a real reading. A field the daemon could not read is `null` AND named in `errors` with the daemon's reason and code -- a null is never the only thing you know (P2.8). The orientation and the mirror are set by the daemon and never read back, so they are always `null` with `unsupported`. |
| `list_screens` | `{}` | List every screen the daemon knows or the saved layout places, in `screens`: each with `mac`, `connected` (live link), `selected`, `model`, `width`/`height` (`null` for a placed panel never seen), `features`, and its saved `x`/`y`/`room`; plus wall state and slots. The one tool the Python server never had. |
| `show_text` | `{text: string, color?: "#RRGGBB", size?: 8..128}` | Draw text in the device font at the panel's resolution (the frame `render_widget`'s `text` kind previews; panels over 64 px get it scaled by a whole factor). Returns `{ok, text, size}`. |
| `live_job_start` | `{kind: "sysmon"\|"stocks"\|"weather"\|"music", params?: object}` | Start a live widget on the named (else the active) panel, replacing the one it runs. `params.size` defaults to the panel's width. `stocks` needs `params.symbol`; `music` needs macOS. Returns `{ok, mac, kind, params}`. |
| `live_job_stop` | `{kind}` | Stop that panel's live widget of this kind. Returns `{ok, mac, kind, stopped}`. |
| `live_job_list` | `{mac?}` | The live widgets running, on one panel or all. |
| `set_scoreboard` | `{red_score: 0..999, blue_score: 0..999, on?: bool}` | Show (or with `on: false` hide) the scoreboard. |
| `set_timer` | `{action: "start"\|"stop"\|"reset"}` | Control the stopwatch. |
| `set_countdown` | `{action: "start"\|"stop", minutes?: 0..99, seconds?: 0..59}` | Start a countdown, or stop the running one. |
| `lease_acquire` | `{ttl_ms: 1000..600000, holder?: string, mac?}` | Borrow the panel's screen. Returns `{ok, lease, mac, holder, ttl_ms}`. Pass `lease` to every call while you hold it; anyone else is refused with the holder's name and the time left. The panel's live widget pauses (its frames keep rendering and are held back, the widget is not stopped). |
| `lease_renew` | `{lease, ttl_ms}` | Move the lease's end to `ttl_ms` from now. A lease that already ended cannot be renewed. |
| `lease_release` | `{lease}` | Give the screen back. Returns `restored`: `"job"` (the live widget's newest frame is painted at once) or `"none"` (no widget was running; the panel keeps your last frame). |
| `notify` | `{text: string, duration_ms: 1000..60000, color?: "#RRGGBB", size?: 8..128, mac?}` | Show a short message for `duration_ms`, then give the panel back. The text is drawn like `show_text`, under a screen lease whose TTL is the duration; the call returns at once and the lease lapses by itself, so a caller that dies cannot leave the message up. Refused (`screen_leased`) while someone else holds the panel. Returns `{ok, text, size, duration_ms, mac, lease}`; `lease_release` with that `lease` dismisses it early. |

### Screen leases

An agent that draws on a panel with a live widget running would be painted
over on the widget's next tick, and an agent that crashes would leave its
frame up for good. A lease is the borrow with the return built in:

- **The TTL is mandatory** and bounded (1 s to 10 min, `LEASE_TTL_MS` in
  `arg_bounds.rs`). Renew before it runs out. A lease nobody renews ends by
  itself, and the panel goes back to its widget as if released.
- **Every tool that reaches a panel takes `lease`**, the token
  `lease_acquire` returned, and sends it with each daemon call. Without it,
  a call to a leased panel is refused.
- **Frame pushes conflate.** When several `show_image`/`push_animation`/
  `show_text` calls queue up on a slow link, only the newest is drawn; the
  others answer `superseded`.
- **`notify` is a lease that ends by itself**: its TTL is the notification's
  duration, so the message comes down when the lease lapses, with the same
  hand-back as any other lease (the widget's newest frame, or `restored:
  "none"` on a panel with no widget; ROADMAP P9.7).
- Every change is announced on the daemon's event stream as
  `{"type": "lease", "state": "acquired" | "released" | "expired", ...}`.

### Validation and Error Handling
- Protocol-level validation errors (missing arguments, invalid JSON) return standard JSON-RPC error codes (`-32602`, `-32700`, etc.).
- Domain errors (values out of range, unparseable images, device communication timeouts) return a tool result with `isError: true` and an explanatory error message, enabling clients to recover and self-correct.
- Every daemon failure carries a stable `code` beside the prose: the tool
  result's JSON is `{"error": "...", "code": "..."}`, and the CLI prints
  `<message> [<code>]`. Branch on the code, never on the wording; a code's
  meaning never changes once shipped. The daemon cannot send a failure
  without one (`divoomd/src/error_code.rs`; ROADMAP P5.10).

<!-- error-codes:start -->
| Code | Meaning | What a client can do |
|---|---|---|
| `bad_request` | The request is malformed: a missing or mistyped argument, a value out of range, an image or file that cannot be read or decoded. | Fix the request; retrying it unchanged will fail again. |
| `unknown_command` | The daemon does not implement this command or `device_call` method. | Check the daemon's `capabilities` (`get_status`). |
| `device_disconnected` | The panel named is not connected -- or the command could not be sent, so its link is gone (P2.8). The daemon retires the link and reports the drop. | Reconnect it. |
| `no_device` | No panel is connected at all (for a wall call: no wall is configured). | Connect a panel, or configure the wall. |
| `unknown_device` | The panel named has never been linked to this daemon, or `disconnect` forgot it. | Link it first. |
| `ambiguous_target` | Several panels are linked, none is active, and the request named none. | Pass `mac`. |
| `deadline_exceeded` | The command outran its time budget. | Retry; check the panel's link. |
| `resource_exhausted` | The daemon is at its connection or subscription cap. | Retry with jitter. |
| `notification_db_missing` | The macOS Notification Center database was not found. | Nothing to forward from. |
| `notification_db_unreadable` | The database exists but cannot be read (macOS: no Full Disk Access). | Grant Full Disk Access. |
| `unsupported` | Not available here: on this platform, in this build, or over this panel's link (a LAN panel has no Bluetooth-only command; the reply's `cause` says which). | Hide the feature for this panel or host. |
| `screen_leased` | Another holder leases this panel's screen; the reply says who and for how long. | Wait for the lease, or ask its holder. |
| `lease_expired` | The lease token is not (or no longer) the panel's lease. | Acquire a new lease. |
| `device_failed` | The panel is there and did not do what was asked: a reply never came, an answer could not be read, a connect or scan failed, a wall panel did not take the command (the reply's `failed` maps each such slot to its reason, and `degraded` lists each slot with no panel). A command that could not be SENT is `device_disconnected`, not this. | Retry, or check the panel. |
| `busy` | The daemon is already doing this (a scan, a connect, a hot update), or another session holds the panel exclusively. | Retry when it is done. |
| `unauthorized` | The request's token does not match the daemon's. | Resend with the right token. |
| `upstream_failed` | A network service the daemon calls for you (the Divoom cloud, a weather or quote provider) failed or refused. | Check the network or the account; the panel is not involved. |
| `internal` | Something inside the daemon or on its host failed (a file it could not write, a host service that errored, a daemon not fully started). | Report it; not the request's or the panel's fault. |
<!-- error-codes:end -->

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
