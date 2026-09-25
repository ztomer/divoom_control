"""The CLI's DEVICE verbs: everything that acts on a panel.

Split out of `cli_commands.py` on 2026-09-25 by the 500-line cap, at the seam
the migration itself created. Four of these verbs (`set-volume`,
`set-brightness`, `push-image`, `push-gif`) are now `divoomd` subcommands and
what is left here is the CLIENT POLICY around them: validate before touching
the radio, decide which panel this is, and hand over. The other three
(`set-radio`, `set-alarm`, `set-temperature`) still issue their device call
from Python, because the capability table that refuses them on a panel without
the feature exists only in Python.

The shared helpers — `_err`, `_daemon_client`, `_scan`, `_divoomd_binary` —
stay in `cli_commands`, and they are called as `cli_commands._err(...)` rather
than imported by name. That is deliberate and looks like noise: a
`from ... import _daemon_client` here would bind the function at import time, so
a test that patches `cli_commands._daemon_client` would silently keep patching a
name this module no longer uses, and every test of the device verbs would fail
against a real daemon instead of a fake. Module-qualified access keeps ONE
definition site and ONE patch point. Do not "tidy" these into from-imports.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from divoom_lib import cli_commands
from divoom_lib.models.capabilities import (
    Capabilities,
    DeviceRegistry,
    capabilities_for,
)

def _capabilities(args: argparse.Namespace, mac: str) -> Capabilities:
    """The capability table for this panel: explicit --type, else the MAC
    registry, else the baseline. Pure data -- no device I/O."""
    if getattr(args, "device_type", None):
        return capabilities_for(args.device_type)
    caps = DeviceRegistry().lookup(mac)
    return caps if caps is not None else capabilities_for(None)


async def resolve_target_mac(args: argparse.Namespace) -> str:
    """The panel this invocation is about, connected and ready.

    This is CLIENT POLICY, not a device command, and it is why it stays in
    Python after the verbs moved to `divoomd`: the daemon's own `resolve_target`
    refuses with a good message when several panels are linked, but it does not
    SCAN for a panel when none is linked and it does not CONNECT one that is
    known but down. Both are conveniences the CLI has always provided and both
    are what make `divoom-control set-volume 5` work on a cold machine.

    The verbs that moved hand the returned MAC to `divoomd`, which does the
    device call itself; the verbs still in Python wrap it in a proxy.
    """
    client = cli_commands._daemon_client(args)
    mac = args.mac
    if not mac:
        st = client.device_status()
        if st.get("mac"):
            mac = st["mac"]
        elif len(st.get("devices") or []) > 1:
            cli_commands._err("several panels are connected and none is the active one; pass --mac, "
                 "or `select --mac` one: " + ", ".join(d["mac"] for d in st["devices"]), 2)
        else:
            # Nothing linked: scan through the daemon and take the first.
            results = cli_commands._scan(client, args.timeout)
            if not results:
                cli_commands._err("no Divoom devices found", 1)
            mac = results[0]["address"]
    st = client.device_status(mac=mac)
    if not st.get("connected"):
        reply = client.connect_device(mac=mac, use_ios_le_protocol=True)
        if not reply.get("connected"):
            cli_commands._err(f"could not connect {mac}: {reply.get('error') or reply.get('message') or reply}", 1)
    return mac


async def _resolve_device(args: argparse.Namespace):
    """Return (device proxy, id) for a verb that still calls the daemon itself.

    `--mac` names the panel; without it, `resolve_target_mac` decides. Only the
    verbs whose CAPABILITY table is still Python need the proxy — the ones that
    moved to `divoomd` need the mac and nothing else.
    """
    if args.command == "pair" or args.command == "identify":
        # These commands don't need a connected device.
        return None, (args.mac or "")
    from divoom_client.daemon_proxy import DaemonDeviceProxy
    client = cli_commands._daemon_client(args)
    mac = await resolve_target_mac(args)
    return DaemonDeviceProxy(client, target="device", mac=mac), mac


def _delegate_device_verb(verb: str, values: list[str], mac: str, args) -> None:
    """Hand a device command to `divoomd <verb>` and let it become the process.

    `execv`, not spawn-and-wait, for the reason the MCP handoff has: the verb's
    output and exit code ARE its result, and a supervisor in between would be a
    place for both to be laundered. `--mac` is always passed, because
    `resolve_target_mac` has already decided which panel this is and the native
    verb must not re-decide.

    Does not return: on success the native verb is this process.
    """
    import os
    from divoom_client.daemon_protocol import ENV_SOCKET

    exe = cli_commands._divoomd_binary()
    argv = [str(exe), verb, *values]
    if mac:
        argv += ["--mac", mac]
    if getattr(args, "json", False):
        argv.append("--json")
    # The daemon the Python side just talked to has to be the daemon the native
    # verb talks to. `resolve_target_mac` may have been pointed at a dev daemon
    # with `--socket`, and without this the child would quietly use the default
    # path — on a user's machine, that is either a confusing "not reachable" or
    # the WRONG daemon. The env var is the same one the MCP handoff sets, and
    # the same one `DaemonTarget::from_env` reads.
    os.environ[ENV_SOCKET] = cli_commands._socket_path(args)
    sys.stderr.write(f"{verb}: handing off to {exe}\n")
    sys.stderr.flush()
    os.execv(str(exe), argv)


async def cmd_capabilities(args: argparse.Namespace) -> int:
    d, mac = await _resolve_device(args)
    try:
        caps = _capabilities(args, mac)
        if args.json:
            cli_commands._print({
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
    # Validated HERE as well as in `divoomd`, and the order matters: this check
    # runs before `resolve_target_mac`, so a typo cannot open a connection
    # before being told it was out of range. The native check is not redundant
    # — it is the one a direct `divoomd set-volume` gets.
    if not (0 <= args.value <= 15):
        cli_commands._err("volume must be 0..15", 2)
    _delegate_device_verb("set-volume", [str(args.value)], await resolve_target_mac(args), args)


async def cmd_set_brightness(args: argparse.Namespace) -> int:
    if not (0 <= args.value <= 100):
        cli_commands._err("brightness must be 0..100", 2)
    _delegate_device_verb("set-brightness", [str(args.value)], await resolve_target_mac(args), args)


async def cmd_set_radio(args: argparse.Namespace) -> int:
    d, mac = await _resolve_device(args)
    try:
        if not _capabilities(args, mac).has_fm:
            cli_commands._err(f"device {mac} has no FM radio (capabilities.has_fm=False)", 1)
        ok = await d.radio.set_radio_frequency(args.freq_x10)
        mhz = args.freq_x10 / 10.0
        cli_commands._print(f"tuned FM to {mhz:.1f} MHz (ok={ok})", as_json=args.json)
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
        cli_commands._err("time must be HH:MM (24h)", 2)
    d, mac = await _resolve_device(args)
    try:
        if not _capabilities(args, mac).has_alarm:
            cli_commands._err(f"device {mac} has no alarm (capabilities.has_alarm=False)", 1)
        # Signature: set_alarm(alarm_index, status, hour, minute, week, mode, trigger_mode, fm_freq, volume)
        # week=127 = all days, mode=0=default, trigger_mode=0=default, fm_freq=0=off, volume=0=default
        ok = await d.alarm.set_alarm(0, 1, hh, mm, 127, 0, 0)
        cli_commands._print(f"set alarm 0 to {hh:02d}:{mm:02d} every day (ok={ok})", as_json=args.json)
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
        cli_commands._err("temperature must be -127..128", 2)
    d, mac = await _resolve_device(args)
    try:
        if not _capabilities(args, mac).has_weather:
            cli_commands._err(f"device {mac} has no weather channel (capabilities.has_weather=False)", 1)
        weather_id = WEATHER_NAME_TO_ID[args.weather]
        ok = await d.weather.set(args.temperature, weather_id)
        cli_commands._print(
            f"set weather: temperature={args.temperature}°C, weather={args.weather} ({weather_id}) (ok={ok})",
            as_json=args.json,
        )
        return 0 if ok else 1
    finally:
        pass  # the daemon keeps the link; the CLI never hangs up a panel


async def cmd_push_image(args: argparse.Namespace) -> int:
    path: Path = args.path
    if not path.exists():
        cli_commands._err(f"file not found: {path}", 2)
    _delegate_device_verb("push-image", [str(path)], await resolve_target_mac(args), args)


async def cmd_push_gif(args: argparse.Namespace) -> int:
    # Not a special case, and never was: this pushed the file with the same
    # `show_image(path)` call `push-image` used. `divoomd push-gif` is kept
    # because scripts call it, and it sends the same path to the same daemon
    # method, which is what sizes to the panel.
    path: Path = args.path
    if not path.exists():
        cli_commands._err(f"file not found: {path}", 2)
    _delegate_device_verb("push-gif", [str(path)], await resolve_target_mac(args), args)


