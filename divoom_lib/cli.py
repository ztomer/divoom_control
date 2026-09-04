#!/usr/bin/env python3
"""
divoom-control CLI — command-line interface for the divoom_lib.

Usage:
    divoom-control scan [--timeout SECONDS]
    divoom-control capabilities [--mac AA:BB:CC:DD:EE:FF]
    divoom-control set-volume N  [--mac ...]
    divoom-control set-brightness N [--mac ...]
    divoom-control set-radio FREQ  [--mac ...]   (e.g. 875 = 87.5 MHz)
    divoom-control set-alarm HH:MM [--mac ...]
    divoom-control push-image PATH  [--mac ...]
    divoom-control push-gif PATH    [--mac ...]
    divoom-control pair --mac ... --type TivooMax
    divoom-control identify

A thin wrapper over the lib — it does connect / disconnect + one operation,
then exits. The goal is to be scriptable from cron, the menubar, or
shell pipelines. Use the GUI for interactive use.

Design notes:
- No argparse tree that requires every command to be registered; the
  top-level dispatcher does the routing. New commands are easy to add.
- All commands log to stderr; results print to stdout (so they can be piped).
- Exit codes: 0 = success, 1 = runtime error, 2 = usage error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from divoom_lib import Divoom
from divoom_lib.models.capabilities import (
    DEVICE_CAPABILITIES,
    DeviceRegistry,
)


# ── Argument parsing ───────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    # Shared options that should also be accepted AFTER the subcommand.
    # `parents=` makes argparse attach the same args to the top-level
    # parser (where they're available as `args.mac` etc.) — argparse
    # allows parent-parser flags to appear before or after the
    # subcommand position, so users can write either order.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--mac", help="Target device MAC (default: first discovered).")
    shared.add_argument("--timeout", type=float, default=10.0,
                        help="BLE scan timeout in seconds (default: 10).")
    shared.add_argument("--type", dest="device_type",
                        help="Explicit device_type (overrides registry).")
    shared.add_argument("--json", action="store_true",
                        help="Output JSON instead of human-readable text.")
    shared.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging.")

    p = argparse.ArgumentParser(
        prog="divoom-control",
        description="Command-line interface for the divoom_lib.",
        parents=[shared],
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", parents=[shared], help="Scan for nearby Divoom devices.")
    sub.add_parser("capabilities", parents=[shared], help="Print the active device's capabilities.")
    sub.add_parser("identify", parents=[shared], help="Print raw BLE manufacturer_data for a new device, for fingerprinting.")

    # SETTERS (require a value)
    p_vol = sub.add_parser("set-volume", parents=[shared], help="Set volume (0-15).")
    p_vol.add_argument("value", type=int)

    p_bri = sub.add_parser("set-brightness", parents=[shared], help="Set brightness (0-100).")
    p_bri.add_argument("value", type=int)

    p_fm = sub.add_parser("set-radio", parents=[shared], help="Set FM frequency (MHz × 10, e.g. 875 = 87.5).")
    p_fm.add_argument("freq_x10", type=int)

    p_al = sub.add_parser("set-alarm", parents=[shared], help="Set a one-shot alarm at HH:MM.")
    p_al.add_argument("time", help="HH:MM (24h)")

    p_wx = sub.add_parser("set-temperature", parents=[shared], help="Set the device's weather channel (temperature + icon).")
    p_wx.add_argument("temperature", type=int, help="Temperature in Celsius (range: -127..128).")
    p_wx.add_argument(
        "--weather", default="clear", choices=["clear", "cloudy", "thunderstorm", "rain", "snow", "fog"],
        help="Weather condition (default: clear).",
    )

    p_img = sub.add_parser("push-image", parents=[shared], help="Push a local image to the device.")
    p_img.add_argument("path", type=Path)

    p_gif = sub.add_parser("push-gif", parents=[shared], help="Push a local animated GIF.")
    p_gif.add_argument("path", type=Path)

    # REGISTRY — pair reuses the shared --mac and --type, both required
    # at the handler level (see cmd_pair). Defining them again here would
    # conflict with the inherited definitions.
    sub.add_parser("pair", parents=[shared], help="Pair a MAC address with a device type (saves to registry).")

    # MCP server (R15 §5; R28 routes through the daemon): stdio JSON-RPC
    # server. It does NOT open its own BLE connection — the daemon is the
    # sole device owner, so the MCP server is a thin daemon client and
    # exposes 12 tools to MCP-compatible clients (Claude Desktop, Cursor,
    # Cline, Continue, etc.).
    p_mcp = sub.add_parser(
        "mcp-server", parents=[shared],
        help="Start the MCP stdio JSON-RPC server (routes through the daemon).",
    )
    p_mcp.add_argument("--socket", default="/tmp/divoom.sock",
                       help="Daemon Unix socket to connect to (auto-spawns a "
                            "local daemon if none is running).")
    p_mcp.add_argument("--host", default=None,
                       help="Connect to a remote daemon on this TCP host "
                            "instead of the local socket (sets DIVOOM_DAEMON_HOST).")
    p_mcp.add_argument("--port", type=int, default=9009,
                       help="TCP port of the remote daemon (default 9009).")
    p_mcp.add_argument("--token", default=None,
                       help="Shared secret for a remote (TCP) daemon "
                            "(falls back to DIVOOM_DAEMON_TOKEN).")

    # Headless daemon (R16): owns the device + macOS notification routing and
    # serves status/notification events over a Unix socket. The GUI and menubar
    # are thin clients of it.
    p_daemon = sub.add_parser(
        "daemon", parents=[shared],
        help="Run the headless daemon (device + macOS notification routing + event socket).",
    )
    p_daemon.add_argument("--socket", default="/tmp/divoom.sock", help="Unix socket path.")
    p_daemon.add_argument("--host", default=None,
                          help="Also listen on this TCP host (e.g. 0.0.0.0 for LAN). "
                               "Requires --token or DIVOOM_DAEMON_TOKEN.")
    p_daemon.add_argument("--port", type=int, default=9009,
                          help="TCP port for the network listener (default 9009).")
    p_daemon.add_argument("--token", default=None,
                          help="Shared secret required for TCP clients "
                               "(falls back to DIVOOM_DAEMON_TOKEN).")

    # macOS menubar agent (R15 §6): native Cocoa status item that
    # connects to the daemon as a client. No BLE, no socket server.
    sub.add_parser(
        "menubar", parents=[shared],
        help="Launch the macOS menubar agent (connects to daemon).",
    )
    return p


# ── Helpers ───────────────────────────────────────────────────────────


from divoom_lib.cli_commands import (
    _print,
    _err,
    _resolve_device,
    cmd_scan,
    cmd_capabilities,
    cmd_set_volume,
    cmd_set_brightness,
    cmd_set_radio,
    cmd_set_alarm,
    cmd_set_temperature,
    cmd_push_image,
    cmd_push_gif,
    cmd_pair,
    cmd_identify,
    cmd_mcp_server,
    cmd_daemon,
    cmd_menubar,
)


# ── Dispatcher ────────────────────────────────────────────────────────


COMMANDS: dict[str, Callable[[argparse.Namespace], Awaitable[int]]] = {
    "scan":          cmd_scan,
    "capabilities":  cmd_capabilities,
    "set-volume":    cmd_set_volume,
    "set-brightness":cmd_set_brightness,
    "set-radio":     cmd_set_radio,
    "set-alarm":     cmd_set_alarm,
    "set-temperature": cmd_set_temperature,
    "push-image":    cmd_push_image,
    "push-gif":      cmd_push_gif,
    "pair":          cmd_pair,
    "identify":      cmd_identify,
    "mcp-server":    cmd_mcp_server,
    "daemon":        cmd_daemon,
    "menubar":       cmd_menubar,
}


async def amain(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    handler = COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    import inspect
    if inspect.iscoroutinefunction(handler):
        return await handler(args)
    else:
        return handler(args)


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
