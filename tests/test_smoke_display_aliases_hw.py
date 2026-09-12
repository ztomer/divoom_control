#!/usr/bin/env python3
"""
Hardware smoke-test for display.show_clock / show_light / set_brightness
via the running daemon.

Moved from divoomd/smoke_display_aliases.py (Phase 1 of
docs/PLANNING_TEST_REORG.md): one place for tests to live. The original
ran everything at module import; here the flow lives in run_smoke() so
pytest collection is side-effect free.

Hardware-gated via tests/conftest.py HARDWARE_TEST_MODULES — skipped
without --run-hardware. Manual use unchanged:
python3 tests/test_smoke_display_aliases_hw.py [mac_address]
"""
import os
import sys, socket, json, time

SOCK = "/tmp/divoomd.sock"
TEST_MAC = os.environ.get("DIVOOM_TEST_MAC")


def call(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n")[0])


def check(label, resp, results):
    success = bool(resp.get("success") or resp.get("result"))
    print(f"[{'PASS' if success else 'FAIL'}] {label}: {resp}")
    results.append((label, success))
    return success


def run_smoke(mac=None):
    """Drive the alias flow; return [(label, passed)]. Raises on socket errors."""
    results = []

    # 1. Scan + connect
    print("-- scan --")
    print(call({"command": "scan", "args": {}}))
    time.sleep(2)

    if mac:
        print("-- connect --")
        r = call({"command": "connect", "args": {"mac": mac}})
        print(r)
        time.sleep(1)

    # 2. get current brightness
    print("-- get_brightness --")
    r = call({"command": "device_call", "args": {"method": "display.get_brightness", "args": {}}})
    check("display.get_brightness", r, results)
    time.sleep(0.5)

    # 3. set brightness 60
    print("-- set_brightness 60 --")
    r = call({"command": "device_call", "args": {"method": "display.set_brightness", "args": {"args": [60]}}})
    check("display.set_brightness(60)", r, results)
    time.sleep(1)

    # 4. show_clock face 0, 24h, with calendar
    print("-- show_clock --")
    r = call({"command": "device_call", "args": {
        "method": "display.show_clock",
        "args": {"kwargs": {"clock": 0, "twentyfour": True, "weather": False, "temp": False, "calendar": True, "color": "#FFFFFF"}}
    }})
    check("display.show_clock", r, results)
    time.sleep(3)

    # 5. show_light — red
    print("-- show_light red --")
    r = call({"command": "device_call", "args": {
        "method": "display.show_light",
        "args": {"kwargs": {"color": [255, 0, 0], "brightness": 80, "power": True}}
    }})
    check("display.show_light red", r, results)
    time.sleep(3)

    # 6. show_light — blue via hex
    print("-- show_light blue (#0000FF) --")
    r = call({"command": "device_call", "args": {
        "method": "display.show_light",
        "args": {"kwargs": {"color": "#0000FF", "brightness": 60, "power": True}}
    }})
    check("display.show_light blue", r, results)
    time.sleep(3)

    # 7. show_design — return to custom art channel
    print("-- show_design --")
    r = call({"command": "device_call", "args": {"method": "display.show_design", "args": {}}})
    check("display.show_design", r, results)

    print("done.")
    return results


def test_smoke_display_aliases():
    """Every alias step must PASS (needs --run-hardware)."""
    results = run_smoke(mac=TEST_MAC)
    failed = [label for label, passed in results if not passed]
    assert results, "smoke flow produced no checkable steps"
    assert not failed, f"smoke steps failed: {failed}"


if __name__ == "__main__":
    mac = sys.argv[1] if len(sys.argv) > 1 else None
    run_smoke(mac=mac)
