"""
R14 §1 — Weather facade.

Sets the temperature + weather-icon on a Divoom device's weather
channel (SPP_SET_TEMP_WEATHER, command 0x5F).

Wire format (from decompiled ``SppProc$CMD_TYPE.java``):

    [0x5F, temp_byte, weather_type]
    temp_byte       = (celsius + 256) & 0xFF if celsius < 0 else celsius
    weather_type    = WeatherType (1=clear, 3=cloudy, 5=storm, 6=rain, 8=snow, 9=fog)

Valid temperature range: -127..128 (the device uses a signed byte
in two's complement). The 0x5F command has been verified against the
decompiled APK (``CmdManager.java``); the weather type values mirror
the ``W1.p`` enum in the APK and ``divoom_lib.models.WeatherType``.

The legacy ``TempWeatherCommand`` in ``divoom_lib/system/temp_weather.py``
is preserved as a thin shim that re-exports to this class so the
existing test in ``tests/test_temp_weather_functions.py`` still passes
— but new code should use ``Divoom.weather`` directly.

Usage::

    await divoom.weather.set(25, WeatherType.Clear)
    await divoom.weather.set_temperature(-5)
    await divoom.weather.set_weather(WeatherType.Snow)
"""
from __future__ import annotations

import logging
from typing import Optional

from divoom_lib.models import COMMANDS, WeatherType
from divoom_lib.sender_protocol import CommandSender

logger = logging.getLogger(__name__)


class Weather:
    """Temperature + weather-icon control for the device's weather
    channel. Bound to the Divoom facade as ``divoom.weather`` (R14 §1)."""

    MIN_TEMP = -127
    MAX_TEMP = 128

    def __init__(self, divoom: CommandSender) -> None:
        self._divoom = divoom
        self._temperature: int = 0
        self._weather_type: int = WeatherType.Clear

    # ── Properties ────────────────────────────────────────────────────

    @property
    def temperature(self) -> int:
        return self._temperature

    @temperature.setter
    def temperature(self, value: int) -> None:
        self._temperature = int(value)

    @property
    def weather_type(self) -> int:
        return self._weather_type

    @weather_type.setter
    def weather_type(self, value: int) -> None:
        self._weather_type = int(value)

    # ── Public API ────────────────────────────────────────────────────

    async def set(self, temperature: int, weather_type: int) -> bool:
        """Send the device's current temperature and weather icon in
        one call. Returns True on successful transmission."""
        if not self.MIN_TEMP <= int(temperature) <= self.MAX_TEMP:
            raise ValueError(
                f"temperature {temperature} out of range "
                f"[{self.MIN_TEMP}..{self.MAX_TEMP}]"
            )
        encoded = self._encode_temperature(int(temperature))
        wt = int(weather_type)
        self._temperature = int(temperature)
        self._weather_type = wt
        logger.info(
            f"Sending weather: temp={temperature}°C (0x{encoded:02X}) "
            f"weather_type={wt} (0x5F)..."
        )
        return await self._divoom.send_command(
            COMMANDS["set temp"], [encoded, wt]
        )

    async def set_temperature(self, temperature: int) -> bool:
        """Update only the temperature (preserves the current weather type)."""
        return await self.set(temperature, self._weather_type)

    async def set_weather(self, weather_type: int) -> bool:
        """Update only the weather icon (preserves the current temperature)."""
        return await self.set(self._temperature, weather_type)

    # ── Internal ──────────────────────────────────────────────────────

    @staticmethod
    def _encode_temperature(celsius: int) -> int:
        """Encode a temperature as a single byte. -127..-1 → 129..255
        (256 + celsius). 0..128 → 0..128."""
        return (256 + celsius) & 0xFF if celsius < 0 else celsius & 0xFF


# ── Backwards-compatibility shim ──────────────────────────────────────
# The old TempWeatherCommand in temp_weather.py had two problems:
#  (1) it wasn't wired to the Divoom facade, and
#  (2) it called ``self._divoom_instance.number2HexString()`` which
#      is not a method on Divoom (it lives in utils/converters.py).
# This thin shim preserves the old class so any external code that
# imported it still works — it now delegates to the new ``Weather``
# class which has the correct wire format.


class _LegacyTempWeatherCommandShim:
    """Deprecated. Use ``Divoom.weather`` (R14 §1) instead.

    This shim preserves the old ``TempWeatherCommand`` API (setters
    for ``temperature`` / ``weather``, an ``update_temp_weather()``
    coroutine). All it does is forward to the new ``Weather`` class.
    """

    def __init__(self, divoom_instance, opts: Optional[dict] = None) -> None:
        self._divoom_instance = divoom_instance
        self._inner = Weather(divoom_instance)
        if opts:
            if "temperature" in opts:
                self._inner.temperature = opts["temperature"]
            if "weather" in opts:
                self._inner.weather_type = opts["weather"]

    @property
    def temperature(self) -> int:
        return self._inner.temperature

    @temperature.setter
    def temperature(self, value: int) -> None:
        self._inner.temperature = value

    @property
    def weather(self) -> int:
        return self._inner.weather_type

    @weather.setter
    def weather(self, value: int) -> None:
        self._inner.weather_type = value

    async def update_temp_weather(self) -> None:
        await self._inner.set(self._inner.temperature, self._inner.weather_type)
