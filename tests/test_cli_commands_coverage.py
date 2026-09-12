"""
Coverage-focused unit tests for divoom_lib/cli_commands.py.

Scope: this file only. Every touchpoint that would normally open BLE or hit
the cloud/daemon is mocked — no real hardware/network calls are made here
(see docs/PLANNING_ROUND61.md item 1 + AGENTS.md hardware-in-loop notes).

Conventions follow tests/test_cli.py: build real argparse.Namespace objects
via ``cli_module.build_parser().parse_args([...])`` where practical, and a
lightweight ``FakeDivoom`` double for the command handlers that need a
connected device.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from divoom_lib import cli as cli_module
from divoom_lib import cli_commands
from divoom_lib.models.capabilities import DeviceRegistry
from tests.support.cli_common import _parse


class FakeDivoom:
    """Shape-compatible stand-in for a connected ``Divoom`` instance, wired
    with AsyncMock namespaces for every sub-API the setter commands touch."""

    def __init__(self) -> None:
        self.capabilities = MagicMock()
        self.capabilities.has_fm = True
        self.capabilities.has_alarm = True
        self.capabilities.has_weather = True
        self.music = MagicMock()
        self.music.set_volume = AsyncMock(return_value=True)
        self.device = MagicMock()
        self.device.set_brightness = AsyncMock(return_value=True)
        self.radio = MagicMock()
        self.radio.set_radio_frequency = AsyncMock(return_value=True)
        self.alarm = MagicMock()
        self.alarm.set_alarm = AsyncMock(return_value=True)
        self.display = MagicMock()
        self.display.show_image = AsyncMock(return_value=True)
        self.disconnect = AsyncMock()


# ── _print helper: direct branch coverage ──────────────────────────────


def test_print_scalar_as_json(capsys) -> None:
    cli_commands._print("hello", as_json=True)
    out = json.loads(capsys.readouterr().out)
    assert out == {"result": "hello"}


def test_print_list_non_json(capsys) -> None:
    cli_commands._print(["a", "b"], as_json=False)
    assert capsys.readouterr().out.splitlines() == ["a", "b"]


def test_print_dict_non_json(capsys) -> None:
    cli_commands._print({"x": 1, "y": 2}, as_json=False)
    out = capsys.readouterr().out
    assert "x: 1" in out
    assert "y: 2" in out


# ── _resolve_device ─────────────────────────────────────────────────────


async def test_resolve_device_bypasses_connect_for_pair_and_identify() -> None:
    d, mac = await cli_commands._resolve_device(SimpleNamespace(command="pair", mac="AA:BB"))
    assert d is None and mac == "AA:BB"
    d, mac = await cli_commands._resolve_device(SimpleNamespace(command="identify", mac=None))
    assert d is None and mac == ""


class _FakeClient:
    """The daemon as the CLI sees it (2026-09-12: the CLI is a daemon client;
    it used to open BLE itself through the bleak facade)."""

    def __init__(self, *, status=None, per_mac=None, scan=None, connect=None):
        self.status = status or {"success": True, "connected": False, "mac": None, "devices": []}
        self.per_mac = per_mac or {}
        self.scan_reply = scan or {"success": True, "devices": []}
        self.connect_reply = connect or {"success": True, "connected": True}
        self.calls = []

    def device_status(self, mac=None):
        self.calls.append(("device_status", mac))
        if mac is not None:
            return self.per_mac.get(mac, {"success": True, "connected": False, "mac": mac})
        return self.status

    def scan(self, timeout=None, limit=None):
        self.calls.append(("scan", timeout))
        return self.scan_reply

    def connect_device(self, **kw):
        self.calls.append(("connect", kw.get("mac")))
        return self.connect_reply

    def device_call(self, method, args=None, kwargs=None, **kw):
        self.calls.append(("device_call", method, kw.get("mac")))
        return {"success": True, "result": True}


def _use_client(monkeypatch, client):
    monkeypatch.setattr(cli_commands, "_daemon_client", lambda: client)
    return client


async def test_resolve_device_explicit_mac_connects_through_the_daemon(monkeypatch) -> None:
    client = _use_client(monkeypatch, _FakeClient())
    ns = SimpleNamespace(command="set-volume", mac="AA:BB", timeout=1.0, device_type=None)
    d, mac = await cli_commands._resolve_device(ns)
    assert mac == "AA:BB"
    assert ("connect", "AA:BB") in client.calls, "not linked yet: the daemon connects it"
    assert ("scan", 1.0) not in client.calls, "an explicit mac never scans"
    assert d._mac == "AA:BB", "the proxy names its panel on every call"


async def test_resolve_device_uses_the_single_linked_panel(monkeypatch) -> None:
    client = _use_client(monkeypatch, _FakeClient(
        status={"success": True, "connected": True, "mac": "CC:DD", "devices": [{"mac": "CC:DD"}]},
        per_mac={"CC:DD": {"success": True, "connected": True, "mac": "CC:DD"}},
    ))
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=1.0, device_type=None)
    d, mac = await cli_commands._resolve_device(ns)
    assert mac == "CC:DD"
    assert not any(c[0] in ("scan", "connect") for c in client.calls)


async def test_resolve_device_refuses_to_guess_between_several_panels(monkeypatch) -> None:
    _use_client(monkeypatch, _FakeClient(
        status={"success": True, "connected": True, "mac": None,
                "devices": [{"mac": "AA:AA"}, {"mac": "BB:BB"}]},
    ))
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=1.0, device_type=None)
    with pytest.raises(SystemExit) as exc:
        await cli_commands._resolve_device(ns)
    assert exc.value.code == 2


async def test_resolve_device_scans_through_the_daemon_when_nothing_is_linked(monkeypatch) -> None:
    client = _use_client(monkeypatch, _FakeClient(
        scan={"success": True, "devices": [{"address": "EE:FF", "name": "Pixoo"}]},
    ))
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=2.5, device_type=None)
    d, mac = await cli_commands._resolve_device(ns)
    assert mac == "EE:FF"
    assert ("scan", 2.5) in client.calls and ("connect", "EE:FF") in client.calls


async def test_resolve_device_errors_when_no_devices_found(monkeypatch) -> None:
    _use_client(monkeypatch, _FakeClient())
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=0.1, device_type=None)
    with pytest.raises(SystemExit) as exc:
        await cli_commands._resolve_device(ns)
    assert exc.value.code == 1


def test_no_daemon_is_a_refusal_not_a_spawn(monkeypatch) -> None:
    # A shell-spawned daemon has no Bluetooth grant and dies on its first
    # scan, so the CLI attaches to a running one or says what to start.
    import divoom_client.daemon_client as dc
    seen = {}
    def fake_ensure(*a, **kw):
        seen.update(kw)
        return None
    monkeypatch.setattr(dc, "ensure_daemon", fake_ensure)
    with pytest.raises(SystemExit) as exc:
        cli_commands._daemon_client()
    assert exc.value.code == 3
    assert seen.get("spawn") is False


# ── cmd_scan ─────────────────────────────────────────────────────────────


async def test_cmd_scan_prints_results(monkeypatch, capsys) -> None:
    _use_client(monkeypatch, _FakeClient(
        scan={"success": True, "devices": [{"address": "AA:BB:CC:DD:EE:FF", "name": "Pixoo"}]}))
    rc = await cli_commands.cmd_scan(_parse("scan"))
    assert rc == 0
    assert "AA:BB:CC:DD:EE:FF  Pixoo" in capsys.readouterr().out


async def test_cmd_scan_no_devices_found(monkeypatch, capsys) -> None:
    _use_client(monkeypatch, _FakeClient())
    rc = await cli_commands.cmd_scan(_parse("scan"))
    assert rc == 0
    assert "no Divoom devices found" in capsys.readouterr().out


async def test_cmd_scan_json(monkeypatch, capsys) -> None:
    _use_client(monkeypatch, _FakeClient(
        scan={"success": True, "devices": [{"address": "AA:BB:CC:DD:EE:FF", "name": "Pixoo"}]}))
    rc = await cli_commands.cmd_scan(_parse("scan", "--json"))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == [{"address": "AA:BB:CC:DD:EE:FF", "name": "Pixoo"}]


# ── cmd_capabilities: notes formatting ─────────────────────────────────


async def test_cmd_capabilities_prints_notes(monkeypatch, capsys) -> None:
    class Caps:
        panel_resolution = 16
        has_fm = has_sd = has_scoreboard = has_anim_8b = False
        has_orientation = has_screen_mirror = has_alarm = False
        has_sleep = has_weather = has_mic = False
        notes = ("quirk-a", "quirk-b")

    class D:
        capabilities = Caps()

        async def disconnect(self):
            pass

    monkeypatch.setattr(cli_commands, "_capabilities", lambda a, m: Caps())

    async def fake_resolve(args):
        return D(), "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(cli_commands, "_resolve_device", fake_resolve)
    rc = await cli_commands.cmd_capabilities(_parse("capabilities"))
    assert rc == 0
    assert "quirk-a; quirk-b" in capsys.readouterr().out


# ── cmd_set_volume / cmd_set_brightness ────────────────────────────────


async def test_cmd_set_volume_happy_path(monkeypatch, capsys) -> None:
    fake = FakeDivoom()
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_set_volume(_parse("set-volume", "7", "--mac", "AA:BB"))
    assert rc == 0
    fake.music.set_volume.assert_awaited_once_with(7)
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link
    assert "set volume to 7/15" in capsys.readouterr().out


async def test_cmd_set_volume_device_reports_failure(monkeypatch) -> None:
    fake = FakeDivoom()
    fake.music.set_volume = AsyncMock(return_value=False)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_set_volume(_parse("set-volume", "7", "--mac", "AA:BB"))
    assert rc == 1
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link


async def test_cmd_set_brightness_happy_path(monkeypatch, capsys) -> None:
    fake = FakeDivoom()
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_set_brightness(
        _parse("set-brightness", "50", "--mac", "AA:BB")
    )
    assert rc == 0
    fake.device.set_brightness.assert_awaited_once_with(50)
    assert "set brightness to 50%" in capsys.readouterr().out


async def test_cmd_set_brightness_device_reports_failure(monkeypatch) -> None:
    fake = FakeDivoom()
    fake.device.set_brightness = AsyncMock(return_value=False)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_set_brightness(
        _parse("set-brightness", "50", "--mac", "AA:BB")
    )
    assert rc == 1
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link


# ── cmd_set_radio ────────────────────────────────────────────────────────


async def test_cmd_set_radio_rejects_when_no_fm_capability(monkeypatch) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_fm = False
    monkeypatch.setattr(cli_commands, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_set_radio(_parse("set-radio", "875", "--mac", "AA:BB"))
    assert exc.value.code == 1
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link


async def test_cmd_set_radio_happy_path(monkeypatch, capsys) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_fm = True
    monkeypatch.setattr(cli_commands, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_set_radio(_parse("set-radio", "875", "--mac", "AA:BB"))
    assert rc == 0
    fake.radio.set_radio_frequency.assert_awaited_once_with(875)
    assert "87.5 MHz" in capsys.readouterr().out


# ── cmd_set_alarm ────────────────────────────────────────────────────────


async def test_cmd_set_alarm_rejects_bad_time_format() -> None:
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_set_alarm(
            _parse("set-alarm", "not-a-time", "--mac", "AA:BB")
        )
    assert exc.value.code == 2


async def test_cmd_set_alarm_rejects_when_no_alarm_capability(monkeypatch) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_alarm = False
    monkeypatch.setattr(cli_commands, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_set_alarm(_parse("set-alarm", "07:30", "--mac", "AA:BB"))
    assert exc.value.code == 1


async def test_cmd_set_alarm_happy_path(monkeypatch, capsys) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_alarm = True
    monkeypatch.setattr(cli_commands, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_set_alarm(_parse("set-alarm", "07:30", "--mac", "AA:BB"))
    assert rc == 0
    fake.alarm.set_alarm.assert_awaited_once_with(0, 1, 7, 30, 127, 0, 0)
    assert "07:30" in capsys.readouterr().out


# ── cmd_push_image / cmd_push_gif ───────────────────────────────────────


async def test_cmd_push_image_file_not_found(tmp_path) -> None:
    missing = tmp_path / "missing.png"
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_push_image(_parse("push-image", str(missing)))
    assert exc.value.code == 2


async def test_cmd_push_image_happy_path(monkeypatch, tmp_path, capsys) -> None:
    f = tmp_path / "pic.png"
    f.write_bytes(b"fake-png-bytes")
    fake = FakeDivoom()
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_push_image(
        _parse("push-image", str(f), "--mac", "AA:BB")
    )
    assert rc == 0
    fake.display.show_image.assert_awaited_once_with(str(f))
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link
    assert "pic.png" in capsys.readouterr().out


async def test_cmd_push_gif_file_not_found(tmp_path) -> None:
    missing = tmp_path / "missing.gif"
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_push_gif(_parse("push-gif", str(missing)))
    assert exc.value.code == 2


async def test_cmd_push_gif_device_reports_failure(monkeypatch, tmp_path) -> None:
    f = tmp_path / "anim.gif"
    f.write_bytes(b"fake-gif-bytes")
    fake = FakeDivoom()
    fake.display.show_image = AsyncMock(return_value=False)
    monkeypatch.setattr(
        cli_commands, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_commands.cmd_push_gif(_parse("push-gif", str(f), "--mac", "AA:BB"))
    assert rc == 1
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link


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
