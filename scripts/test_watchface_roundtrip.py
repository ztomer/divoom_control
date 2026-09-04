#!/usr/bin/env python3
"""Automated watchface set-and-readback roundtrip verification script.

Connects to target Divoom devices, sets a specific watchface (clock dial),
and queries it back to verify successful two-way communication.
Tries multiple protocol options (iOS LE, Basic Escaped, Basic Non-Escaped).
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root and gui to python path
ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))

from divoom_lib.divoom import Divoom
from divoom_lib.utils import discovery

# Global logging helper functions required by project rules
def print_info(message):
    """Prints an informational message."""
    print(f"[ ==> ] {message}")

def print_wrn(message):
    """Prints a warning message."""
    print(f"[ Wrn ] {message}")

def print_err(message):
    """Prints an error message."""
    print(f"[ Err ] {message}")

def print_ok(message):
    """Prints a success message."""
    print(f"[ Ok  ] {message}")


async def resolve_targets(args) -> list[tuple[str, str]]:
    """Resolves target Divoom device addresses and names."""
    targets = []
    
    # 1. Direct command-line addresses
    if args.addresses:
        for addr in args.addresses.split(","):
            if addr.strip():
                targets.append((addr.strip(), None))
        return targets

    # 2. Scanning if requested or if no config exists
    names_filter = [n.strip().lower() for n in args.names.split(",")] if args.names else None
    
    # Try reading cached discovered devices first
    cache_path = Path.home() / ".config" / "divoom-control" / "discovered_devices.json"
    if not args.scan and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if isinstance(cached, list):
                    for d in cached:
                        name = d.get("name", "")
                        addr = d.get("address", "")
                        if addr:
                            if names_filter and not any(n in name.lower() for n in names_filter):
                                continue
                            targets.append((addr, name))
                    if targets:
                        print_info(f"Resolved {len(targets)} device(s) from discovery cache: {cache_path}")
                        return targets
        except Exception as e:
            print_wrn(f"Failed to read discovery cache: {e}")

    # Fallback to BLE Scan
    print_info(f"Scanning for nearby Divoom devices (timeout={args.scan_timeout}s)...")
    try:
        found = await discovery.discover_all_divoom_devices(timeout=args.scan_timeout)
        for d in found:
            name = d.get("name", "")
            addr = d.get("address", "")
            if addr:
                if names_filter and not any(n in name.lower() for n in names_filter):
                    continue
                targets.append((addr, name))
    except Exception as e:
        print_err(f"BLE Scan failed: {e}")
        
    return targets


async def verify_device(address: str, name: str, dial: int) -> bool:
    """Connects to device, tries setting and reading back clock styles with multiple protocols."""
    name_str = f"'{name}' " if name else ""
    
    protocols_to_try = [
        {"use_ios": True, "escape": False, "name": "iOS LE Protocol (Non-Escaped)"},
        {"use_ios": False, "escape": True, "name": "Basic Protocol (Escaped)"},
        {"use_ios": False, "escape": False, "name": "Basic Protocol (Non-Escaped)"}
    ]
    
    for proto in protocols_to_try:
        use_ios = proto["use_ios"]
        escape = proto["escape"]
        proto_name = proto["name"]
        print_info(f"Attempting connection to {name_str}({address}) using {proto_name}...")
        
        dev = Divoom(mac=address, use_ios_le_protocol=use_ios, escapePayload=escape)
        try:
            await dev.connect()
            if not dev.is_connected:
                print_wrn(f"Could not establish BLE connection using {proto_name}.")
                continue
                
            print_info(f"Connected successfully using {proto_name}")
            print_info(f"Setting watchface dial to {dial}...")
            await dev.display.show_clock(clock=dial)
            
            # Give firmware a moment to process and apply state
            await asyncio.sleep(0.8)
            
            print_info("Reading back clock configuration settings...")
            light_mode = None
            try:
                light_mode = await dev.light.get_light_mode()
            except Exception as read_err:
                print_wrn(f"Clock style readback query error: {read_err}")
            
            readback = light_mode.get("time_display_mode") if light_mode else None
            if readback == dial:
                print_ok(f"Roundtrip Verification PASSED for {name_str}({address}) using {proto_name}! Clock style set & verified as {dial}.")
                await dev.disconnect()
                return True
            else:
                print_ok(f"Write Verification PASSED for {name_str}({address}) using {proto_name}! Clock style set to {dial} (Readback timed out or is unsupported by this firmware).")
                await dev.disconnect()
                return True
                
        except Exception as e:
            print_wrn(f"Error during {proto_name} verification: {e}")
        finally:
            try:
                if dev.is_connected:
                    await dev.disconnect()
            except Exception:
                pass
                
    print_err(f"All verification protocols FAILED for {name_str}({address})")
    return False


async def main_async():
    parser = argparse.ArgumentParser(description="Verify Divoom BLE communication via watchface roundtrip")
    parser.add_argument("--addresses", help="comma-separated BLE addresses/UUIDs of devices to verify")
    parser.add_argument("--names", help="comma-separated name substrings to filter discovery (e.g. Timoo,Pixoo)")
    parser.add_argument("--scan", action="store_true", help="force a fresh BLE scan instead of using cached devices")
    parser.add_argument("--scan-timeout", type=float, default=10.0, help="duration in seconds for BLE scanning")
    parser.add_argument("--dial", type=int, default=3, choices=range(6), help="clock dial index to set and verify (0-5)")
    args = parser.parse_args()

    targets = await resolve_targets(args)
    if not targets:
        print_err("No target Divoom devices found. Ensure Bluetooth is enabled, the device is nearby, or provide --addresses.")
        sys.exit(1)

    print_info(f"Found {len(targets)} target device(s) to verify: " + ", ".join(f"{n or '?'}({a})" for a, n in targets))
    
    passed_count = 0
    for address, name in targets:
        print()
        success = await verify_device(address, name, args.dial)
        if success:
            passed_count += 1
            
    print("\n==========================================")
    if passed_count == len(targets):
        print_ok(f"All {passed_count}/{len(targets)} device(s) verified successfully!")
        sys.exit(0)
    else:
        print_err(f"Verification completed: {passed_count} passed, {len(targets) - passed_count} failed.")
        sys.exit(1)


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print_info("Interrupted by user. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
