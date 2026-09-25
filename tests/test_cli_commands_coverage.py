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
from divoom_lib import cli_device_verbs
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
    d, mac = await cli_device_verbs._resolve_device(SimpleNamespace(command="pair", mac="AA:BB"))
    assert d is None and mac == "AA:BB"
    d, mac = await cli_device_verbs._resolve_device(SimpleNamespace(command="identify", mac=None))
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
    # `_daemon_client` takes the parsed args now (it reads `--socket`), so the
    # stand-in accepts and ignores them. The `args` shape reaching it is
    # asserted by the `--socket` tests, not here.
    monkeypatch.setattr(cli_commands, "_daemon_client", lambda *a, **k: client)
    return client


async def test_resolve_device_explicit_mac_connects_through_the_daemon(monkeypatch) -> None:
    client = _use_client(monkeypatch, _FakeClient())
    ns = SimpleNamespace(command="set-volume", mac="AA:BB", timeout=1.0, device_type=None)
    d, mac = await cli_device_verbs._resolve_device(ns)
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
    d, mac = await cli_device_verbs._resolve_device(ns)
    assert mac == "CC:DD"
    assert not any(c[0] in ("scan", "connect") for c in client.calls)


async def test_resolve_device_refuses_to_guess_between_several_panels(monkeypatch) -> None:
    _use_client(monkeypatch, _FakeClient(
        status={"success": True, "connected": True, "mac": None,
                "devices": [{"mac": "AA:AA"}, {"mac": "BB:BB"}]},
    ))
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=1.0, device_type=None)
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs._resolve_device(ns)
    assert exc.value.code == 2


async def test_resolve_device_scans_through_the_daemon_when_nothing_is_linked(monkeypatch) -> None:
    client = _use_client(monkeypatch, _FakeClient(
        scan={"success": True, "devices": [{"address": "EE:FF", "name": "Pixoo"}]},
    ))
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=2.5, device_type=None)
    d, mac = await cli_device_verbs._resolve_device(ns)
    assert mac == "EE:FF"
    assert ("scan", 2.5) in client.calls and ("connect", "EE:FF") in client.calls


async def test_resolve_device_errors_when_no_devices_found(monkeypatch) -> None:
    _use_client(monkeypatch, _FakeClient())
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=0.1, device_type=None)
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs._resolve_device(ns)
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


async def test_a_refused_scan_is_an_error_not_an_empty_list(monkeypatch, capsys) -> None:
    # Live 2026-09-12: the GUI's own scan was running, the daemon answered
    # "scan already in progress", and the CLI printed "(no Divoom devices
    # found)". A refusal must read as a refusal, on every scan path.
    _use_client(monkeypatch, _FakeClient(
        scan={"success": False, "error": "scan already in progress"}))
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_scan(_parse("scan"))
    assert exc.value.code == 1
    assert "scan already in progress" in capsys.readouterr().err
    ns = SimpleNamespace(command="set-volume", mac=None, timeout=1.0, device_type=None)
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs._resolve_device(ns)
    assert exc.value.code == 1
    assert "scan already in progress" in capsys.readouterr().err


async def test_cmd_select_makes_a_panel_active_through_the_daemon(monkeypatch, capsys) -> None:
    client = _use_client(monkeypatch, _FakeClient())
    client.select_device = lambda mac: (client.calls.append(("select", mac)) or {"success": True, "selected": mac})
    rc = await cli_commands.cmd_select(_parse("select", "--mac", "AA:BB"))
    assert rc == 0
    assert ("select", "AA:BB") in client.calls
    assert "active panel: AA:BB" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        await cli_commands.cmd_select(_parse("select"))
    assert exc.value.code == 2


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

    monkeypatch.setattr(cli_device_verbs, "_capabilities", lambda a, m: Caps())

    async def fake_resolve(args):
        return D(), "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(cli_device_verbs, "_resolve_device", fake_resolve)
    rc = await cli_device_verbs.cmd_capabilities(_parse("capabilities"))
    assert rc == 0
    assert "quirk-a; quirk-b" in capsys.readouterr().out


# ── cmd_set_radio ────────────────────────────────────────────────────────


async def test_cmd_set_radio_rejects_when_no_fm_capability(monkeypatch) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_fm = False
    monkeypatch.setattr(cli_device_verbs, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_device_verbs, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs.cmd_set_radio(_parse("set-radio", "875", "--mac", "AA:BB"))
    assert exc.value.code == 1
    fake.disconnect.assert_not_awaited()  # the daemon keeps the link


async def test_cmd_set_radio_happy_path(monkeypatch, capsys) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_fm = True
    monkeypatch.setattr(cli_device_verbs, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_device_verbs, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_device_verbs.cmd_set_radio(_parse("set-radio", "875", "--mac", "AA:BB"))
    assert rc == 0
    fake.radio.set_radio_frequency.assert_awaited_once_with(875)
    assert "87.5 MHz" in capsys.readouterr().out


# ── cmd_set_alarm ────────────────────────────────────────────────────────


async def test_cmd_set_alarm_rejects_bad_time_format() -> None:
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs.cmd_set_alarm(
            _parse("set-alarm", "not-a-time", "--mac", "AA:BB")
        )
    assert exc.value.code == 2


async def test_cmd_set_alarm_rejects_when_no_alarm_capability(monkeypatch) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_alarm = False
    monkeypatch.setattr(cli_device_verbs, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_device_verbs, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs.cmd_set_alarm(_parse("set-alarm", "07:30", "--mac", "AA:BB"))
    assert exc.value.code == 1


async def test_cmd_set_alarm_happy_path(monkeypatch, capsys) -> None:
    fake = FakeDivoom()
    fake.capabilities.has_alarm = True
    monkeypatch.setattr(cli_device_verbs, "_capabilities", lambda a, m: fake.capabilities)
    monkeypatch.setattr(
        cli_device_verbs, "_resolve_device", AsyncMock(return_value=(fake, "AA:BB"))
    )
    rc = await cli_device_verbs.cmd_set_alarm(_parse("set-alarm", "07:30", "--mac", "AA:BB"))
    assert rc == 0
    fake.alarm.set_alarm.assert_awaited_once_with(0, 1, 7, 30, 127, 0, 0)
    assert "07:30" in capsys.readouterr().out


# ── cmd_set_volume / cmd_set_brightness ────────────────────────────────────
#
# Rewritten 2026-09-25 (L5 item 2): these two verbs now hand the device command
# to `divoomd` and the process IS the native verb. The subjects are unchanged —
# the right argv reaches the right binary, and a bad value is refused before
# anything is resolved — but the instrument changed from a fake device proxy to
# a fake execv, because there is no Python device call left to fake. The
# end-to-end proof that the native verb really performs the call, against a real
# daemon, is tests/test_cli_device_verbs.py; the wire assertions are in
# divoomd/src/verbs_tests.rs.


def _recorded_exec(monkeypatch) -> list:
    """Capture the exec instead of performing it, and record the argv.

    Patching `os.execv` and `cli_commands._divoomd_binary` — the definition
    sites — is enough for every device verb. They are called module-qualified on
    purpose (see divoom_lib/cli_device_verbs.py), so there is exactly one place
    each can be replaced.
    """
    calls: list = []

    def _execv(path, argv):
        calls.append((path, argv))
        raise SystemExit(0)  # execv never returns

    monkeypatch.setattr(os, "execv", _execv)  # the delegate execs in this module
    return calls


async def test_cmd_set_volume_hands_off_to_the_native_verb(monkeypatch) -> None:
    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB"))
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    calls = _recorded_exec(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_set_volume(_parse("set-volume", "7", "--mac", "AA:BB"))

    assert calls == [("/opt/divoomd", ["/opt/divoomd", "set-volume", "7", "--mac", "AA:BB"])]


async def test_cmd_set_brightness_hands_off_with_json_when_asked(monkeypatch) -> None:
    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB"))
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    calls = _recorded_exec(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_set_brightness(
            _parse("set-brightness", "50", "--mac", "AA:BB", "--json")
        )

    assert calls == [
        ("/opt/divoomd", ["/opt/divoomd", "set-brightness", "50", "--mac", "AA:BB", "--json"])
    ]


@pytest.mark.parametrize("command,value,message", [
    ("cmd_set_volume", "16", "volume must be 0..15"),
    ("cmd_set_volume", "-1", "volume must be 0..15"),
    ("cmd_set_brightness", "101", "brightness must be 0..100"),
    ("cmd_set_brightness", "-1", "brightness must be 0..100"),
])
async def test_an_out_of_range_value_is_refused_before_anything_is_resolved(
    monkeypatch, capsys, command, value, message
) -> None:
    """The ordering, which is why the check stayed in Python at all.

    Resolving a target can scan and can CONNECT. A user who typed 16 must be
    told so without the CLI reaching for the radio first, so the resolution mock
    is asserted to be untouched — and the exec, which is the thing that would
    have carried the bad value to the device.
    """
    resolve = AsyncMock(return_value="AA:BB")
    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", resolve)
    calls = _recorded_exec(monkeypatch)

    verb, flag = command.removeprefix("cmd_").split("_", 1)
    with pytest.raises(SystemExit) as exc:
        await getattr(cli_device_verbs, command)(_parse(f"{verb}-{flag}", value, "--mac", "AA:BB"))

    assert exc.value.code == 2
    # The text goes to stderr; SystemExit only carries the code, which is why
    # this reads the stream rather than the exception.
    assert message in capsys.readouterr().err, "the message must still name the range"
    resolve.assert_not_awaited()
    assert calls == []


# ── cmd_push_image / cmd_push_gif ───────────────────────────────────────────


async def test_cmd_push_image_file_not_found(tmp_path) -> None:
    missing = tmp_path / "missing.png"
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs.cmd_push_image(_parse("push-image", str(missing)))
    assert exc.value.code == 2


async def test_cmd_push_image_hands_the_path_to_the_native_verb(monkeypatch, tmp_path) -> None:
    # The PATH, not pixels: the daemon sizes the image to the panel, which is
    # why this verb deliberately does not go through the MCP show_image tool
    # (that one resizes to 16x16 in the client).
    f = tmp_path / "pic.png"
    f.write_bytes(b"fake-png-bytes")
    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB"))
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    calls = _recorded_exec(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_push_image(_parse("push-image", str(f), "--mac", "AA:BB"))

    assert calls == [
        ("/opt/divoomd", ["/opt/divoomd", "push-image", str(f), "--mac", "AA:BB"])
    ]


async def test_cmd_push_gif_file_not_found(tmp_path) -> None:
    missing = tmp_path / "missing.gif"
    with pytest.raises(SystemExit) as exc:
        await cli_device_verbs.cmd_push_gif(_parse("push-gif", str(missing)))
    assert exc.value.code == 2


async def test_cmd_push_gif_keeps_its_name_and_the_same_call(monkeypatch, tmp_path) -> None:
    # Scripts call `push-gif`, so the name stays; it is the same verb with the
    # same argument, because it always was — both pushed the file by path.
    f = tmp_path / "anim.gif"
    f.write_bytes(b"fake-gif-bytes")
    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB"))
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    calls = _recorded_exec(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_push_gif(_parse("push-gif", str(f), "--mac", "AA:BB"))

    assert calls == [
        ("/opt/divoomd", ["/opt/divoomd", "push-gif", str(f), "--mac", "AA:BB"])
    ]
