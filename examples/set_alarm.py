#!/usr/bin/env python3
"""
Set alarm 0 on the connected Divoom device to a given time, every day.

This is the scriptable counterpart to the GUI's Alarms editor. It uses
``set_alarm(alarm_index=0, status=1, hour, minute, week=127)`` to set a
single alarm that fires every day of the week.

A richer example with per-day selection and custom sounds is in the
GUI's Routines card.

Usage:
    python -m examples.set_alarm 07:30
    python -m examples.set_alarm 07:30 --mac AA:BB:CC:DD:EE:FF
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

from divoom_lib import Divoom


async def main(time_str: str, mac: str | None, timeout: float) -> int:
    if not re.fullmatch(r"\d{1,2}:\d{2}", time_str):
        print(f"invalid time: {time_str!r} (expected HH:MM)", file=sys.stderr)
        return 2
    hh, mm = (int(x) for x in time_str.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        print(f"out of range: {time_str!r}", file=sys.stderr)
        return 2
    if mac is None:
        from divoom_lib.utils.discovery import discover_all_divoom_devices
        devices = await discover_all_divoom_devices(timeout=timeout)
        if not devices:
            print("No Divoom devices found.", file=sys.stderr)
            return 1
        mac = devices[0]["address"]
        name = devices[0]["name"]
    else:
        name = mac
    divoom = Divoom(mac=mac, device_name=name)
    await divoom.connect()
    try:
        if not divoom.capabilities.has_alarm:
            print(f"device {mac} has no alarm (capabilities.has_alarm=False)", file=sys.stderr)
            return 1
        # week=127 = all 7 days; mode=0/trigger_mode=0/fm_freq=0/volume=0 use defaults.
        ok = await divoom.alarm.set_alarm(0, 1, hh, mm, 127, 0, 0)
        print(f"set alarm 0 to {hh:02d}:{mm:02d} every day on {mac} (ok={ok})")
        return 0 if ok else 1
    finally:
        await divoom.disconnect()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("time", help="Alarm time in HH:MM (24h).")
    p.add_argument("--mac", help="Target device MAC (default: first discovered).")
    p.add_argument("--timeout", type=float, default=10.0)
    ns = p.parse_args()
    sys.exit(asyncio.run(main(time_str=ns.time, mac=ns.mac, timeout=ns.timeout)))
