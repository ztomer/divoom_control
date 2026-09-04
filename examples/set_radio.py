#!/usr/bin/env python3
"""
Tune the device's FM radio to a specific frequency.

Only devices with FM hardware (Tivoo / Tivoo Max / Timoo / Ditoo) work.
Pixoo returns an error because it has no FM tuner. The capabilities
table flags this; we check it before issuing the command.

Usage:
    python -m examples.set_radio 87.5
    python -m examples.set_radio 87.5 --mac AA:BB:CC:DD:EE:FF
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from divoom_lib import Divoom


async def main(mhz: float, mac: str | None, timeout: float) -> int:
    freq_x10 = int(round(mhz * 10))
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
        if not divoom.capabilities.has_fm:
            print(f"device {mac} has no FM tuner (capabilities.has_fm=False)", file=sys.stderr)
            return 1
        ok = await divoom.radio.set_radio_frequency(freq_x10)
        print(f"tuned {mac} to {mhz:.1f} MHz (ok={ok})")
        return 0 if ok else 1
    finally:
        await divoom.disconnect()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("frequency", type=float, help="Frequency in MHz (e.g. 87.5)")
    p.add_argument("--mac", help="Target device MAC (default: first discovered).")
    p.add_argument("--timeout", type=float, default=10.0)
    ns = p.parse_args()
    sys.exit(asyncio.run(main(mhz=ns.frequency, mac=ns.mac, timeout=ns.timeout)))
