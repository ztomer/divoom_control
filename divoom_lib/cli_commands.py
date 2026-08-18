"""divoom-control CLI command handlers (split from cli.py, REVIEW §1).

The argument parser + dispatcher live in cli.py; this module holds the per-command
coroutines and their helpers. Imported back into cli.py to build COMMANDS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from divoom_lib import Divoom
from divoom_lib.models.capabilities import (
    DEVICE_CAPABILITIES,
    DeviceRegistry,
)


def _print(data: Any, *, as_json: bool = False) -> None:
    if as_json:
        if isinstance(data, (list, dict)):
            print(json.dumps(data, indent=2, default=str))
        else:
            print(json.dumps({"result": str(data)}, indent=2))
    else:
        if isinstance(data, list):
            for item in data:
                print(item)
        elif isinstance(data, dict):
            for k, v in data.items():
                print(f"{k}: {v}")
        else:
            print(data)


def _err(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


async def _resolve_device(args: argparse.Namespace) -> tuple[Divoom, str]:
    """Connect to the requested device and return (Divoom instance, MAC)."""
    if args.command == "pair" or args.command == "identify":
        # These commands don't need a connected device.
        return None, (args.mac or "")
    mac = args.mac
    device_name = None
    if not mac:
        # Auto-discover the first Divoom device.
        from bleak import BleakScanner
        from divoom_lib.utils.discovery import discover_all_divoom_devices
        results = await discover_all_divoom_devices(timeout=args.timeout)
        if not results:
            _err("no Divoom devices found", 1)
        mac = results[0]["address"]
        device_name = results[0].get("name")

    kwargs: dict = {"mac": mac, "device_type": args.device_type}
    # Try to pass the manufacturer_data from the scan if we have it.
    if device_name:
        kwargs["device_name"] = device_name
    divoom = Divoom(**kwargs)
    await divoom.connect()
    return divoom, mac


# ── Commands ──────────────────────────────────────────────────────────


async def cmd_scan(args: argparse.Namespace) -> int:
    from divoom_lib.utils.discovery import discover_all_divoom_devices
    results = await discover_all_divoom_devices(timeout=args.timeout)
    if args.json:
        _print(results, as_json=True)
    else:
        if not results:
            print("(no Divoom devices found)")
        for r in results:
            print(f"{r['address']}  {r['name']}")
    return 0


async def cmd_capabilities(args: argparse.Namespace) -> int:
    d, mac = await _resolve_device(args)
    try:
        caps = d.capabilities
        if args.json:
            _print({
                "mac": mac,
                "panel_resolution": caps.panel_resolution,
                "has_fm": caps.has_fm,
                "has_sd": caps.has_sd,
                "has_scoreboard": caps.has_scoreboard,
                "has_anim_8b": caps.has_anim_8b,
                "has_orientation": caps.has_orientation,
                "has_screen_mirror": caps.has_screen_mirror,
                "has_alarm": caps.has_alarm,
                "has_sleep": caps.has_sleep,
                "has_weather": caps.has_weather,
                "has_mic": caps.has_mic,
                "notes": list(caps.notes),
            }, as_json=True)
        else:
            print(f"Device: {mac}")
            print(f"  panel_resolution: {caps.panel_resolution}×{caps.panel_resolution}")
            print(f"  has_fm:           {caps.has_fm}")
            print(f"  has_sd:           {caps.has_sd}")
            print(f"  has_scoreboard:   {caps.has_scoreboard}")
            print(f"  has_anim_8b:      {caps.has_anim_8b}")
            print(f"  has_orientation:  {caps.has_orientation}")
            print(f"  has_screen_mirror:{caps.has_screen_mirror}")
            print(f"  has_alarm:        {caps.has_alarm}")
            print(f"  has_sleep:        {caps.has_sleep}")
            print(f"  has_weather:      {caps.has_weather}")
            print(f"  has_mic:          {caps.has_mic}")
            if caps.notes:
                print(f"  notes: {'; '.join(caps.notes)}")
        return 0
    finally:
        if d is not None:
            await d.disconnect()


async def cmd_set_volume(args: argparse.Namespace) -> int:
    if not (0 <= args.value <= 15):
        _err("volume must be 0..15", 2)
    d, mac = await _resolve_device(args)
    try:
        ok = await d.music.set_volume(args.value)
        _print(f"set volume to {args.value}/15 (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        await d.disconnect()


async def cmd_set_brightness(args: argparse.Namespace) -> int:
    if not (0 <= args.value <= 100):
        _err("brightness must be 0..100", 2)
    d, mac = await _resolve_device(args)
    try:
        ok = await d.device.set_brightness(args.value)
        _print(f"set brightness to {args.value}% (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        await d.disconnect()


async def cmd_set_radio(args: argparse.Namespace) -> int:
    d, mac = await _resolve_device(args)
    try:
        if not d.capabilities.has_fm:
            _err(f"device {mac} has no FM radio (capabilities.has_fm=False)", 1)
        ok = await d.radio.set_radio_frequency(args.freq_x10)
        mhz = args.freq_x10 / 10.0
        _print(f"tuned FM to {mhz:.1f} MHz (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        await d.disconnect()


async def cmd_set_alarm(args: argparse.Namespace) -> int:
    """Set alarm 0 to HH:MM on every day (127 = all days).
    Note: a full alarm editor is the GUI's job; this is the scriptable path."""
    try:
        hh, mm = args.time.split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        _err("time must be HH:MM (24h)", 2)
    d, mac = await _resolve_device(args)
    try:
        if not d.capabilities.has_alarm:
            _err(f"device {mac} has no alarm (capabilities.has_alarm=False)", 1)
        # Signature: set_alarm(alarm_index, status, hour, minute, week, mode, trigger_mode, fm_freq, volume)
        # week=127 = all days, mode=0=default, trigger_mode=0=default, fm_freq=0=off, volume=0=default
        ok = await d.alarm.set_alarm(0, 1, hh, mm, 127, 0, 0)
        _print(f"set alarm 0 to {hh:02d}:{mm:02d} every day (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        await d.disconnect()


# R14 §1 — weather command (0x5F).
WEATHER_NAME_TO_ID = {
    "clear":        1,
    "cloudy":       3,
    "thunderstorm": 5,
    "rain":         6,
    "snow":         8,
    "fog":          9,
}


async def cmd_set_temperature(args: argparse.Namespace) -> int:
    """Set the device's weather channel: temperature + icon (0x5F)."""
    # Validate BEFORE connecting (mirrors set-volume / set-brightness): an
    # out-of-range temp otherwise opened the BLE link, then died with a raw
    # ValueError traceback from Weather.set instead of a clean usage error.
    if not (-127 <= args.temperature <= 128):
        _err("temperature must be -127..128", 2)
    d, mac = await _resolve_device(args)
    try:
        if not d.capabilities.has_weather:
            _err(f"device {mac} has no weather channel (capabilities.has_weather=False)", 1)
        weather_id = WEATHER_NAME_TO_ID[args.weather]
        ok = await d.weather.set(args.temperature, weather_id)
        _print(
            f"set weather: temperature={args.temperature}°C, weather={args.weather} ({weather_id}) (ok={ok})",
            as_json=args.json,
        )
        return 0 if ok else 1
    finally:
        await d.disconnect()


async def cmd_push_image(args: argparse.Namespace) -> int:
    path: Path = args.path
    if not path.exists():
        _err(f"file not found: {path}", 2)
    d, mac = await _resolve_device(args)
    try:
        ok = await d.display.show_image(str(path))
        _print(f"pushed {path.name} to {mac} (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        await d.disconnect()


async def cmd_push_gif(args: argparse.Namespace) -> int:
    path: Path = args.path
    if not path.exists():
        _err(f"file not found: {path}", 2)
    d, mac = await _resolve_device(args)
    try:
        ok = await d.display.show_image(str(path))
        _print(f"pushed animated {path.name} to {mac} (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        await d.disconnect()


async def cmd_pair(args: argparse.Namespace) -> int:
    """Save MAC → device_type to the per-install registry."""
    if not args.mac:
        _err("--mac is required for `pair`", 2)
    if not args.device_type:
        _err("--type is required for `pair`", 2)
    if args.device_type not in DEVICE_CAPABILITIES:
        _err(f"unknown device_type {args.device_type!r}; "
             f"valid: {sorted(DEVICE_CAPABILITIES.keys())}", 2)
    reg = DeviceRegistry()
    reg.register(args.mac, args.device_type)
    if args.json:
        _print({"registered": args.mac, "device_type": args.device_type}, as_json=True)
    else:
        print(f"registered {args.mac} → {args.device_type}")
        print(f"registry file: {reg.path}")
    return 0


async def cmd_identify(args: argparse.Namespace) -> int:
    """Print the raw BLE manufacturer_data for a device. Used to populate
    the ADVERTISED_FINGERPRINTS table as the user identifies new devices."""
    from bleak import BleakScanner
    timeout = args.timeout
    print(f"Scanning for {timeout}s...", file=sys.stderr)
    # Use the callback API so we get the full AdvertisementData.
    found = {}
    def cb(device, adv):
        if adv.manufacturer_data:
            found[device.address] = (device.name, adv.manufacturer_data, adv.service_uuids)
    scanner = BleakScanner(detection_callback=cb)
    await scanner.start()
    import asyncio as _aio
    await _aio.sleep(timeout)
    await scanner.stop()

    if not found:
        _err("no devices with manufacturer_data found", 1)

    if args.json:
        out = {
            addr: {"name": name, "manufacturer_data": {hex(k): v.hex() for k, v in md.items()}, "service_uuids": list(uuids)}
            for addr, (name, md, uuids) in found.items()
        }
        _print(out, as_json=True)
    else:
        for addr, (name, md, uuids) in found.items():
            print(f"\n{addr}  {name}")
            for company_id, payload in md.items():
                print(f"  manufacturer_data: company_id=0x{company_id:04x} bytes={payload.hex()}")
            if uuids:
                print(f"  service_uuids:     {list(uuids)}")
        print("\nTo register a fingerprint, add to ADVERTISED_FINGERPRINTS in", file=sys.stderr)
        print("divoom_lib/models/capabilities.py and re-run identify.", file=sys.stderr)
    return 0


async def cmd_mcp_server(args: argparse.Namespace) -> int:
    """Start the MCP stdio JSON-RPC server (R15 §5; R28 routes through the daemon).

    The MCP server does NOT open its own BLE connection — the daemon is the sole
    device owner (R17), so this builds the tool catalog against a
    ``DaemonDeviceProxy`` that routes every tool call through the daemon's
    ``device_call`` RPC. It connects to the local daemon socket (auto-spawning
    one if needed), or to a remote daemon over TCP when ``--host`` is given.

    Exits cleanly when the parent process closes stdin. The proxy is stateless,
    so there is nothing to disconnect on exit (the daemon keeps owning the
    device for the GUI/menubar)."""
    import os
    from divoom_client.daemon_protocol import ENV_HOST, ENV_PORT, ENV_TOKEN
    from divoom_client.daemon_client import ensure_daemon, DaemonDeviceProxy

    # A remote daemon is selected purely via env (DaemonClient.from_env /
    # ensure_daemon read these); mirror the CLI flags into the environment so a
    # single code path handles local + remote.
    host = getattr(args, "host", None)
    if host:
        os.environ[ENV_HOST] = host
        os.environ[ENV_PORT] = str(getattr(args, "port", 9009))
        token = getattr(args, "token", None) or os.environ.get(ENV_TOKEN)
        if token:
            os.environ[ENV_TOKEN] = token

    socket_path = getattr(args, "socket", None) or "/tmp/divoom.sock"
    client = ensure_daemon(socket_path, mac=getattr(args, "mac", None))
    if client is None:
        _err("could not reach or start the divoom daemon", 1)

    from divoom_lib.mcp_server import MCPServer
    from divoom_lib.mcp_tools import build_tool_catalog

    proxy = DaemonDeviceProxy(client)
    server = MCPServer(
        server_info={"name": "divoom-control", "version": "0.15.0"},
    )
    server.tools = build_tool_catalog(proxy)
    where = f"{host}:{getattr(args, 'port', 9009)}" if host else socket_path
    sys.stderr.write(
        f"MCP server starting: daemon={where}, tools={len(server.tools)}\n"
    )
    sys.stderr.flush()
    await server.run_stdio()
    return 0


async def cmd_daemon(args: argparse.Namespace) -> int:
    """The Python daemon server was archived 2026-07-13 (explicit user
    sign-off) in favor of the Rust `divoomd` binary — see `docs/ROADMAP.md`'s
    "Native Rust daemon" section. This subcommand is kept only to give a
    clear, actionable error instead of a raw ImportError; the historical
    implementation still exists (moved, not deleted) at
    git history if it's ever needed for reference (recover from git history (archived in 046cdf8, removed in R66 2026-08-17))."""
    print(
        "The Python daemon server has been archived — divoomd (Rust) is now "
        "the only supported daemon. Build/run divoomd directly, or use "
        "divoom_client.daemon_client.ensure_daemon()/spawn_daemon() which "
        "auto-spawns it. The archived Python implementation is kept for "
        "recoverable from git history but is no longer runnable via "
        "this CLI command.",
        file=sys.stderr,
    )
    return 1


def cmd_menubar(args: argparse.Namespace) -> int:
    """The pyobjc menubar was removed 2026-08-17 (R66) in favour of the native
    Rust agent, `divoom-menubar/`, which is what the shipped .app
    has bundled since the native cutover. This subcommand is kept only to give
    a clear, actionable error instead of a raw ImportError -- same treatment
    `cmd_daemon` got when the Python daemon server was archived."""
    print(
        "The Python menubar has been removed — the native Rust agent "
        "(divoom-menubar) is now the only menubar. Run it with "
        "`./run.sh --menubar`, or let the GUI spawn it (`./run.sh`). Build it "
        "with `./build.sh`. Its resubscribe guard lives in "
        "divoom-menubar/src/resubscribe.rs.",
        file=sys.stderr,
    )
    return 1


