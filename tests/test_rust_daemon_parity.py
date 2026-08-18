"""Integration parity tests for the native Rust daemon (divoomd).

Spawns the compiled Rust divoomd binary and drives it using the Python DaemonClient
to assert that all notification/status commands produce identical JSON structures to the Python daemon.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_daemon.daemon_protocol import DaemonClient


@pytest.fixture
def rust_daemon_ctx():
    # Locate the compiled Rust binary (mirrors DaemonClient's dev-tree discovery).
    repo_root = Path(__file__).parent.parent
    bin_path = None
    for folder in ("release", "debug"):
        candidate = repo_root / "target" / folder / "divoomd"
        if candidate.exists():
            bin_path = candidate
            break

    if bin_path is None:
        pytest.skip("Rust binary not found. Run `cargo build` in divoomd/ first.")

    sp = f"/tmp/divoomd_parity_{os.getpid()}.sock"
    if os.path.exists(sp):
        os.remove(sp)

    # Spawn divoomd as a subprocess
    proc = subprocess.Popen(
        [str(bin_path), "--socket", sp],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait for the socket to be bound
    bound = False
    for _ in range(50):
        if os.path.exists(sp):
            bound = True
            break
        time.sleep(0.05)

    if not bound:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=1.0)
        pytest.fail(f"Rust daemon failed to bind to {sp}. stdout: {stdout}, stderr: {stderr}")

    try:
        yield DaemonClient(sp)
    finally:
        # Shutdown cleanly via socket or SIGTERM
        try:
            DaemonClient(sp).send_command("shutdown")
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(sp):
            os.remove(sp)


def test_rust_ping(rust_daemon_ctx):
    client = rust_daemon_ctx
    reply = client.send_command("ping")
    assert reply["success"] is True
    # The native daemon returns {"success": true, "pong": true}
    assert reply.get("pong") is True


def test_rust_get_status(rust_daemon_ctx):
    client = rust_daemon_ctx
    reply = client.send_command("get_status")
    assert reply["success"] is True
    assert "uptime_s" in reply
    assert reply["state"] in ("idle", "active", "error")
    assert reply["counters"] == {"seen": 0, "routed": 0, "dropped": 0}


def test_rust_notification_status(rust_daemon_ctx):
    client = rust_daemon_ctx
    reply = client.send_command("notification_status")
    assert reply["success"] is True
    assert reply["state"] in ("idle", "active", "error")
    assert reply["counters"] == {"seen": 0, "routed": 0, "dropped": 0}


def test_rust_start_stop_notifications(rust_daemon_ctx):
    client = rust_daemon_ctx
    # start_notifications
    reply = client.send_command("start_notifications")
    
    # On non-macOS, start_notifications returns success=false or unsupported=true.
    # On macOS, it should start or report access/TCC errors.
    # Let's assert the schema properties.
    assert "success" in reply
    assert "state" in reply
    assert "counters" in reply
    
    # stop_notifications
    reply2 = client.send_command("stop_notifications")
    assert reply2["success"] is True
    assert reply2["state"] == "idle"
    assert "counters" in reply2


def test_rust_set_routing(rust_daemon_ctx):
    client = rust_daemon_ctx
    rules = [
        ("whatsapp", 6),
        ("mail", 7),
        ("slack", 13)
    ]
    reply = client.set_routing(rules)
    assert reply["success"] is True


def test_rust_tcp_token_auth():
    # Locate the compiled Rust binary
    repo_root = Path(__file__).parent.parent
    bin_path = repo_root / "target" / "debug" / "divoomd"
    if not bin_path.exists():
        bin_path = repo_root / "target" / "release" / "divoomd"
    if not bin_path.exists():
        pytest.skip(f"Rust binary not found at {bin_path}. Run cargo build first.")

    sp = f"/tmp/divoomd_parity_tcp_{os.getpid()}.sock"
    if os.path.exists(sp):
        os.remove(sp)

    host = "127.0.0.1"
    port = 9099
    token = "my_secret_token"

    # Spawn divoomd with TCP listener enabled and token auth required
    proc = subprocess.Popen(
        [str(bin_path), "--socket", sp, "--host", host, "--port", str(port), "--token", token],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait for the Unix socket (and TCP port) to be bound
    bound = False
    for _ in range(50):
        if os.path.exists(sp):
            bound = True
            break
        time.sleep(0.05)

    if not bound:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=1.0)
        pytest.fail(f"Rust daemon failed to bind. stdout: {stdout}, stderr: {stderr}")

    try:
        # Test 1: Successful auth with correct token
        client_ok = DaemonClient(host=host, port=port, token=token)
        reply = client_ok.send_command("ping")
        assert reply["success"] is True
        assert reply.get("pong") is True

        # Test 2: Unauthorized with wrong token
        client_wrong = DaemonClient(host=host, port=port, token="wrong_token")
        reply = client_wrong.send_command("ping")
        assert reply["success"] is False
        assert "unauthorized" in reply.get("error", "").lower()

        # Test 3: Unauthorized with no token
        client_none = DaemonClient(host=host, port=port, token=None)
        reply = client_none.send_command("ping")
        assert reply["success"] is False
        assert "unauthorized" in reply.get("error", "").lower()

    finally:
        # Shutdown cleanly via Unix socket (unauthenticated)
        try:
            DaemonClient(sp).send_command("shutdown")
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(sp):
            os.remove(sp)


def test_rust_default_mac():
    # Locate the compiled Rust binary
    repo_root = Path(__file__).parent.parent
    bin_path = repo_root / "target" / "debug" / "divoomd"
    if not bin_path.exists():
        bin_path = repo_root / "target" / "release" / "divoomd"
    if not bin_path.exists():
        pytest.skip(f"Rust binary not found at {bin_path}. Run cargo build first.")

    sp = f"/tmp/divoomd_parity_mac_{os.getpid()}.sock"
    if os.path.exists(sp):
        os.remove(sp)

    default_mac = "AA:BB:CC:DD:EE:FF"

    # Spawn divoomd with a default MAC address configured
    proc = subprocess.Popen(
        [str(bin_path), "--socket", sp, "--mac", default_mac],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait for the Unix socket to be bound
    bound = False
    for _ in range(50):
        if os.path.exists(sp):
            bound = True
            break
        time.sleep(0.05)

    if not bound:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=1.0)
        pytest.fail(f"Rust daemon failed to bind. stdout: {stdout}, stderr: {stderr}")

    try:
        client = DaemonClient(sp)
        reply = client.send_command("device_status")
        assert reply["success"] is True
        assert reply.get("mac") == default_mac
        assert reply.get("connected") is False
        assert reply.get("connection_state") == "disconnected"

    finally:
        try:
            DaemonClient(sp).send_command("shutdown")
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(sp):
            os.remove(sp)


def test_rust_spp_connect_failure_integration(rust_daemon_ctx):
    client = rust_daemon_ctx
    # Attempting to connect to a dummy MAC with use_ios_le_protocol=False
    # should trigger the SppTransport path, spawning spp_bridge.py.
    # It will fail (due to no such device) and return an SPP-specific connection error.
    reply = client.connect_device(
        mac="11:22:33:44:55:66",
        use_ios_le_protocol=False
    )
    assert reply["success"] is False
    # The error message should indicate SPP connection failure
    assert "spp" in reply.get("error", "").lower()


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
    reply = client.send_command("fetch_gallery", {
        "classify": 18,
        "limit": 3
    })
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


def test_rust_set_clock_rich(rust_daemon_ctx):
    client = rust_daemon_ctx

    reply = client.send_command("device_call", {
        "method": "display.set_clock_rich",
        "kw": {
            "style": 3,
            "twentyfour": True,
            "humidity": True,
            "weather": False,
            "date": True,
            "color": "#ff00ff"
        }
    })
    assert reply["success"] is False
    err = reply["error"].lower()
    assert "no device connected" in err or "not connected" in err


def test_rust_mcp_via_daemon(rust_daemon_ctx):
    """Phase 4 Tier A: MCP server -> DaemonDeviceProxy -> Rust daemon (mock device).

    Drives the MCP layer end-to-end against the *Rust* daemon, hardware-free:
    tools/list builds the catalog over a daemon-routing proxy, and a tools/call
    round-trips through the Rust daemon's device_call to a mock device. (Exact wire
    bytes are asserted in the Rust mock_device_tests; over the socket we can only
    observe success, which is what this verifies.)
    """
    import asyncio
    from divoom_daemon.daemon_client import DaemonDeviceProxy
    from divoom_lib.mcp_server import MCPServer
    from divoom_lib.mcp_tools import build_tool_catalog

    client = rust_daemon_ctx
    conn = client.send_command("connect", {"mock": True})
    assert conn.get("success") is True, conn

    proxy = DaemonDeviceProxy(client)
    server = MCPServer(server_info={"name": "divoom-control", "version": "test"})
    server.tools = build_tool_catalog(proxy)

    async def drive():
        listed = await server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        assert "set_volume" in names and "set_brightness" in names, names

        return await server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "set_volume", "arguments": {"level": 8}},
        })

    called = asyncio.run(drive())
    assert "result" in called, called
    assert called["result"].get("isError") in (None, False), called


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
            if ev.get("type") == "owned_devices" and \
               any(d.get("address") == mac for d in ev.get("devices", [])):
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




