"""The CLI's DEVICE verbs: everything that acts on a panel.

Split out of `cli_commands.py` on 2026-09-25 by the 500-line cap, at the seam
the migration itself created. Four of these verbs (`set-volume`,
`set-brightness`, `push-image`, `push-gif`) are now `divoomd` subcommands and
what is left here is the CLIENT POLICY around them: validate before touching
the radio, decide which panel this is, and hand over. The other three
(`set-radio`, `set-alarm`, `set-temperature`) still issue their device call
from Python, because the capability table that refuses them on a panel without
the feature exists only in Python.

WHAT A PANEL IS (P3.4): the capability table that used to live here is gone.
"The daemon knows what each panel is" -- its model, its size, its chassis, the
features the vendor app enables for its model and the screens the app offers
it -- so the CLI asks the daemon (`device_status`) instead of carrying a
second table of per-model facts. The two gates that table fed could not fire
(`has_alarm` and `has_weather` were true of every row), and the third -- the
FM radio -- is enforced by the DAEMON, which is the one place that knows the
panel has no radio.

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
    """What this panel IS, as the daemon says (P3.4).

    The daemon's own description: the model and how it was decided, the size,
    the chassis, the features the vendor app enables for that model, and the
    screens the app offers it. The CLI used to print a table of its own --
    which is where the "a Ditoo has an FM radio" story came from.
    """
    client = cli_commands._daemon_client(args)
    mac = await resolve_target_mac(args)
    status = client.device_status(mac=mac) or {}
    features = status.get("features") or {}
    chassis = status.get("chassis") or {}
    screens = status.get("screens")
    if args.json:
        cli_commands._print({
            "mac": mac,
            "model": status.get("model"),
            "model_source": status.get("model_source"),
            "width": status.get("width"),
            "height": status.get("height"),
            "chassis": chassis or None,
            "features": features or None,
            "screens": screens,
        }, as_json=True)
    else:
        print(f"Device: {mac}")
        print(f"  model:           {status.get('model') or 'unknown'} "
              f"({status.get('model_source') or 'no name'})")
        width = status.get("width")
        print(f"  size:            {f'{width}x{width}' if width else 'unknown'}")
        if chassis:
            print(f"  chassis:         {chassis.get('family')} "
                  f"({chassis.get('w_mm')}x{chassis.get('h_mm')} mm)")
        if features:
            for key in sorted(features):
                if key in ("source", "clock_style"):
                    continue
                print(f"  {key + ':':<17}{features[key]}")
            print(f"  clock_style:     {features.get('clock_style')}")
        else:
            print("  features:        the daemon does not know this panel yet")
        if screens is not None:
            print(f"  screens:         {', '.join(screens)}")
        else:
            print("  screens:         the daemon does not know this panel yet")
    return 0


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
    """Tune the FM radio.

    The band is checked in `divoomd`, and so is the CAPABILITY: the daemon
    knows which panels have a radio (the vendor app offers the FM screen to
    the Timebox and the Tiivoo 2, and to no other panel), so the daemon is
    where the refusal happens. The CLI used to carry a table of its own for
    this, and it said the opposite of the app.
    """
    mac = await resolve_target_mac(args)
    _delegate_device_verb("set-radio", [str(args.freq_x10)], mac, args)


async def cmd_set_alarm(args: argparse.Namespace) -> int:
    """Set alarm 0 to HH:MM on every day.

    Note: a full alarm editor is the GUI's job; this is the scriptable path.
    The time is still validated here, before a panel is resolved, so a typo is
    reported without reaching for the radio — `divoomd` validates it again for
    anyone calling the verb directly.
    """
    try:
        hh, mm = args.time.split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        cli_commands._err("time must be HH:MM (24h)", 2)
    mac = await resolve_target_mac(args)
    # BEHAVIOUR CHANGE: this used to send trigger_mode=0, which the reference
    # implementation never documents — it defines the field as
    # ALARM_TRIGGER_MUSIC=1 / ALARM_TRIGGER_GIF=4, and its own usage example
    # passes 1. `divoomd set-alarm` sends the documented 1, matching the MCP
    # tool. The byte on the wire changes; see the CHANGELOG stanza.
    _delegate_device_verb("set-alarm", [args.time], mac, args)


# R14 §1 — weather command (0x5F). The name->id table used to live here; it is
# `WEATHER_TYPES` in divoomd/src/mcp_tools.rs now, and `divoomd set-temperature`
# owns the mapping. Kept as a reference for the wire values, NOT used: a second
# copy is what tools/check_weather_parity.py exists to prevent.
WEATHER_NAME_TO_ID_REFERENCE = {
    "clear":        1,
    "cloudy":       3,
    "thunderstorm": 5,
    "rain":         6,
    "snow":         8,
    "fog":          9,
}


async def cmd_set_temperature(args: argparse.Namespace) -> int:
    """Set the device's weather channel: temperature + icon (0x5F)."""
    # Validated BEFORE resolving a panel (mirrors set-volume): an out-of-range
    # temperature otherwise opened the link, then died with a raw ValueError
    # traceback from Weather.set instead of a clean usage error. The icon NAME
    # is checked in divoomd, which owns the name->wire-value table now.
    if not (-127 <= args.temperature <= 128):
        cli_commands._err("temperature must be -127..128", 2)
    mac = await resolve_target_mac(args)
    _delegate_device_verb("set-temperature", [str(args.temperature), args.weather], mac, args)


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


