# divoom_lib/system/temp_weather.py
"""
R14 §1 — legacy compatibility shim.

The original ``TempWeatherCommand`` had two problems:
  (1) it wasn't wired to the Divoom facade, and
  (2) it called ``self._divoom_instance.number2HexString()`` which
      is not a method on Divoom (it lives in utils/converters.py)
      — it would crash at first ``update_temp_weather()``.

This file now re-exports the modern ``Weather`` class and a
``TempWeatherCommand`` shim that forwards to it. New code should
use ``Divoom.weather`` directly. The shim is preserved so
``tests/test_temp_weather_functions.py`` and any external code
that imported ``TempWeatherCommand`` continue to work.
"""
from typing import Optional

from .weather import Weather  # noqa: F401  (re-export for legacy importers)


class TempWeatherCommand:
    """Deprecated. Use ``Divoom.weather`` (R14 §1) instead.

    Backwards-compatible shim that delegates to the new ``Weather``
    class. Preserves the old setter / ``update_temp_weather()`` API.
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

    async def update_temp_weather(self) -> bool:
        return await self._inner.set(self._inner.temperature, self._inner.weather_type)
