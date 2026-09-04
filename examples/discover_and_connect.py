#!/usr/bin/env python3
"""
Discover and connect to a Divoom device, then print its capabilities.

This is the smallest working example — no device-specific configuration
required. It scans for any nearby Divoom device (matched by BLE name
prefix), connects, prints capabilities, and disconnects.

Usage:
    python -m examples.discover_and_connect
    python -m examples.discover_and_connect --timeout 20
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_all_divoom_devices


async def main(timeout: float = 10.0) -> int:
    print(f"Scanning for Divoom devices (timeout={timeout}s)…", file=sys.stderr)
    devices = await discover_all_divoom_devices(timeout=timeout)
    if not devices:
        print("No Divoom devices found.", file=sys.stderr)
        return 1
    for d in devices:
        print(f"  {d['address']}  {d['name']}")
    target = devices[0]
    print(f"Connecting to {target['name']} ({target['address']})…", file=sys.stderr)
    divoom = Divoom(mac=target["address"], device_name=target["name"])
    await divoom.connect()
    try:
        caps = divoom.capabilities
        print("Capabilities:")
        print(f"  panel_resolution: {caps.panel_resolution}×{caps.panel_resolution}")
        print(f"  has_fm:           {caps.has_fm}")
        print(f"  has_sd:           {caps.has_sd}")
        print(f"  has_scoreboard:   {caps.has_scoreboard}")
        print(f"  has_alarm:        {caps.has_alarm}")
        print(f"  has_sleep:        {caps.has_sleep}")
        print(f"  has_weather:      {caps.has_weather}")
        print(f"  has_mic:          {caps.has_mic}")
    finally:
        await divoom.disconnect()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeout", type=float, default=10.0)
    ns = p.parse_args()
    sys.exit(asyncio.run(main(timeout=ns.timeout)))
