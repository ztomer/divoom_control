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

from divoom_client.daemon_protocol import DaemonClient


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
    rules = [("whatsapp", 6), ("mail", 7), ("slack", 13)]
    reply = client.set_routing(rules)
    assert reply["success"] is True


def test_rust_tcp_token_auth():
    # Resolved by VERSION: see tests/support/daemon_binary.py
    from tests.support.daemon_binary import require_divoomd

    bin_path = require_divoomd()

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
        text=True,
        stdin=subprocess.DEVNULL,
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


def test_rust_status_with_nothing_connected_reports_nothing():
    """2026-09-12: the daemon has no "current" device. It used to accept
    `--mac` and report that address as `mac` while `connected` was false --
    a panel it had never reached, presented as known. Now a status with
    nothing linked says so, and lists no devices."""
    from tests.support.daemon_binary import require_divoomd

    bin_path = require_divoomd()
    sp = "/tmp/divoomd_test_status_empty.sock"
    if os.path.exists(sp):
        os.remove(sp)
    proc = subprocess.Popen(
        [str(bin_path), "--socket", sp],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if os.path.exists(sp):
                break
            time.sleep(0.1)
        else:
            out, err = proc.communicate(timeout=2)
            pytest.fail(f"Rust daemon failed to bind. stdout: {out}, stderr: {err}")
        client = DaemonClient(socket_path=sp)
        reply = client.send_command("device_status")
        assert reply["success"] is True
        assert reply.get("mac") is None
        assert reply.get("connected") is False
        assert reply.get("connection_state") == "disconnected"
        assert reply.get("devices") == []
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        if os.path.exists(sp):
            os.remove(sp)


def test_rust_spp_connect_failure_integration(rust_daemon_ctx):
    client = rust_daemon_ctx
    # Attempting to connect to a dummy MAC with use_ios_le_protocol=False
    # should trigger the SppTransport path, spawning spp_bridge.py.
    # It will fail (due to no such device) and return an SPP-specific connection error.
    reply = client.connect_device(mac="11:22:33:44:55:66", use_ios_le_protocol=False)
    assert reply["success"] is False
    # The error message should indicate SPP connection failure
    assert "spp" in reply.get("error", "").lower()


def test_rust_set_clock_rich(rust_daemon_ctx):
    client = rust_daemon_ctx

    reply = client.send_command(
        "device_call",
        {
            "method": "display.set_clock_rich",
            "kw": {
                "style": 3,
                "twentyfour": True,
                "humidity": True,
                "weather": False,
                "date": True,
                "color": "#ff00ff",
            },
        },
    )
    assert reply["success"] is False
    err = reply["error"].lower()
    assert "no device connected" in err or "not connected" in err


def test_rust_mcp_via_daemon(rust_daemon_ctx):
    """MCP -> Rust daemon (mock device), driven through the SHIPPING server.

    Rewritten 2026-09-25 (phase L5). This used to build a Python ``MCPServer``
    over a ``DaemonDeviceProxy``, which meant the integration it covered — the
    MCP layer reaching a daemon and landing on a device — was covered only for
    the implementation that no longer ships. It now spawns ``divoomd mcp``, the
    process an MCP client actually launches, pointed at the same mock-device
    daemon. (Exact wire bytes are asserted in the Rust mock_device_tests; over
    the socket we can only observe success, which is what this verifies.)
    """
    import json
    import subprocess

    client = rust_daemon_ctx
    conn = client.send_command("connect", {"mock": True})
    assert conn.get("success") is True, conn

    env = dict(os.environ)
    env["DIVOOM_SOCKET"] = client.socket_path
    for var in ("DIVOOM_DAEMON_HOST", "DIVOOM_DAEMON_PORT", "DIVOOM_DAEMON_TOKEN"):
        env.pop(var, None)

    from tests.support.daemon_binary import require_divoomd

    proc = subprocess.Popen(
        [str(require_divoomd()), "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    # The MCP handshake first: rmcp (lane MCP.DV) answers nothing before it,
    # exactly as the spec says, where the hand-rolled loop answered anything.
    requests = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "parity", "version": "0"},
                },
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "set_volume", "arguments": {"level": 8}},
            }
        )
        + "\n"
    )
    try:
        out, _err = proc.communicate(requests, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise

    # Paired by id, not by line order: rmcp serves requests concurrently.
    by_id = {r.get("id"): r for r in (json.loads(line) for line in out.splitlines() if line.strip())}
    replies = [by_id.get(1, {}), by_id.get(2, {})]
    assert all(replies), f"expected a handshake, got: {out!r}"

    names = {t["name"] for t in replies[0]["result"]["tools"]}
    assert "set_volume" in names and "set_brightness" in names, names

    called = replies[1]
    assert "result" in called, called
    assert called["result"].get("isError") in (None, False), called
