#!/usr/bin/env python3
"""
Push an animated GIF to the connected Divoom device.

The GIF is decoded frame-by-frame, each frame is resized to the device's
panel_resolution and quantized to the Divoom palette, and the full
animation is sent via the 0x8B 3-phase protocol (256-byte chunks,
LSB-first pixel packing, chunk-index offset id). For static images see
push_static_image.py.

Usage:
    python -m examples.push_animated_gif path/to/animation.gif
    python -m examples.push_animated_gif path/to/animation.gif --mac AA:BB:CC:DD:EE:FF
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from divoom_lib import Divoom


async def main(path: Path, mac: str | None, timeout: float) -> int:
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
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
        ok = await divoom.display.show_image(str(path))
        print(f"pushed animated {path.name} → {mac} (ok={ok})")
        return 0 if ok else 1
    finally:
        await divoom.disconnect()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path)
    p.add_argument("--mac", help="Target device MAC (default: first discovered).")
    p.add_argument("--timeout", type=float, default=10.0)
    ns = p.parse_args()
    sys.exit(asyncio.run(main(path=ns.path, mac=ns.mac, timeout=ns.timeout)))
