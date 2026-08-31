"""
R15 §3 — Weather provider.

A small abstraction layer over weather data sources. The Live Widgets
Weather card needs a current temperature + condition; we get this from
one of:

  * ``WTTrInProvider`` — public, no-auth, JSON-formatted endpoint at
    ``wttr.in`` (e.g. ``https://wttr.in/Berlin?format=j1``). WMO weather
    codes are mapped onto our internal ``WeatherType`` enum.

  * ``StubProvider`` — deterministic data for tests and offline use.

  * ``get_weather(provider, location=None)`` — public entry point. If
    the configured provider fails (network error, parse error, missing
    key) it falls back to ``StubProvider`` so the UI never has to
    handle a None.

Location resolution order:
  1. ``location`` argument (if provided)
  2. ``DIVOOM_CONTROL_WEATHER_LAT`` / ``DIVOOM_CONTROL_WEATHER_LON``
     env vars (reverse-geocoded by wttr.in's coordinate format)
  3. ``DIVOOM_CONTROL_WEATHER_LOCATION`` env var
  4. the saved location in ``~/.config/divoom-control/config.ini``
     (``[weather] location``), set by the GUI's city search
  5. ``""`` — an empty location makes wttr.in geolocate by the caller's IP,
     and the real city is read back from ``nearest_area``.

  (Item 4 is the only persisted tier; the env vars stay above it so a
  deliberate override still wins for debugging. Items 1-3 and 5 predate it.
  This list used to end at ``"Berlin"`` — a hardcoded default that was
  replaced by IP geolocation without the docstring being updated, so it
  documented a city the code had already stopped using.)

The interface is intentionally tiny so the GUI can swap providers
without touching the weather-card code::

    info = await get_weather()
    print(info.temperature_c, info.weather_type, info.location)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from divoom_lib.models import WeatherType

logger = logging.getLogger(__name__)


class WeatherProviderKind(str, Enum):
    WTTR_IN = "wttr_in"
    STUB = "stub"


# WMO weather codes → internal WeatherType. See
# https://open-meteo.com/weather-documentation and wttr.in's docs.
# (wttr.in returns the same code via ``weatherCode``.)
WEATHER_CODE_TO_DIVOOM: dict[int, int] = {
    113: WeatherType.Clear,        # Sunny / clear
    116: WeatherType.CloudySky,    # Partly cloudy
    119: WeatherType.CloudySky,    # Cloudy
    122: WeatherType.CloudySky,    # Overcast
    143: WeatherType.Fog,          # Mist
    176: WeatherType.Rain,         # Patchy rain possible
    179: WeatherType.Snow,         # Patchy snow possible
    182: WeatherType.Snow,         # Patchy sleet possible
    185: WeatherType.Fog,          # Patchy freezing drizzle
    200: WeatherType.Thunderstorm, # Thundery outbreaks
    227: WeatherType.Snow,         # Blowing snow
    230: WeatherType.Snow,         # Blizzard
    248: WeatherType.Fog,          # Fog
    260: WeatherType.Fog,          # Freezing fog
    263: WeatherType.Rain,         # Patchy light drizzle
    266: WeatherType.Rain,         # Light drizzle
    281: WeatherType.Rain,         # Freezing drizzle
    284: WeatherType.Rain,         # Heavy freezing drizzle
    293: WeatherType.Rain,         # Patchy light rain
    296: WeatherType.Rain,         # Light rain
    299: WeatherType.Rain,         # Moderate rain at times
    302: WeatherType.Rain,         # Moderate rain
    305: WeatherType.Rain,         # Heavy rain at times
    308: WeatherType.Rain,         # Heavy rain
    311: WeatherType.Rain,         # Light freezing rain
    314: WeatherType.Rain,         # Moderate / heavy freezing rain
    317: WeatherType.Snow,         # Light sleet
    320: WeatherType.Snow,         # Moderate / heavy sleet
    323: WeatherType.Snow,         # Patchy light snow
    326: WeatherType.Snow,         # Light snow
    329: WeatherType.Snow,         # Patchy moderate snow
    332: WeatherType.Snow,         # Moderate snow
    335: WeatherType.Snow,         # Patchy heavy snow
    338: WeatherType.Snow,         # Heavy snow
    350: WeatherType.Snow,         # Ice pellets
    353: WeatherType.Rain,         # Light rain shower
    356: WeatherType.Rain,         # Moderate / heavy rain shower
    359: WeatherType.Rain,         # Torrential rain shower
    362: WeatherType.Snow,         # Light sleet showers
    365: WeatherType.Snow,         # Moderate / heavy sleet showers
    368: WeatherType.Snow,         # Light snow showers
    371: WeatherType.Snow,         # Moderate / heavy snow showers
    374: WeatherType.Snow,         # Light ice pellet showers
    377: WeatherType.Snow,         # Moderate / heavy ice pellet showers
    386: WeatherType.Thunderstorm, # Patchy light rain w/ thunder
    389: WeatherType.Thunderstorm, # Moderate / heavy rain w/ thunder
    392: WeatherType.Thunderstorm, # Patchy light snow w/ thunder
    395: WeatherType.Thunderstorm, # Moderate / heavy snow w/ thunder
}

# Default location when no env override is set. Berlin is a wttr.in-
# resolvable city name with predictable weather — useful for stub
# fallback so the card always shows *something* in dev.
DEFAULT_LOCATION = "Berlin"


@dataclass(frozen=True)
class WeatherInfo:
    """A snapshot of current weather. Immutable so it can be safely
    cached in the UI."""

    temperature_c: int
    weather_type: int  # one of divoom_lib.models.WeatherType
    location: str
    provider: str  # string for JSON-friendliness
    fetched_at: float  # unix epoch seconds


WEATHER_CONFIG_SECTION = "weather"


def saved_location() -> str:
    """The location saved by the GUI's city search, or "" if none is set.

    Reads the same `~/.config/divoom-control/config.ini` the rest of the GUI
    persists to. Stored as wttr.in's `"lat,lon"` coordinate form rather than a
    city name: `Weather/SearchCity` returns `Lat`/`Lon` alongside the name, and
    coordinates survive the fact that Divoom's city namespace and wttr.in's are
    not the same one — a `CityId` from Divoom means nothing to wttr.in, but a
    latitude does.

    Any failure reads as "not set". A malformed config file must not stop the
    weather widget from working; falling through to IP geolocation is a working
    answer, and raising here would take out the whole live job.
    """
    import configparser
    from pathlib import Path

    try:
        path = Path.home() / ".config" / "divoom-control" / "config.ini"
        if not path.exists():
            return ""
        cfg = configparser.ConfigParser()
        cfg.read(path)
        if cfg.has_option(WEATHER_CONFIG_SECTION, "location"):
            return (cfg.get(WEATHER_CONFIG_SECTION, "location") or "").strip()
    except Exception as e:  # noqa: BLE001 - see docstring
        logger.debug(f"could not read saved weather location: {e}")
    return ""


def resolve_location(explicit: Optional[str]) -> str:
    """Pick the location string, applying overrides in priority order.

    PUBLIC as of R72 P2.1. Two GUI sites imported this while it was
    underscore-prefixed -- reaching into the private surface of a module the
    docs call reference-only, which breaks silently the day it is renamed.

    It is CLIENT-LOCAL work despite living here, and the capability map says so:
    it reads env vars and a saved preference and makes no network call. The IP
    geolocation in the note below happens on wttr.in's side, inside the
    DAEMON's request, when this returns "".

    Priority order:

      1. explicit argument
      2. DIVOOM_CONTROL_WEATHER_LAT / _LON
      3. DIVOOM_CONTROL_WEATHER_LOCATION
      4. the saved location from the GUI's city search

    With none set, returns "" — an empty location makes wttr.in **geolocate by
    the caller's IP** (``https://wttr.in/?format=j1``), and the real city is read
    back from the response's ``nearest_area``. This replaces the old hardcoded
    "Berlin" default (which was wrong for everyone not in Berlin).

    The saved location sits BELOW the env vars deliberately: those are a
    deliberate per-run override (and the dev bundle/launchd case R67/C2 fixed
    depends on them), so a stored preference must not silently outrank one.
    """
    if explicit:
        return explicit
    lat = os.environ.get("DIVOOM_CONTROL_WEATHER_LAT")
    lon = os.environ.get("DIVOOM_CONTROL_WEATHER_LON")
    if lat and lon:
        return f"{lat},{lon}"
    env_loc = os.environ.get("DIVOOM_CONTROL_WEATHER_LOCATION")
    if env_loc:
        return env_loc
    saved = saved_location()
    if saved:
        return saved
    return ""  # let wttr.in geolocate by IP


def _map_weather_code(code: int) -> int:
    """WMO weather code → divoom WeatherType. Unknown codes fall back
    to Clear (it's the most "neutral" icon and never crashes the UI)."""
    return WEATHER_CODE_TO_DIVOOM.get(int(code), WeatherType.Clear)


class StubProvider:
    """Deterministic data source for tests + offline dev.

    Returns a fixed temperature/condition so tests can assert against
    the data without mocking out the network. The default is "Clear,
    22°C, Berlin" — pleasant and visually distinct."""

    provider_name = "stub"

    def __init__(
        self,
        temperature_c: int = 22,
        weather_type: int = WeatherType.Clear,
        location: str = "stub",
    ) -> None:
        self._temperature_c = int(temperature_c)
        self._weather_type = int(weather_type)
        self._location = str(location)

    async def fetch(self, location: Optional[str] = None) -> WeatherInfo:
        return WeatherInfo(
            temperature_c=self._temperature_c,
            weather_type=self._weather_type,
            location=self._location,
            provider=self.provider_name,
            fetched_at=time.time(),
        )


class WTTrInProvider:
    """wttr.in JSON endpoint. Public, no auth, no key.

    Endpoint: ``https://wttr.in/{location}?format=j1`` (the ``j1`` flag
    requests JSON output). The response is a small blob with
    ``current_condition[0]`` containing ``temp_C`` and ``weatherCode``.

    Network errors, parse errors, and missing fields all raise
    ``WeatherProviderError`` so the caller can fall back to Stub.
    """

    provider_name = "wttr_in"
    BASE_URL = "https://wttr.in"

    def __init__(self, session=None, timeout_s: float = 8.0) -> None:
        self._session = session
        self._timeout_s = float(timeout_s)

    async def fetch(self, location: Optional[str] = None) -> WeatherInfo:
        loc = resolve_location(location)
        url = f"{self.BASE_URL}/{loc}"
        params = {"format": "j1"}

        try:
            import aiohttp  # imported lazily so tests without aiohttp can still use Stub
        except ImportError as exc:
            raise WeatherProviderError(
                f"aiohttp not available: {exc}"
            ) from exc

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self._timeout_s)
        )
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise WeatherProviderError(
                        f"wttr.in returned HTTP {resp.status} for {loc!r}"
                    )
                data = await resp.json(content_type=None)
        except Exception as exc:  # network, timeout, decode, anything
            raise WeatherProviderError(f"wttr.in fetch failed: {exc}") from exc
        finally:
            if own_session:
                await session.close()

        try:
            current = data["current_condition"][0]
            temp_c = int(round(float(current["temp_C"])))
            weather_code = int(current["weatherCode"])
            area = data.get("nearest_area", [{}])[0]
            area_name = (
                area.get("areaName", [{}])[0].get("value")
                if isinstance(area.get("areaName"), list)
                else None
            )
            country = (
                area.get("country", [{}])[0].get("value")
                if isinstance(area.get("country"), list)
                else None
            )
            display = ", ".join(filter(None, [area_name, country])) or loc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise WeatherProviderError(
                f"wttr.in response missing expected fields: {exc}"
            ) from exc

        return WeatherInfo(
            temperature_c=temp_c,
            weather_type=_map_weather_code(weather_code),
            location=display,
            provider=self.provider_name,
            fetched_at=time.time(),
        )


class WeatherProviderError(RuntimeError):
    """Raised by a provider when the fetch fails. Callers should fall
    back to ``StubProvider`` (or surface a non-fatal warning in the UI)."""


async def get_weather(
    provider: Optional[WeatherProviderKind] = None,
    location: Optional[str] = None,
    stub_fallback: bool = True,
) -> WeatherInfo:
    """Public entry point. Returns a ``WeatherInfo``.

    The provider is selected from the optional ``provider`` argument,
    otherwise the ``DIVOOM_CONTROL_WEATHER_PROVIDER`` env var, otherwise
    wttr.in. If the provider raises ``WeatherProviderError`` (or any
    other exception) and ``stub_fallback`` is True, the function falls
    back to ``StubProvider`` and logs a warning."""

    chosen = provider or _env_provider()
    if chosen == WeatherProviderKind.STUB:
        return await StubProvider().fetch(location=location)
    try:
        return await WTTrInProvider().fetch(location=location)
    except Exception as exc:
        if not stub_fallback:
            raise
        logger.warning(
            "WeatherProvider %s failed (%s); falling back to StubProvider.",
            chosen.value,
            exc,
        )
        return await StubProvider().fetch(location=location)


def _env_provider() -> WeatherProviderKind:
    raw = os.environ.get("DIVOOM_CONTROL_WEATHER_PROVIDER", "").strip().lower()
    if raw == "stub":
        return WeatherProviderKind.STUB
    # Default to wttr.in for everything else (including unknown values).
    return WeatherProviderKind.WTTR_IN
