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
from types import SimpleNamespace
import subprocess
import sys
from pathlib import Path

import pytest

from divoom_lib import cli as cli_module
from divoom_lib import cli_commands
from divoom_lib import cli_device_verbs  # handlers split out of cli.py; patch internals here
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
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
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
        capture_output=True, text=True, env=env, timeout=15, stdin=subprocess.DEVNULL,
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
        capture_output=True, text=True, env=env, timeout=15, stdin=subprocess.DEVNULL,
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


# ── `capabilities` command: the DAEMON's description ───────────────────
#
# P3.4: what a panel IS comes from the daemon -- its model, its size, its
# chassis, the vendor app's features for it and the screens it offers. The
# CLI used to print a table of its own, which is where the "a Ditoo has an FM
# radio" story came from.


class _FakeDaemonClient:
    """The daemon as the CLI sees it: one panel, described."""

    def device_status(self, mac=None):
        return {
            "success": True,
            "connected": True,
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "PIXOO_MAX",
            "model_source": "name",
            "width": 32,
            "height": 32,
            "chassis": {"family": "pixoo", "w_mm": 200.0, "h_mm": 200.0, "screen_mm": 158.0},
            "features": {"speaker": False, "sd_card": False, "radio": False, "mic": True,
                         "clock_style": "ClockNormal32"},
            "screens": ["design", "alarm", "weather"],
        }


@pytest.mark.asyncio
async def test_cmd_capabilities_prints_the_daemons_description(monkeypatch, capsys) -> None:
    async def fake_resolve(args):
        return "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", fake_resolve)
    monkeypatch.setattr(cli_commands, "_daemon_client", lambda *a, **k: _FakeDaemonClient())
    ns = cli_module.build_parser().parse_args(["capabilities", "--mac", "AA:BB:CC:DD:EE:FF"])
    rc = await cli_module.cmd_capabilities(ns)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PIXOO_MAX" in out, out
    assert "32x32" in out, out
    assert "pixoo" in out, out


@pytest.mark.asyncio
async def test_cmd_capabilities_json_output(monkeypatch, capsys) -> None:
    async def fake_resolve(args):
        return "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(cli_device_verbs, "resolve_target_mac", fake_resolve)
    monkeypatch.setattr(cli_commands, "_daemon_client", lambda *a, **k: _FakeDaemonClient())
    ns = cli_module.build_parser().parse_args(["capabilities", "--mac", "AA:BB:CC:DD:EE:FF", "--json"])
    rc = await cli_module.cmd_capabilities(ns)
    assert rc == 0
    captured = capsys.readouterr()
    obj = json.loads(captured.out)
    assert obj["model"] == "PIXOO_MAX"
    assert obj["width"] == 32
    assert obj["features"]["radio"] is False
    assert obj["screens"] == ["design", "alarm", "weather"]


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


async def test_cmd_set_temperature_hands_the_icon_name_to_divoomd(monkeypatch) -> None:
    """Rewritten 2026-09-25 (L5): the weather push is a divoomd verb now.

    The name crosses rather than the wire value, because the name->id table
    moved into `divoomd/src/mcp_tools.rs` with the rest of the weather mapping.
    Passing `1` here would leave a second copy of that table in Python, which is
    the drift `tools/check_weather_parity.py` was written to catch.
    """
    execs: list = []

    def _execv(path, argv):
        execs.append((path, argv))
        raise SystemExit(0)

    monkeypatch.setattr(
        cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB:CC:DD:EE:FF")
    )
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    monkeypatch.setattr(os, "execv", _execv)

    p = cli_module.build_parser()
    ns = p.parse_args(["set-temperature", "18", "--mac", "AA:BB:CC:DD:EE:FF", "--weather", "clear"])
    with pytest.raises(SystemExit):
        await cli_module.cmd_set_temperature(ns)

    assert execs == [
        ("/opt/divoomd",
         ["/opt/divoomd", "set-temperature", "18", "clear", "--mac", "AA:BB:CC:DD:EE:FF"])
    ]


async def test_cmd_set_temperature_has_no_capability_gate_of_its_own(monkeypatch) -> None:
    """P3.4: the CLI carries no per-model table any more.

    The gate it used to have read a table whose `has_weather` was true of
    every row -- a gate that could not fail. The panel's abilities are the
    daemon's, and the daemon does the refusing.
    """
    monkeypatch.setattr(
        cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB:CC:DD:EE:FF")
    )
    monkeypatch.setattr(cli_commands, "_divoomd_binary", lambda: "/opt/divoomd")
    assert not hasattr(cli_device_verbs, "_capabilities"), (
        "the CLI still has a capability table of its own"
    )


async def test_cmd_set_temperature_rejects_out_of_range(monkeypatch) -> None:
    """Before a panel is resolved, and so before any connection is opened."""
    monkeypatch.setattr(
        cli_device_verbs, "resolve_target_mac", AsyncMock(return_value="AA:BB:CC:DD:EE:FF")
    )
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
