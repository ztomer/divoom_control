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


def _identify_client(monkeypatch, devices):
    class _C:
        def scan(self, timeout=None, limit=None):
            return {"success": True, "devices": devices}
    monkeypatch.setattr(cli_commands, "_daemon_client", lambda: _C())


async def test_cmd_identify_errors_when_nothing_found(monkeypatch) -> None:
    _identify_client(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_identify(_parse("identify", "--timeout", "0.01"))
    assert exc.value.code == 1


async def test_cmd_identify_json(monkeypatch, capsys) -> None:
    # The daemon's scan carries the advertisement (company id -> hex bytes).
    _identify_client(monkeypatch, [{"address": "AA:BB:CC:DD:EE:FF", "name": "Pixoo",
                                    "manufacturer_data": {"1": "0102"}, "service_uuids": ["1234"]}])
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
    _identify_client(monkeypatch, [{"address": "AA:BB:CC:DD:EE:FF", "name": "Pixoo",
                                    "manufacturer_data": {"1": "0102"}, "service_uuids": ["1234"]}])
    rc = await cli_commands.cmd_identify(_parse("identify", "--timeout", "0.01"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "AA:BB:CC:DD:EE:FF" in out
    assert "company_id=0x0001" in out
    assert "service_uuid: 1234" in out


# ── cmd_mcp_server ───────────────────────────────────────────────────────────
#
# Rewritten 2026-09-25 (phase L5): the command no longer builds a Python MCP
# server, it hands the process to `divoomd mcp`. These three tests kept their
# subjects — an unreachable daemon, the local path, the remote env — and changed
# their instrument from a fake MCPServer to a fake execv. The end-to-end proof
# that the native server really answers lives in tests/test_mcp_delegation.py;
# what matters here is the wiring, which is what these three were actually
# written for.


def _fake_execv(recorded: list):
    def _execv(path, argv):
        recorded.append((path, argv))
        raise SystemExit(0)  # execv never returns

    return _execv


async def test_cmd_mcp_server_errors_when_daemon_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(
        "divoom_client.daemon_client.ensure_daemon", lambda *a, **k: None
    )
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_mcp_server(_parse("mcp-server"))
    assert exc.value.code == 1


async def test_cmd_mcp_server_local_happy_path(monkeypatch) -> None:
    """The local path: the daemon is ensured, then the native server is exec'd."""
    fake_client = object()
    monkeypatch.setattr(
        "divoom_client.daemon_client.ensure_daemon", lambda *a, **k: fake_client
    )
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    monkeypatch.setattr(os, "environ", os.environ.copy())
    execs: list = []
    monkeypatch.setattr(os, "execv", _fake_execv(execs))

    with pytest.raises(SystemExit):
        await cli_commands.cmd_mcp_server(
            _parse("mcp-server", "--socket", "/tmp/fake-divoom-test.sock")
        )

    assert execs == [("/opt/divoomd", ["/opt/divoomd", "mcp"])]
    # The child inherits the daemon target; without this it would silently
    # connect to /tmp/divoom.sock and report the daemon as down.
    assert os.environ["DIVOOM_SOCKET"] == "/tmp/fake-divoom-test.sock"


async def test_cmd_mcp_server_remote_host_sets_env(monkeypatch) -> None:
    # Insulate real os.environ from this test's mutations: cmd_mcp_server
    # writes directly to os.environ, so swap in a throwaway copy that
    # monkeypatch discards on teardown.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    fake_client = object()
    monkeypatch.setattr(
        "divoom_client.daemon_client.ensure_daemon", lambda *a, **k: fake_client
    )
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    execs: list = []
    monkeypatch.setattr(os, "execv", _fake_execv(execs))

    with pytest.raises(SystemExit):
        await cli_commands.cmd_mcp_server(
            _parse("mcp-server", "--host", "1.2.3.4", "--port", "9100", "--token", "secret")
        )

    assert execs, "the remote path must still hand off to the native server"
    assert os.environ["DIVOOM_DAEMON_HOST"] == "1.2.3.4"
    assert os.environ["DIVOOM_DAEMON_PORT"] == "9100"
    assert os.environ["DIVOOM_DAEMON_TOKEN"] == "secret"


async def test_cmd_mcp_server_passes_mac_to_the_daemon_it_may_spawn(monkeypatch) -> None:
    """`--mac` exists so a freshly spawned daemon binds the right device.

    It is consumed by `ensure_daemon` and is NOT an argument to `divoomd mcp`,
    which connects to whatever daemon is already there. Dropping the hand-off
    would make the flag silently do nothing on a fresh machine.
    """
    seen: dict = {}

    def fake_ensure(socket_path, *, mac=None, **kwargs):
        seen["socket_path"] = socket_path
        seen["mac"] = mac
        return object()

    monkeypatch.setattr("divoom_client.daemon_client.ensure_daemon", fake_ensure)
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(os, "execv", _fake_execv([]))

    with pytest.raises(SystemExit):
        await cli_commands.cmd_mcp_server(
            _parse("mcp-server", "--socket", "/tmp/x.sock", "--mac", "11:22:33:44:55:66")
        )

    assert seen["mac"] == "11:22:33:44:55:66"
