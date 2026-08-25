"""cmd_identify + cmd_mcp_server coverage (split from
test_cli_commands_coverage.py)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from divoom_lib import cli_commands
from tests.support.cli_common import _parse


# ── cmd_identify ─────────────────────────────────────────────────────────


class _FakeIdentifyScanner:
    """Stand-in for bleak.BleakScanner, patterned after the _FakeScanner in
    tests/test_discovery.py. Fires the detection callback synchronously from
    start() so no real BLE adapter is ever touched."""

    devices: list = []

    def __init__(self, detection_callback=None) -> None:
        self._cb = detection_callback

    async def start(self) -> None:
        for device, adv in self.devices:
            self._cb(device, adv)

    async def stop(self) -> None:
        pass


async def test_cmd_identify_errors_when_nothing_found(monkeypatch) -> None:
    _FakeIdentifyScanner.devices = []
    monkeypatch.setattr("bleak.BleakScanner", _FakeIdentifyScanner)
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_identify(_parse("identify", "--timeout", "0.01"))
    assert exc.value.code == 1


async def test_cmd_identify_json(monkeypatch, capsys) -> None:
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Pixoo")
    adv = SimpleNamespace(manufacturer_data={0x0001: b"\x01\x02"}, service_uuids=["1234"])
    _FakeIdentifyScanner.devices = [(device, adv)]
    monkeypatch.setattr("bleak.BleakScanner", _FakeIdentifyScanner)
    rc = await cli_commands.cmd_identify(
        _parse("identify", "--timeout", "0.01", "--json")
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    entry = data["AA:BB:CC:DD:EE:FF"]
    assert entry["name"] == "Pixoo"
    assert entry["manufacturer_data"]["0x1"] == "0102"
    assert entry["service_uuids"] == ["1234"]


async def test_cmd_identify_text(monkeypatch, capsys) -> None:
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Pixoo")
    adv = SimpleNamespace(manufacturer_data={0x0001: b"\x01\x02"}, service_uuids=["1234"])
    _FakeIdentifyScanner.devices = [(device, adv)]
    monkeypatch.setattr("bleak.BleakScanner", _FakeIdentifyScanner)
    rc = await cli_commands.cmd_identify(_parse("identify", "--timeout", "0.01"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "AA:BB:CC:DD:EE:FF" in out
    assert "company_id=0x0001" in out
    assert "service_uuids:" in out


# ── cmd_mcp_server ───────────────────────────────────────────────────────


class _FakeMCPServer:
    def __init__(self, server_info) -> None:
        self.server_info = server_info
        self.tools = []
        self.ran = False

    async def run_stdio(self) -> None:
        self.ran = True


async def test_cmd_mcp_server_errors_when_daemon_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(
        "divoom_client.daemon_client.ensure_daemon", lambda *a, **k: None
    )
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_mcp_server(_parse("mcp-server"))
    assert exc.value.code == 1


async def test_cmd_mcp_server_local_happy_path(monkeypatch) -> None:
    fake_client = object()
    monkeypatch.setattr(
        "divoom_client.daemon_client.ensure_daemon", lambda *a, **k: fake_client
    )

    class FakeProxy:
        def __init__(self, client) -> None:
            self.client = client

    monkeypatch.setattr("divoom_client.daemon_client.DaemonDeviceProxy", FakeProxy)
    monkeypatch.setattr("divoom_lib.mcp_server.MCPServer", _FakeMCPServer)
    monkeypatch.setattr(
        "divoom_lib.mcp_tools.build_tool_catalog", lambda proxy: ["t1", "t2", "t3"]
    )
    rc = await cli_commands.cmd_mcp_server(
        _parse("mcp-server", "--socket", "/tmp/fake-divoom-test.sock")
    )
    assert rc == 0


async def test_cmd_mcp_server_remote_host_sets_env(monkeypatch) -> None:
    # Insulate real os.environ from this test's mutations: cmd_mcp_server
    # writes directly to os.environ, so swap in a throwaway copy that
    # monkeypatch discards on teardown.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    fake_client = object()
    monkeypatch.setattr(
        "divoom_client.daemon_client.ensure_daemon", lambda *a, **k: fake_client
    )

    class FakeProxy:
        def __init__(self, client) -> None:
            self.client = client

    monkeypatch.setattr("divoom_client.daemon_client.DaemonDeviceProxy", FakeProxy)
    monkeypatch.setattr("divoom_lib.mcp_server.MCPServer", _FakeMCPServer)
    monkeypatch.setattr("divoom_lib.mcp_tools.build_tool_catalog", lambda proxy: [])

    rc = await cli_commands.cmd_mcp_server(
        _parse("mcp-server", "--host", "1.2.3.4", "--port", "9100", "--token", "secret")
    )
    assert rc == 0
    assert os.environ["DIVOOM_DAEMON_HOST"] == "1.2.3.4"
    assert os.environ["DIVOOM_DAEMON_PORT"] == "9100"
    assert os.environ["DIVOOM_DAEMON_TOKEN"] == "secret"
