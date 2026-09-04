#!/usr/bin/env python3
"""Drive the running divoomd over its Unix socket: scan, and if a Divoom device
is in range, run a connect -> brightness round-trip -> disconnect. Used by
test_host.sh to validate the btleplug/BlueZ BLE path on Linux end-to-end."""
import json
import socket
import sys

SOCK = sys.argv[1] if len(sys.argv) > 1 else "/tmp/divoomd.sock"


def call(cmd, args=None, timeout=25):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    s.connect(SOCK)
    s.sendall((json.dumps({"command": cmd, "args": args or {}}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        d = s.recv(65536)
        if not d:
            break
        buf += d
    s.close()
    return json.loads(buf.decode().split("\n")[0])


def main():
    print("ping:", call("ping"))
    r = call("scan", {"timeout": 10})
    devs = r.get("devices", [])
    print(f"scan: {len(devs)} device(s)")
    for d in devs:
        print("  ", d.get("name"), d.get("address"))

    hint = ("pixoo", "timoo", "tivoo", "ditoo", "divoom")
    target = next((d for d in devs if any(k in (d.get("name") or "").lower() for k in hint)), None)
    if not target:
        print("RESULT: BLE stack reached the adapter + scanned OK; no Divoom device in range to exercise.")
        return 0

    mac = target["address"]
    print(f"== exercising {target.get('name')} ({mac}) ==")
    conn = call("connect", {"mac": mac}, timeout=30)
    print("connect:", conn)
    if not conn.get("success"):
        call("disconnect", timeout=20)
        print("RESULT: scan OK on Linux, but CONNECT FAILED:", conn.get("error"))
        return 1
    b1 = call("device_call", {"method": "device.get_brightness"}, timeout=20)
    print("get_brightness:", b1)
    print("set_brightness=55:", call("device_call", {"method": "device.set_brightness", "args": [55]}, timeout=20))
    b2 = call("device_call", {"method": "device.get_brightness"}, timeout=20)
    print("get_brightness:", b2)
    print("disconnect:", call("disconnect", timeout=20))
    ok = b1.get("success") and b2.get("success")
    print("RESULT:", "BLE hardware round-trip on Linux OK." if ok else "connected but read-back failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
