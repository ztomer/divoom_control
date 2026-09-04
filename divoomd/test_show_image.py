#!/usr/bin/env python3
"""
Smoke-test for device.show_image via the Rust native daemon.
Pushes a 16x16 solid-red frame to the connected Pixoo.
Usage: python3 test_show_image.py [mac_address]
"""
import sys, socket, json, time

SOCK = "/tmp/divoomd.sock"

def call(sock_path, req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n")[0])

def main():
    mac = sys.argv[1] if len(sys.argv) > 1 else None

    # Ping
    r = call(SOCK, {"command": "ping"})
    print("ping:", r)

    # Status
    r = call(SOCK, {"command": "device_status"})
    print("status:", r)
    connected = r.get("connected", False)

    if not connected:
        if not mac:
            print("scanning for device...")
            r = call(SOCK, {"command": "scan", "args": {"timeout": 8}})
            print("scan:", r)
            devs = r.get("devices", [])
            if not devs:
                print("no devices found")
                return
            mac = devs[0]["address"]
            print(f"using device: {mac}")
        print(f"connecting to {mac}...")
        r = call(SOCK, {"command": "connect", "args": {"mac": mac}})
        print("connect:", r)
        if not r.get("connected"):
            print("connect failed")
            return

    # Read brightness first (sanity)
    r = call(SOCK, {"command": "device_call", "args": {"method": "device.get_brightness"}})
    print("get_brightness:", r)

    # Build a 16x16 test image: red/green/blue/white quadrants
    w, h = 16, 16
    rgb = []
    for y in range(h):
        for x in range(w):
            if x < 8 and y < 8:
                rgb += [255, 0, 0]      # top-left: red
            elif x >= 8 and y < 8:
                rgb += [0, 255, 0]      # top-right: green
            elif x < 8 and y >= 8:
                rgb += [0, 0, 255]      # bottom-left: blue
            else:
                rgb += [255, 255, 255]  # bottom-right: white
    assert len(rgb) == w * h * 3

    print(f"pushing {w}x{h} test image ({len(rgb)} RGB bytes, {len(rgb)//3} pixels)...")
    t0 = time.time()
    r = call(SOCK, {"command": "device_call", "args": {
        "method": "device.show_image",
        "w": w,
        "h": h,
        "time_ms": 100,
        "rgb": rgb,
    }})
    elapsed = time.time() - t0
    print(f"show_image ({elapsed:.2f}s):", r)

if __name__ == "__main__":
    main()
