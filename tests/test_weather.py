"""
R14 §1 — tests for the Weather facade (``divoom.weather``).

These tests run in-process; no BLE hardware required. The Divoom
class is mocked at the ``send_command`` boundary.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from divoom_lib.models import COMMANDS, WeatherType
from divoom_lib.system.weather import Weather


# ── Encoding ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("celsius,expected_byte", [
    (0,    0x00),
    (1,    0x01),
    (25,   0x19),
    (127,  0x7F),
    (128,  0x80),  # 128 is the upper edge — the device accepts it.
    (-1,   0xFF),  # 256 + (-1) = 255
    (-10,  0xF6),  # 256 + (-10) = 246
    (-127, 0x81),  # 256 + (-127) = 129
])
def test_encode_temperature(celsius: int, expected_byte: int) -> None:
    assert Weather._encode_temperature(celsius) == expected_byte


def test_encode_temperature_below_min_is_not_special_cased() -> None:
    """Validation lives in ``set()``; the static encoder is just
    arithmetic and does not raise. This documents the behavior."""
    # -128 would encode to 128 (0x80), but ``set()`` should reject it.
    assert Weather._encode_temperature(-128) == 128


# ── Public API ────────────────────────────────────────────────────────


def _make_weather() -> tuple[Weather, MagicMock]:
    divoom = MagicMock()
    divoom.logger = MagicMock()
    divoom.send_command = AsyncMock(return_value=True)
    return Weather(divoom), divoom


@pytest.mark.asyncio
async def test_set_sends_correct_wire_bytes_positive() -> None:
    w, divoom = _make_weather()
    ok = await w.set(25, WeatherType.Clear)
    assert ok is True
    divoom.send_command.assert_called_once_with(
        COMMANDS["set temp"],   # 0x5F
        [0x19, WeatherType.Clear],
    )


@pytest.mark.asyncio
async def test_set_sends_correct_wire_bytes_negative() -> None:
    w, divoom = _make_weather()
    await w.set(-10, WeatherType.Rain)
    divoom.send_command.assert_called_once_with(
        COMMANDS["set temp"],
        [0xF6, WeatherType.Rain],   # 256 + (-10) = 246
    )


@pytest.mark.asyncio
async def test_set_sends_correct_wire_bytes_zero() -> None:
    w, divoom = _make_weather()
    await w.set(0, WeatherType.CloudySky)
    divoom.send_command.assert_called_once_with(
        COMMANDS["set temp"],
        [0x00, WeatherType.CloudySky],
    )


@pytest.mark.asyncio
async def test_set_rejects_out_of_range_high() -> None:
    w, _ = _make_weather()
    with pytest.raises(ValueError):
        await w.set(129, WeatherType.Clear)


@pytest.mark.asyncio
async def test_set_rejects_out_of_range_low() -> None:
    w, _ = _make_weather()
    with pytest.raises(ValueError):
        await w.set(-128, WeatherType.Clear)


@pytest.mark.asyncio
async def test_set_temperature_preserves_weather_type() -> None:
    """``set_temperature()`` updates only the temperature; the weather
    type is kept from the last ``set()`` call (or the default)."""
    w, divoom = _make_weather()
    await w.set(20, WeatherType.Snow)         # sets type=Snow
    divoom.send_command.reset_mock()
    await w.set_temperature(15)                # keeps type=Snow
    divoom.send_command.assert_called_once_with(
        COMMANDS["set temp"],
        [0x0F, WeatherType.Snow],
    )


@pytest.mark.asyncio
async def test_set_weather_preserves_temperature() -> None:
    w, divoom = _make_weather()
    await w.set(20, WeatherType.Snow)
    divoom.send_command.reset_mock()
    await w.set_weather(WeatherType.Fog)
    divoom.send_command.assert_called_once_with(
        COMMANDS["set temp"],
        [0x14, WeatherType.Fog],
    )


@pytest.mark.asyncio
async def test_set_returns_send_command_result() -> None:
    w, divoom = _make_weather()
    divoom.send_command = AsyncMock(return_value=False)
    ok = await w.set(20, WeatherType.Clear)
    assert ok is False


@pytest.mark.asyncio
async def test_set_updates_internal_state() -> None:
    w, _ = _make_weather()
    await w.set(7, WeatherType.Thunderstorm)
    assert w.temperature == 7
    assert w.weather_type == WeatherType.Thunderstorm


# ── Legacy shim ───────────────────────────────────────────────────────


def test_temp_weather_command_shim_preserves_state() -> None:
    """``TempWeatherCommand`` (the old class) still works via the shim."""
    from divoom_lib.system.temp_weather import TempWeatherCommand
    divoom = MagicMock()
    divoom.logger = MagicMock()
    divoom.send_command = AsyncMock(return_value=True)
    shim = TempWeatherCommand(divoom, opts={"temperature": 10, "weather": WeatherType.Snow})
    assert shim.temperature == 10
    assert shim.weather == WeatherType.Snow


# ── Divoom facade wiring ──────────────────────────────────────────────


def test_divoom_weather_attribute_is_weather_instance() -> None:
    """``Divoom().weather`` is a ``Weather`` instance — R14 §1 wiring."""
    from divoom_lib import Divoom
    d = Divoom(mac="AA:BB:CC:DD:EE:FF", device_name="fake")
    assert isinstance(d.weather, Weather)
