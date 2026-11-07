"""Integration parity tests for the native Rust daemon (divoomd) -- hardware and cloud.

Split from ``test_rust_daemon_parity.py`` (the control plane: ping, status,
notifications, routing, auth, clock, MCP). These need ``--run-hardware`` or a
cloud login and skip without them; the daemon fixture is in conftest.py.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_client.daemon_protocol import DaemonClient


def test_rust_hardware_parity(request, rust_daemon_ctx):
    if not request.config.getoption("--run-hardware"):
        pytest.skip("Requires --run-hardware flag")

    client = rust_daemon_ctx

    # 1. Scan for Divoom devices via the Rust daemon
    reply = client.scan(timeout=8.0)
    assert reply["success"] is True
    devices = reply.get("devices", [])
    if not devices:
        pytest.skip("No physical Divoom devices found nearby")

    print(f"\n[Hardware] discovered {len(devices)} devices:")
    for d in devices:
        print(f"  {d.get('name')} ({d.get('address')})")

    def op(method, args=None):
        payload = {"method": method}
        if args is not None:
            payload["args"] = args
        return client.send_command("device_call", payload)

    # 2. Full lifecycle loop on a canonical device (prefer a Pixoo), proving
    #    connect → device_call → disconnect → reconnect stays coherent across
    #    iterations and never wedges the device lock.
    target = next((d for d in devices if "pixoo" in d["name"].lower()), devices[0])
    mac = target["address"]
    print(f"[Hardware] lifecycle loop on {target['name']} ({mac})")

    for i in range(3):
        r = client.connect_device(mac=mac)
        assert r["success"] is True, f"connect iter {i}: {r}"
        assert r["connected"] is True
        st = client.send_command("device_status")
        assert st["success"] and st["connected"], f"status iter {i}: {st}"

        g = op("display.get_brightness")
        assert g["success"] is True, f"get_brightness iter {i}: {g}"
        assert isinstance(g["result"], int)
        orig = g["result"]

        s = op("display.set_brightness", [40])
        assert s["success"] is True
        assert op("display.get_brightness")["result"] == 40

        # exercise a channel switch + a hot-channel op (the historically "long" path)
        assert op("display.show_clock")["success"] is True
        assert op("hot_update.show_hot_channel")["success"] is True

        # restore + disconnect
        assert op("display.set_brightness", [orig])["success"] is True
        d = client.disconnect_device()
        assert d["success"] is True, f"disconnect iter {i}: {d}"
    print("[Hardware] 3x connect/device_call/disconnect loop OK")

    # 3. The daemon is a single-device owner: confirm it can ALSO reach every
    #    other discovered device (sequential connect/disconnect).
    for d in devices:
        if d["address"] == mac:
            continue
        r = client.connect_device(mac=d["address"])
        assert r["success"] is True, f"connect {d['name']}: {r}"
        assert r["connected"] is True
        st = client.send_command("device_status")
        assert st["success"] and st["connected"], f"status {d['name']}: {st}"
        print(f"[Hardware] connected to {d['name']} OK")
        assert client.disconnect_device()["success"] is True
    print("[Hardware] multi-device connect/disconnect OK")


def test_rust_cloud_auth_endpoints(request, rust_daemon_ctx):
    if not request.config.getoption("--run-cloud"):
        pytest.skip("requires live Divoom cloud access; run with --run-cloud")
    client = rust_daemon_ctx

    # 1. Query cached credentials (should succeed)
    reply = client.send_command("get_cached_credentials")
    assert reply["success"] is True
    assert "credentials" in reply

    # 2. Query credentials (which performs guest login fallback if cache is empty/invalid)
    reply = client.send_command("get_credentials", {"force_refresh": False})
    assert reply["success"] is True
    assert "token" in reply
    assert "user_id" in reply
    assert "utc" in reply


def test_rust_fetch_gallery(request, rust_daemon_ctx):
    if not request.config.getoption("--run-cloud"):
        pytest.skip("requires live Divoom cloud access; run with --run-cloud")
    client = rust_daemon_ctx

    # Query gallery classify=18 (Recommend), limit=3
    reply = client.send_command("fetch_gallery", {"classify": 18, "limit": 3})
    assert reply["success"] is True
    assert "result" in reply
    res = reply["result"]
    assert res.get("ReturnCode") == 0
    assert "FileList" in res
    files = res["FileList"]
    assert isinstance(files, list)
    if len(files) > 0:
        first = files[0]
        assert "FileId" in first
        assert "FileName" in first


def test_rust_hardware_event_broadcast(request, rust_daemon_ctx):
    """R59/event-driven on REAL hardware: connecting a device must push a
    `status`(connected) + `owned_devices`(listing the real mac) broadcast that a
    subscriber receives — proving the UI can update live without polling. The
    disconnect must push `owned_devices`([]). Keeps hardware in the loop."""
    if not request.config.getoption("--run-hardware"):
        pytest.skip("Requires --run-hardware flag")

    client = rust_daemon_ctx
    reply = client.scan(timeout=8.0)
    devices = (reply or {}).get("devices", [])
    if not devices:
        pytest.skip("No physical Divoom devices found nearby")
    mac = devices[0]["address"]
    print(f"\n[Hardware] event-broadcast test on {devices[0].get('name')} ({mac})")

    events: list[dict] = []
    lock = threading.Lock()
    connected_ev = threading.Event()
    owned_ev = threading.Event()
    cleared_ev = threading.Event()

    def on_event(ev):
        with lock:
            events.append(ev)
            if ev.get("type") == "status" and ev.get("connected") is True:
                connected_ev.set()
            if ev.get("type") == "owned_devices" and any(d.get("address") == mac for d in ev.get("devices", [])):
                owned_ev.set()
            if ev.get("type") == "owned_devices" and ev.get("devices") == []:
                cleared_ev.set()

    sub = threading.Thread(target=client.subscribe, kwargs={"on_event": on_event}, daemon=True)
    sub.start()
    time.sleep(0.5)

    try:
        r = client.connect_device(mac=mac)
        assert r.get("success") is True, f"connect {mac}: {r}"
        assert connected_ev.wait(timeout=8), f"no connected status event: {events}"
        assert owned_ev.wait(timeout=8), f"no owned_devices event for {mac}: {events}"

        d = client.disconnect_device()
        assert d.get("success") is True, f"disconnect: {d}"
        assert cleared_ev.wait(timeout=8), f"owned_devices not cleared on disconnect: {events}"
        print("[Hardware] status + owned_devices broadcast verified live")
    finally:
        # subscriber thread ends when the fixture shuts the daemon down
        pass
