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

from divoom_lib.models.capabilities import (
    Capabilities,
    DEVICE_CAPABILITIES,
    DeviceRegistry,
    capabilities_for,
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


def _daemon_client():
    """The running daemon, or a clear refusal.

    The CLI is a DAEMON CLIENT (2026-09-12, user correction): the daemon is the
    sole owner of device I/O, and the CLI used to be a second implementation
    over bleak. It does not spawn a daemon either -- a shell-spawned one has no
    Bluetooth grant and dies on its first scan with SIGABRT and no message --
    so with nothing running it says what to start.
    """
    from divoom_client.daemon_client import ensure_daemon
    client = ensure_daemon(spawn=False)
    if client is None:
        _err("no divoomd daemon is running. Start the Divoom app (it owns the "
             "Bluetooth grant) or the dev daemon bundle "
             "(scripts/make_dev_daemon_app.sh), then retry.", 3)
    return client


def _capabilities(args: argparse.Namespace, mac: str) -> Capabilities:
    """The capability table for this panel: explicit --type, else the MAC
    registry, else the baseline. Pure data -- no device I/O."""
    if getattr(args, "device_type", None):
        return capabilities_for(args.device_type)
    caps = DeviceRegistry().lookup(mac)
    return caps if caps is not None else capabilities_for(None)


async def _resolve_device(args: argparse.Namespace):
    """Return (device proxy, id). The proxy speaks to the daemon for ONE
    panel: `--mac` names it; without it, the daemon's own resolver answers
    for a single linked panel and refuses when several are linked.
    """
    if args.command == "pair" or args.command == "identify":
        # These commands don't need a connected device.
        return None, (args.mac or "")
    from divoom_client.daemon_proxy import DaemonDeviceProxy
    client = _daemon_client()
    mac = args.mac
    if not mac:
        st = client.device_status()
        if st.get("mac"):
            mac = st["mac"]
        elif len(st.get("devices") or []) > 1:
            _err("several panels are connected; pass --mac to say which: "
                 + ", ".join(d["mac"] for d in st["devices"]), 2)
        else:
            # Nothing linked: scan through the daemon and take the first.
            results = (client.scan(timeout=args.timeout) or {}).get("devices") or []
            if not results:
                _err("no Divoom devices found", 1)
            mac = results[0]["address"]
    st = client.device_status(mac=mac)
    if not st.get("connected"):
        reply = client.connect_device(mac=mac, use_ios_le_protocol=True)
        if not reply.get("connected"):
            _err(f"could not connect {mac}: {reply.get('error') or reply.get('message') or reply}", 1)
    return DaemonDeviceProxy(client, target="device", mac=mac), mac


# ── Commands ──────────────────────────────────────────────────────────


async def cmd_scan(args: argparse.Namespace) -> int:
    client = _daemon_client()
    results = (client.scan(timeout=args.timeout) or {}).get("devices") or []
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
        caps = _capabilities(args, mac)
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
        pass  # the daemon keeps the link; the CLI never hangs up a panel


async def cmd_set_volume(args: argparse.Namespace) -> int:
    if not (0 <= args.value <= 15):
        _err("volume must be 0..15", 2)
    d, mac = await _resolve_device(args)
    try:
        ok = await d.music.set_volume(args.value)
        _print(f"set volume to {args.value}/15 (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        pass  # the daemon keeps the link; the CLI never hangs up a panel


async def cmd_set_brightness(args: argparse.Namespace) -> int:
    if not (0 <= args.value <= 100):
        _err("brightness must be 0..100", 2)
    d, mac = await _resolve_device(args)
    try:
        ok = await d.device.set_brightness(args.value)
        _print(f"set brightness to {args.value}% (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        pass  # the daemon keeps the link; the CLI never hangs up a panel


async def cmd_set_radio(args: argparse.Namespace) -> int:
    d, mac = await _resolve_device(args)
    try:
        if not _capabilities(args, mac).has_fm:
            _err(f"device {mac} has no FM radio (capabilities.has_fm=False)", 1)
        ok = await d.radio.set_radio_frequency(args.freq_x10)
        mhz = args.freq_x10 / 10.0
        _print(f"tuned FM to {mhz:.1f} MHz (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        pass  # the daemon keeps the link; the CLI never hangs up a panel


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
        if not _capabilities(args, mac).has_alarm:
            _err(f"device {mac} has no alarm (capabilities.has_alarm=False)", 1)
        # Signature: set_alarm(alarm_index, status, hour, minute, week, mode, trigger_mode, fm_freq, volume)
        # week=127 = all days, mode=0=default, trigger_mode=0=default, fm_freq=0=off, volume=0=default
        ok = await d.alarm.set_alarm(0, 1, hh, mm, 127, 0, 0)
        _print(f"set alarm 0 to {hh:02d}:{mm:02d} every day (ok={ok})", as_json=args.json)
        return 0 if ok else 1
    finally:
        pass  # the daemon keeps the link; the CLI never hangs up a panel


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
        if not _capabilities(args, mac).has_weather:
            _err(f"device {mac} has no weather channel (capabilities.has_weather=False)", 1)
        weather_id = WEATHER_NAME_TO_ID[args.weather]
        ok = await d.weather.set(args.temperature, weather_id)
        _print(
            f"set weather: temperature={args.temperature}°C, weather={args.weather} ({weather_id}) (ok={ok})",
            as_json=args.json,
        )
        return 0 if ok else 1
    finally:
        pass  # the daemon keeps the link; the CLI never hangs up a panel


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
        pass  # the daemon keeps the link; the CLI never hangs up a panel


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
        pass  # the daemon keeps the link; the CLI never hangs up a panel


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
    """Print the raw BLE manufacturer_data for nearby devices. Used to
    populate the ADVERTISED_FINGERPRINTS table as the user identifies new
    devices. Read through the daemon's scan (it carries the advertisement's
    manufacturer data and service UUIDs); the radio has one owner."""
    client = _daemon_client()
    print(f"Scanning for {args.timeout}s...", file=sys.stderr)
    results = (client.scan(timeout=args.timeout) or {}).get("devices") or []
    found = {r["address"]: r for r in results if r.get("manufacturer_data")}
    if not found:
        _err("no devices with manufacturer_data found", 1)

    if args.json:
        out = {
            addr: {"name": r.get("name"), "manufacturer_data": {
                hex(int(k)): v for k, v in r["manufacturer_data"].items()},
                "service_uuids": list(r.get("service_uuids") or [])}
            for addr, r in found.items()
        }
        _print(out, as_json=True)
    else:
        for addr, r in found.items():
            print(f"\n{addr}  {r.get('name')}")
            for company_id, payload in r["manufacturer_data"].items():
                print(f"  manufacturer_data: company_id=0x{int(company_id):04x} bytes={payload}")
            for u in r.get("service_uuids") or []:
                print(f"  service_uuid: {u}")
        print("\nAdd a fingerprint to ADVERTISED_FINGERPRINTS in "
              "divoom_lib/models/capabilities.py as (company_id, prefix_bytes) -> device_type.")
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


