"""CLI subcommands `pair`, `daemon`, `menubar` (split from
test_cli_commands_coverage.py for the 500-line cap)."""
import json

import pytest

from divoom_lib import cli_commands
from divoom_lib.models.capabilities import DeviceRegistry
from tests.support.cli_common import _parse


# ── cmd_pair ─────────────────────────────────────────────────────────────


async def test_cmd_pair_requires_mac() -> None:
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_pair(_parse("pair"))
    assert exc.value.code == 2


async def test_cmd_pair_requires_type() -> None:
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_pair(
            _parse("pair", "--mac", "AA:BB:CC:DD:EE:FF")
        )
    assert exc.value.code == 2


async def test_cmd_pair_rejects_unknown_device_type() -> None:
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_pair(
            _parse("pair", "--mac", "AA:BB:CC:DD:EE:FF", "--type", "NotARealDevice")
        )
    assert exc.value.code == 2


async def test_cmd_pair_happy_path_json(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        cli_commands, "DeviceRegistry", lambda: DeviceRegistry(tmp_path / "devices.json")
    )
    rc = await cli_commands.cmd_pair(
        _parse("pair", "--mac", "AA:BB:CC:DD:EE:FF", "--type", "TivooMax", "--json")
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"registered": "AA:BB:CC:DD:EE:FF", "device_type": "TivooMax"}


async def test_cmd_pair_happy_path_text(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        cli_commands, "DeviceRegistry", lambda: DeviceRegistry(tmp_path / "devices.json")
    )
    rc = await cli_commands.cmd_pair(
        _parse("pair", "--mac", "AA:BB:CC:DD:EE:FF", "--type", "TivooMax")
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "registered AA:BB:CC:DD:EE:FF" in out
    assert "registry file:" in out




# ── cmd_daemon ───────────────────────────────────────────────────────────


async def test_cmd_daemon_reports_archived_and_fails(capsys) -> None:
    """The Python daemon server was archived 2026-07-13; this subcommand now
    prints a clear pointer at divoomd instead of an ImportError."""
    rc = await cli_commands.cmd_daemon(
        _parse("daemon", "--socket", "/tmp/fake-daemon-test.sock")
    )
    assert rc == 1
    assert "divoomd" in capsys.readouterr().err


# ── cmd_menubar ──────────────────────────────────────────────────────────


def test_cmd_menubar_is_retired_and_points_at_the_rust_agent(capsys) -> None:
    """R66: the pyobjc menubar was removed; the subcommand survives only to give
    an actionable error rather than a raw ImportError (same as cmd_daemon)."""
    rc = cli_commands.cmd_menubar(_parse("menubar"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "run.sh --menubar" in err
    assert "divoom-menubar" in err
