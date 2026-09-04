#!/usr/bin/env python3
"""
Watch the BLE radio and auto-connect to a known device.

Useful as a `launchd` agent on macOS: when a paired Divoom device
appears in range, this script connects to it, optionally runs a
callback, then disconnects. Designed to be a no-op when the device is
out of range so it can run as a long-lived loop.

Usage:
    python -m examples.auto_connect                  # first discovered, no callback
    python -m examples.auto_connect --mac AA:BB:...  # only this MAC
    python -m examples.auto_connect --once           # exit after first connect

Combine with `divoom-control pair --mac ... --type ...` to register a
device before running this script — the lib will then know its
capabilities.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from bleak import BleakScanner

from divoom_lib import Divoom


async def main(mac: str | None, timeout: float, once: bool, on_connect: bool) -> int:
    seen: set[str] = set()
    print(f"watching for Divoom devices (timeout={timeout}s per scan)…", file=sys.stderr)
    while True:
        devices = await BleakScanner.discover(timeout=timeout)
        for d in devices:
            if not d.name:
                continue
            if not any(kw in d.name.lower() for kw in ("timoo", "tivoo", "timebox", "pixoo", "ditoo")):
                continue
            if mac is not None and d.address.lower() != mac.lower():
                continue
            if d.address in seen:
                continue
            seen.add(d.address)
            print(f"discovered {d.name} ({d.address})", file=sys.stderr)
            divoom = Divoom(mac=d.address, device_name=d.name)
            try:
                await divoom.connect()
                if on_connect:
                    print(f"connected to {d.address} — capabilities: panel={divoom.capabilities.panel_resolution}")
                if once:
                    return 0
            finally:
                try:
                    await divoom.disconnect()
                except Exception:
                    pass
        if once:
            return 0
        await asyncio.sleep(2.0)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mac", help="Only watch this MAC (default: any Divoom).")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--once", action="store_true", help="Exit after first connect.")
    p.add_argument("--quiet", action="store_true", help="Don't print on connect.")
    ns = p.parse_args()
    try:
        sys.exit(asyncio.run(main(
            mac=ns.mac, timeout=ns.timeout, once=ns.once, on_connect=not ns.quiet,
        )))
    except KeyboardInterrupt:
        sys.exit(0)
