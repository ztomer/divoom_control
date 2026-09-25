"""Unit coverage for the device-verb HANDLERS in `divoom_lib/cli_device_verbs.py`.

Split out of `test_cli_commands_coverage.py` on 2026-09-25 by the 500-line cap.
These are the same tests that lived there, in the same place in the argument:
what the handler hands to `divoomd`, and what it refuses to hand over.

The split is by KIND, not by accident:

* `tests/test_cli_device_verbs.py` — the END TO END. The real entry point, a real
  BLE-free daemon, a real JSON-RPC or device call. Slow, and the only thing that
  proves a user's command works.
* this file — the UNITS. The handlers with `os.execv` instrumented, so what is
  asserted is the boundary: which binary, which argv, which socket, and which
  refusals happen BEFORE the handoff rather than after it.
* `tests/test_cli_commands_coverage.py` — the shared helpers and the commands
  that are not device verbs (scan, select, the daemon-client refusal).

The wire assertions for the verbs themselves are in
`divoomd/src/verbs_tests.rs`, against a real socket with the request read back.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from divoom_lib import cli_commands
from divoom_lib import cli_device_verbs
from tests.support.cli_common import _parse


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


# ── cmd_set_radio / cmd_set_alarm / cmd_set_temperature ───────────────────
#
# These three moved to divoomd as well, and the interesting part is what stayed
# behind: the CAPABILITY check. The table that knows which panels have a radio
# or an alarm is Python's alone — the daemon has no capability table — so the
# refusal is client policy, and it is asserted here on the real code path with
# the exec instrumented, to prove the refusal happens BEFORE the handoff. After
# the handoff there would be no point in it: the call would already be on its way
# to a panel that cannot do it.


def _capabilities_stub(monkeypatch, *, has_fm=True, has_alarm=True, has_weather=True):
    caps = SimpleNamespace(has_fm=has_fm, has_alarm=has_alarm, has_weather=has_weather)
    monkeypatch.setattr(cli_device_verbs, "_capabilities", lambda a, m: caps)
    return caps


def _ready_to_hand_off(monkeypatch, mac="AA:BB"):
    """A resolvable panel, a resolvable binary, and a recorded exec."""
    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", AsyncMock(return_value=mac))
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    return _recorded_exec(monkeypatch)


@pytest.mark.parametrize("command,argv,flag", [
    ("cmd_set_radio", ["set-radio", "875", "--mac", "AA:BB"], "has_fm"),
    ("cmd_set_alarm", ["set-alarm", "07:30", "--mac", "AA:BB"], "has_alarm"),
    ("cmd_set_temperature",
     ["set-temperature", "18", "--weather", "clear", "--mac", "AA:BB"], "has_weather"),
])
async def test_a_panel_without_the_feature_is_refused_before_the_handoff(
    monkeypatch, capsys, command, argv, flag
) -> None:
    _capabilities_stub(monkeypatch, **{flag: False})
    calls = _ready_to_hand_off(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        await getattr(cli_device_verbs, command)(_parse(*argv))

    assert exc.value.code == 1
    assert calls == [], f"{command} handed off to divoomd for a panel that cannot do it"
    # `_err` writes to stderr and SystemExit carries only the code, so the text
    # comes from the stream.
    err = capsys.readouterr().err
    assert "AA:BB" in err, f"the message must name the panel: {err}"
    assert flag in err, f"and say which capability is missing: {err}"


async def test_a_capable_panel_hands_off_to_divoomd(monkeypatch) -> None:
    _capabilities_stub(monkeypatch)
    calls = _ready_to_hand_off(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_set_radio(_parse("set-radio", "911", "--mac", "AA:BB"))

    assert calls == [
        ("/opt/divoomd", ["/opt/divoomd", "set-radio", "911", "--mac", "AA:BB"])
    ]


async def test_an_alarm_is_handed_over_with_its_time_intact(monkeypatch) -> None:
    """`HH:MM` crosses as written: splitting it into hour and minute is the
    native verb's business, and a script's argument should come back quoted in
    any error it causes."""
    _capabilities_stub(monkeypatch)
    calls = _ready_to_hand_off(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_set_alarm(_parse("set-alarm", "07:30", "--mac", "AA:BB"))

    assert calls == [
        ("/opt/divoomd", ["/opt/divoomd", "set-alarm", "07:30", "--mac", "AA:BB"])
    ]


async def test_the_weather_verb_passes_the_icon_name_not_its_number(monkeypatch) -> None:
    """The NAME crosses, because the name->wire table moved to divoomd with the
    rest of the weather mapping. Passing `1` here would freeze a second copy of
    that table in Python, which is what check_weather_parity.py exists to stop.

    The CLI takes the icon as `--weather`; the native verb takes it positionally,
    like every other value it accepts. That is a grammar choice inside divoomd,
    and translating it here leaves both surfaces' own conventions intact.
    """
    _capabilities_stub(monkeypatch)
    calls = _ready_to_hand_off(monkeypatch)

    with pytest.raises(SystemExit):
        await cli_device_verbs.cmd_set_temperature(
            _parse("set-temperature", "18", "--weather", "clear", "--mac", "AA:BB")
        )

    assert calls == [
        ("/opt/divoomd",
         ["/opt/divoomd", "set-temperature", "18", "clear", "--mac", "AA:BB"])
    ]
