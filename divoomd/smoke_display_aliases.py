#!/usr/bin/env python3
"""
HW smoke-test: display.show_clock, display.show_light, display.set_brightness.
Usage: python3 test_display_aliases.py [mac_address]
"""
import sys, socket, json, time

SOCK = "/tmp/divoomd.sock"

def call(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk: break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n")[0])

def ok(label, resp):
    success = resp.get("success") or resp.get("result")
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {label}: {resp}")

mac = sys.argv[1] if len(sys.argv) > 1 else None

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
ok("display.get_brightness", r)
time.sleep(0.5)

# 3. set brightness 60
print("-- set_brightness 60 --")
r = call({"command": "device_call", "args": {"method": "display.set_brightness", "args": {"args": [60]}}})
ok("display.set_brightness(60)", r)
time.sleep(1)

# 4. show_clock face 0, 24h, with calendar
print("-- show_clock --")
r = call({"command": "device_call", "args": {
    "method": "display.show_clock",
    "args": {"kwargs": {"clock": 0, "twentyfour": True, "weather": False, "temp": False, "calendar": True, "color": "#FFFFFF"}}
}})
ok("display.show_clock", r)
time.sleep(3)

# 5. show_light — red
print("-- show_light red --")
r = call({"command": "device_call", "args": {
    "method": "display.show_light",
    "args": {"kwargs": {"color": [255, 0, 0], "brightness": 80, "power": True}}
}})
ok("display.show_light red", r)
time.sleep(3)

# 6. show_light — blue via hex
print("-- show_light blue (#0000FF) --")
r = call({"command": "device_call", "args": {
    "method": "display.show_light",
    "args": {"kwargs": {"color": "#0000FF", "brightness": 60, "power": True}}
}})
ok("display.show_light blue", r)
time.sleep(3)

# 7. show_design — return to custom art channel
print("-- show_design --")
r = call({"command": "device_call", "args": {"method": "display.show_design", "args": {}}})
ok("display.show_design", r)

print("done.")
