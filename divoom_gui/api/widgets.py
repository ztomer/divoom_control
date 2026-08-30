"""WidgetsApi — weather/stocks/sysmon/cover-art (REVIEW §1.2).

Extracts the live widget surface.
"""
from __future__ import annotations

import json
import asyncio
import time
import logging
from divoom_gui.api import ApiBase

logger = logging.getLogger("divoom_gui.api.widgets")


class WidgetsApi(ApiBase):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    def push_weather(self) -> bool:
        from divoom_lib.system.weather import Weather
        from divoom_lib.weather_provider import get_weather
        from divoom_lib.models import COMMANDS

        async def _push(d):
            info = await get_weather()
            # Step 1: switch to TEMPRETURE channel (APK canonical 0x45)
            await d.send_command(
                COMMANDS["set light mode"],
                [0x01, 0x00, 0xFF, 0xFF, 0xFF, 0x00],
            )
            # Step 2: push temperature + weather data
            return await Weather(d).set(info.temperature_c, info.weather_type)

        return self._tool_call(_push, "weather")

    def _tool_call(self, fn, label: str) -> bool:
        logger.info(f"GUI Action: Tool {label}...")
        try:
            target = self._current_divoom
            if not target:
                return False
            return bool(self._run_async(fn(target)))
        except Exception as e:
            logger.error(f"tool {label} failed: {e}")
            return False

    def get_weather(self) -> dict:
        """One weather reading, asked of the DAEMON.

        R67/C2: this used to fetch weather itself via
        `divoom_lib.weather_provider` while the daemon fetched it again for the
        device push — two fetches of one fact, from two code paths that could
        disagree, and potentially for two different cities because `location`
        was never passed through. The daemon now owns it, so the card and the
        panel cannot drift apart.

        The local provider is still the one that RESOLVES the location (env
        overrides, then IP geolocation), and that resolved value is sent along
        so the daemon does not have to guess.
        """
        from divoom_lib.models import WeatherType

        try:
            client = self._client
            if client is None:
                raise RuntimeError("daemon not available")
            try:
                from divoom_lib.weather_provider import _resolve_location
                location = _resolve_location(None)
            except Exception:
                location = ""
            reply = client.weather(location)
            if not isinstance(reply, dict) or not reply.get("success"):
                raise RuntimeError((reply or {}).get("error", "weather unavailable"))
            return {
                "temperature_c": reply.get("temperature_c", 0),
                "weather_type": reply.get("weather_type", int(WeatherType.Clear)),
                "location": reply.get("location") or location or "here",
                "provider": "daemon",
                "fetched_at": time.time(),
            }
        except Exception as exc:
            logger.warning("get_weather failed: %s", exc)
            # An honest failure: the card must be able to say the reading is
            # unavailable rather than render a fabricated 0C.
            return {
                "temperature_c": 0,
                "weather_type": int(WeatherType.Clear),
                "location": "unavailable",
                "provider": "error",
                "fetched_at": 0.0,
                "error": str(exc),
            }


        async def _gather():
            info = await get_weather()
            return {
                "temperature_c": info.temperature_c,
                "weather_type": info.weather_type,
                "location": info.location,
                "provider": info.provider,
                "fetched_at": info.fetched_at,
            }

        try:
            return asyncio.run(_gather())
        except Exception as exc:
            logger.warning("get_weather failed: %s", exc)
            return {
                "temperature_c": 0,
                "weather_type": int(WeatherType.Clear),
                "location": "error",
                "provider": "stub",
                "fetched_at": 0.0,
                "error": str(exc),
            }