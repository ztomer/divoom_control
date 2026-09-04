#!/usr/bin/env python3
"""Smoke-test 0x8b animation push on live hardware.

Tests TERMINATE removal (R35): runs once per device and reports PASS.
"""

import sys
import os
import asyncio
import tempfile
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from divoom_lib import Divoom


def make_test_gif() -> str:
    img = Image.new("RGB", (16, 16), (0, 120, 255))
    for y in range(4, 12):
        for x in range(4, 12):
            img.putpixel((x, y), (255, 60, 60))
    path = os.path.join(tempfile.gettempdir(), "divoom_test_16x16.gif")
    img.save(path)
    return path


async def test_device(address: str, name: str):
    print(f"  [{name}] ...", end=" ", flush=True)
    try:
        divoom = Divoom(mac=address, device_name=name)
        await divoom.connect()
        result = await divoom.display.show_image(make_test_gif(), time=1)
        await divoom.disconnect()
        print("PASS" if result else "FAIL")
        return result
    except Exception as e:
        print(f"FAIL ({e})")
        return False



# Manual hardware harness — run directly:
#   python3 tests/test_hardware_smoke.py
# Not a pytest test (the function takes real device args, not fixtures);
# without this marker pytest collects it and errors on missing fixtures.
test_device.__test__ = False

async def main():
    from divoom_lib.utils.discovery import discover_all_divoom_devices
    devices = await discover_all_divoom_devices(timeout=8)
    if not devices:
        print("FAIL: no Divoom devices found")
        sys.exit(1)

    print(f"\nSmoke-testing {len(devices)} device(s)")
    print("=" * 40)
    all_ok = True
    for d in devices:
        print(f"  Device: {d['name']}  ({d['address']})")
        ok = await test_device(d["address"], d["name"])
        if not ok:
            all_ok = False
        await asyncio.sleep(3)

    print(f"\n{'='*40}")
    print(f"Overall: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
