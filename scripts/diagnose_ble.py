#!/usr/bin/env python3
"""Diagnose macOS BLE scanning end-to-end. RUN FROM YOUR (granted) TERMINAL:

    python3 scripts/diagnose_ble.py

It prints, in one pass:
  1. which python is running (TCC attributes Bluetooth per binary/responsible app)
  2. the CoreBluetooth authorization state
  3. a RAW scan of ALL nearby BLE devices (unfiltered)
  4. the Divoom-name-filtered scan the app actually uses

Comparing 3 vs 4 tells us instantly:
  - raw finds your screens but filtered doesn't -> the NAME FILTER is dropping them
    (your model isn't in the keyword list) — paste the names and we widen it.
  - raw finds nothing -> permission/hardware (screens not advertising, or denied).
  - authorization != 3 -> it's a permission grant problem.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

print("=" * 60)
print("python      :", sys.executable)

try:
    from CoreBluetooth import CBCentralManager
    auth = CBCentralManager.authorization()
    names = {0: "notDetermined", 1: "restricted", 2: "DENIED", 3: "ALLOWED"}
    print("CB auth     :", auth, f"({names.get(auth, '?')})")
except Exception as e:  # pragma: no cover
    print("CB auth     : <error reading>", e)

print("=" * 60)


async def main() -> None:
    from bleak import BleakScanner

    print("RAW scan (all BLE, 8s) — this is what your screens must show up in:")
    raw = await BleakScanner.discover(timeout=8.0)
    print(f"  -> {len(raw)} device(s):")
    for d in raw:
        rssi = getattr(d, "rssi", None)
        print(f"     {d.address}  rssi={rssi}  name={d.name!r}")

    print("-" * 60)
    print("Divoom-filtered scan (what the app's Scan button uses):")
    try:
        from divoom_lib.utils import discovery
        divs = await discovery.discover_all_divoom_devices(timeout=8.0)
        print(f"  -> {len(divs)}: {divs}")
    except Exception as e:
        print("  filtered scan error:", repr(e))

    print("=" * 60)
    print("If RAW shows your screens but Divoom-filtered is empty, paste the")
    print("RAW names above — the keyword filter is dropping your model.")


if __name__ == "__main__":
    asyncio.run(main())
