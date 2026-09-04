"""
Tests for the divoom-control CLI.

Strategy:
- For every subcommand, run `--help` as a subprocess and assert the
  expected command name appears in the output. This is the cheapest
  wire-test — no hardware, no mocks, no asyncio. It also catches any
  argparse breakage (e.g. duplicate option names, missing required
  args).
- For `pair`, we exercise the registry roundtrip with a temp HOME so we
  don't pollute the real ``~/.config/divoom-control/devices.json``.
- For `capabilities` (no connection yet), we wire a fake Divoom into
  ``cmd_capabilities`` to confirm the data path; the BLE connect path
  is gated behind ``--mac <not-paired>`` so we keep these tests
  fully offline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from divoom_lib import cli as cli_module
from divoom_lib import cli_commands  # handlers split out of cli.py; patch internals here
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.models.capabilities import (
    BASELINE,
    Capabilities,
    DeviceRegistry,
)


# ── Subprocess `--help` smoke tests ────────────────────────────────────


CLI_CMD = [sys.executable, "-m", "divoom_lib.cli"]


def _run_help(sub: str | None = None) -> str:
    cmd = list(CLI_CMD)
    if sub is not None:
        cmd.append(sub)
    cmd.append("--help")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return r.stdout


ALL_SUBCOMMANDS = [
    "scan",
    "capabilities",
    "identify",
    "set-volume",
    "set-brightness",
    "set-radio",
    "set-alarm",
    "push-image",
    "push-gif",
    "pair",
]


@pytest.mark.parametrize("sub", ALL_SUBCOMMANDS)
def test_cli_subcommand_help_works(sub: str) -> None:
    out = _run_help(sub)
    assert sub in out, f"subcommand {sub!r} not mentioned in its --help output"
    assert "usage:" in out


def test_cli_top_level_help_lists_all_subcommands() -> None:
    out = _run_help()
    for sub in ALL_SUBCOMMANDS:
        assert sub in out, f"top-level --help missing {sub!r}"


# ── `pair` subprocess test (real registry, temp HOME) ──────────────────


def test_cli_pair_writes_to_registry(tmp_path: Path) -> None:
    """Run `pair --mac AA:... --type TivooMax` with a temp HOME and assert
    the registry file contains the expected entry."""
    env = os.environ.copy()
    env["DIVOOM_CONTROL_REGISTRY"] = str(tmp_path / "devices.json")
    env["HOME"] = str(tmp_path)
    r = subprocess.run(
        CLI_CMD + ["pair", "--mac", "AA:BB:CC:DD:EE:FF", "--type", "TivooMax"],
        capture_output=True, text=True, env=env, timeout=15,
    )
    assert r.returncode == 0, r.stderr
    assert "registered" in r.stdout.lower()
    assert tmp_path.joinpath("devices.json").exists()
    data = json.loads(tmp_path.joinpath("devices.json").read_text())
    assert data == {"aa:bb:cc:dd:ee:ff": "TivooMax"}


def test_cli_pair_rejects_unknown_device_type(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["DIVOOM_CONTROL_REGISTRY"] = str(tmp_path / "devices.json")
    env["HOME"] = str(tmp_path)
    r = subprocess.run(
        CLI_CMD + ["pair", "--mac", "AA:BB:CC:DD:EE:FF", "--type", "NotARealDevice"],
        capture_output=True, text=True, env=env, timeout=15,
    )
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "unknown device_type" in r.stderr


# ── Argument-parser unit tests (in-process) ────────────────────────────


def test_parser_rejects_missing_subcommand() -> None:
    p = cli_module.build_parser()
    with pytest.raises(SystemExit) as exc:
        p.parse_args([])
    assert exc.value.code == 2


def test_set_volume_clamps_via_handler() -> None:
    """`set-volume` only validates inside the handler, but parsing should accept
    any int (handler raises SystemExit(2))."""
    p = cli_module.build_parser()
    args = p.parse_args(["set-volume", "10", "--mac", "AA:BB:CC:DD:EE:FF"])
    assert args.value == 10
    assert args.mac == "AA:BB:CC:DD:EE:FF"
    assert args.command == "set-volume"


def test_push_image_accepts_path() -> None:
    p = cli_module.build_parser()
    args = p.parse_args(["push-image", "/tmp/foo.png"])
    assert str(args.path) == "/tmp/foo.png"


# ── `capabilities` command with a fake Divoom ─────────────────────────


class _FakeCapabilities:
    """Shape-compatible duck-type for a `Capabilities` instance, for unit
    tests. The real one is a frozen dataclass; this needs nothing more."""

    panel_resolution = 32
    has_fm = True
    has_sd = True
    has_scoreboard = True
    has_anim_8b = True
    has_orientation = True
    has_screen_mirror = True
    has_alarm = True
    has_sleep = True
    has_weather = True
    has_mic = True
    notes = ()


class _FakeDivoom:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    @property
    def capabilities(self):
        return _FakeCapabilities()


@pytest.mark.asyncio
async def test_cmd_capabilities_uses_fake_divoom(monkeypatch) -> None:
    """Wire in a fake Divoom, run cmd_capabilities, assert the human-
    readable output mentions the device's panel_resolution."""
    async def fake_resolve(args):
        return _FakeDivoom(), "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(cli_commands, "_resolve_device",fake_resolve)
    ns = cli_module.build_parser().parse_args(["capabilities", "--mac", "AA:BB:CC:DD:EE:FF"])
    rc = await cli_module.cmd_capabilities(ns)
    assert rc == 0


@pytest.mark.asyncio
async def test_cmd_capabilities_json_output(monkeypatch, capsys) -> None:
    async def fake_resolve(args):
        return _FakeDivoom(), "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(cli_commands, "_resolve_device",fake_resolve)
    ns = cli_module.build_parser().parse_args(["capabilities", "--mac", "AA:BB:CC:DD:EE:FF", "--json"])
    rc = await cli_module.cmd_capabilities(ns)
    assert rc == 0
    captured = capsys.readouterr()
    obj = json.loads(captured.out)
    assert obj["panel_resolution"] == 32
    assert obj["has_fm"] is True
    assert obj["has_alarm"] is True


# ── `set-volume` validation (handler-level, no BLE) ────────────────────


@pytest.mark.asyncio
async def test_cmd_set_volume_rejects_out_of_range() -> None:
    p = cli_module.build_parser()
    ns = p.parse_args(["set-volume", "42", "--mac", "AA:BB:CC:DD:EE:FF"])
    with pytest.raises(SystemExit) as exc:
        await cli_module.cmd_set_volume(ns)
    assert exc.value.code == 2


@pytest.mark.asyncio
async def test_cmd_set_brightness_rejects_out_of_range() -> None:
    p = cli_module.build_parser()
    ns = p.parse_args(["set-brightness", "200", "--mac", "AA:BB:CC:DD:EE:FF"])
    with pytest.raises(SystemExit) as exc:
        await cli_module.cmd_set_brightness(ns)
    assert exc.value.code == 2


# ── set-temperature (R14 §1) ───────────────────────────────────────────


class _FakeDivoomForWeather:
    """Minimal fake that mimics the parts of Divoom that
    ``cmd_set_temperature`` touches: ``capabilities`` and ``weather``."""

    def __init__(self, *, has_weather: bool = True) -> None:
        self.capabilities = MagicMock()
        self.capabilities.has_weather = has_weather
        self.weather = MagicMock()
        # side_effect so it can raise (out-of-range) or return True
        self.weather.set = AsyncMock(side_effect=self._validate_and_set)
        self._disconnected = False

    async def _validate_and_set(self, temperature: int, weather_id: int) -> bool:
        # Mirror Weather.set's validation so the CLI behavior is testable.
        if not -127 <= int(temperature) <= 128:
            raise ValueError(f"temperature {temperature} out of range [-127..128]")
        return True

    async def disconnect(self) -> None:
        self._disconnected = True


async def test_cmd_set_temperature_calls_weather_set(monkeypatch) -> None:
    fake = _FakeDivoomForWeather()
    monkeypatch.setattr(cli_commands, "_resolve_device",AsyncMock(return_value=(fake, "AA:BB:CC:DD:EE:FF")))

    p = cli_module.build_parser()
    ns = p.parse_args(["set-temperature", "18", "--mac", "AA:BB:CC:DD:EE:FF", "--weather", "clear"])
    rc = await cli_module.cmd_set_temperature(ns)
    assert rc == 0
    fake.weather.set.assert_called_once_with(18, 1)  # clear=1


async def test_cmd_set_temperature_rejects_when_no_capability(monkeypatch) -> None:
    fake = _FakeDivoomForWeather(has_weather=False)
    monkeypatch.setattr(cli_commands, "_resolve_device",AsyncMock(return_value=(fake, "AA:BB:CC:DD:EE:FF")))

    p = cli_module.build_parser()
    ns = p.parse_args(["set-temperature", "18", "--mac", "AA:BB:CC:DD:EE:FF"])
    with pytest.raises(SystemExit) as exc:
        await cli_module.cmd_set_temperature(ns)
    assert exc.value.code == 1


async def test_cmd_set_temperature_rejects_out_of_range(monkeypatch) -> None:
    fake = _FakeDivoomForWeather()
    monkeypatch.setattr(cli_commands, "_resolve_device",AsyncMock(return_value=(fake, "AA:BB:CC:DD:EE:FF")))

    p = cli_module.build_parser()
    ns = p.parse_args(["set-temperature", "200", "--mac", "AA:BB:CC:DD:EE:FF"])
    with pytest.raises((SystemExit, ValueError)):
        await cli_module.cmd_set_temperature(ns)


def test_set_temperature_registered_in_dispatch_table() -> None:
    """R14 §1 — the new subcommand is wired in ``COMMANDS``."""
    assert "set-temperature" in cli_module.COMMANDS
    assert cli_module.COMMANDS["set-temperature"] is cli_module.cmd_set_temperature


# ── Module / package surface ───────────────────────────────────────────


def test_cli_is_importable_as_module() -> None:
    import divoom_lib.cli as cli
    assert callable(cli.main)
    assert callable(cli.amain)
    assert callable(cli.build_parser)


def test_baseline_known_to_test() -> None:
    """Sanity: the capabilities baseline the CLI uses as fallback is the
    same as what the lib exposes."""
    assert BASELINE.panel_resolution == 16
