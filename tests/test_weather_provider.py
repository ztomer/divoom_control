"""
R15 §3 — tests for the weather provider (divoom_lib/weather_provider.py).

Five contract tests:
1. WMO weather code → divoom WeatherType mapping covers all the cases
   we expect (clear, cloudy, rain, snow, fog, storm) plus a fallback
   for unknown codes.
2. StubProvider returns deterministic data.
3. WTTrInProvider parses a mock JSON response correctly.
4. WTTrInProvider falls back to StubProvider on network/parse error.
5. get_weather() returns a WeatherInfo with the right fields.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from divoom_lib.models import WeatherType
from divoom_lib.weather_provider import (
    DEFAULT_LOCATION,
    StubProvider,
    WEATHER_CODE_TO_DIVOOM,
    WTTrInProvider,
    WeatherInfo,
    WeatherProviderError,
    WeatherProviderKind,
    _map_weather_code,
    _resolve_location,
    get_weather,
)


# ── 1. WMO code → WeatherType ─────────────────────────────────────────


@pytest.mark.parametrize(
    "wmo_code,expected",
    [
        (113, WeatherType.Clear),        # Sunny
        (116, WeatherType.CloudySky),    # Partly cloudy
        (119, WeatherType.CloudySky),    # Cloudy
        (122, WeatherType.CloudySky),    # Overcast
        (143, WeatherType.Fog),          # Mist
        (248, WeatherType.Fog),          # Fog
        (260, WeatherType.Fog),          # Freezing fog
        (176, WeatherType.Rain),         # Patchy rain
        (296, WeatherType.Rain),         # Light rain
        (308, WeatherType.Rain),         # Heavy rain
        (359, WeatherType.Rain),         # Torrential
        (179, WeatherType.Snow),         # Patchy snow
        (332, WeatherType.Snow),         # Moderate snow
        (338, WeatherType.Snow),         # Heavy snow
        (200, WeatherType.Thunderstorm), # Thundery outbreaks
        (386, WeatherType.Thunderstorm), # Rain w/ thunder
    ],
)
def test_wmo_code_to_weather_type(wmo_code: int, expected: int) -> None:
    assert _map_weather_code(wmo_code) == expected


def test_wmo_code_unknown_falls_back_to_clear() -> None:
    """Unknown codes default to Clear (safest icon, never crashes UI)."""
    assert _map_weather_code(999) == WeatherType.Clear
    assert _map_weather_code(-1) == WeatherType.Clear


def test_wmo_mapping_covers_all_six_weather_types() -> None:
    """Every internal WeatherType must be reachable from the WMO map."""
    internal_types = {
        v for v in WEATHER_CODE_TO_DIVOOM.values()
    }
    expected_types = {
        WeatherType.Clear,
        WeatherType.CloudySky,
        WeatherType.Thunderstorm,
        WeatherType.Rain,
        WeatherType.Snow,
        WeatherType.Fog,
    }
    assert expected_types.issubset(internal_types), (
        f"Missing WeatherType mappings: {expected_types - internal_types}"
    )


# ── 2. StubProvider is deterministic ──────────────────────────────────


@pytest.mark.asyncio
async def test_stub_provider_returns_deterministic_data() -> None:
    info = await StubProvider(temperature_c=15, weather_type=WeatherType.Snow, location="test-city").fetch()
    assert isinstance(info, WeatherInfo)
    assert info.temperature_c == 15
    assert info.weather_type == WeatherType.Snow
    assert info.location == "test-city"
    assert info.provider == "stub"
    assert info.fetched_at > 0


@pytest.mark.asyncio
async def test_stub_provider_default_is_clear_22c() -> None:
    """The default-constructed stub returns 22°C Clear (used as the
    network-failure fallback so the UI never sees a None)."""
    info = await StubProvider().fetch()
    assert info.temperature_c == 22
    assert info.weather_type == WeatherType.Clear


# ── 3. WTTrInProvider parses mock JSON ────────────────────────────────


@pytest.mark.asyncio
async def test_wttr_provider_parses_valid_response() -> None:
    """A mock aiohttp response with a valid j1 payload parses to the
    expected WeatherInfo."""
    fake_payload = {
        "current_condition": [
            {
                "temp_C": "12",
                "weatherCode": "113",  # Sunny
            }
        ],
        "nearest_area": [
            {
                "areaName": [{"value": "Berlin"}],
                "country": [{"value": "Germany"}],
            }
        ],
    }
    fake_resp = MagicMock()
    fake_resp.status = 200

    async def _json(**kwargs):
        return fake_payload

    fake_resp.json = _json

    # Use a MagicMock as the context-manager-with-response.
    session = MagicMock()
    session.get.return_value.__aenter__.return_value = fake_resp
    session.get.return_value.__aexit__.return_value = False

    info = await WTTrInProvider(session=session).fetch("Berlin")
    assert info.temperature_c == 12
    assert info.weather_type == WeatherType.Clear
    assert info.location == "Berlin, Germany"
    assert info.provider == "wttr_in"


# ── 4. Fallback on network/parse error ────────────────────────────────


@pytest.mark.asyncio
async def test_wttr_provider_falls_back_on_http_error() -> None:
    """A non-200 status raises WeatherProviderError, which
    ``get_weather()`` catches and falls back to StubProvider."""
    fake_resp = MagicMock()
    fake_resp.status = 500

    session = MagicMock()
    session.get.return_value.__aenter__.return_value = fake_resp
    session.get.return_value.__aexit__.return_value = False

    with pytest.raises(WeatherProviderError):
        await WTTrInProvider(session=session).fetch("Berlin")


@pytest.mark.asyncio
async def test_wttr_provider_falls_back_on_malformed_json() -> None:
    """A response that doesn't have the expected keys raises
    WeatherProviderError so the caller can fall back."""
    fake_resp = MagicMock()
    fake_resp.status = 200

    async def _json(**kwargs):
        return {"oops": "no current_condition key"}

    fake_resp.json = _json

    session = MagicMock()
    session.get.return_value.__aenter__.return_value = fake_resp
    session.get.return_value.__aexit__.return_value = False

    with pytest.raises(WeatherProviderError):
        await WTTrInProvider(session=session).fetch("Berlin")


@pytest.mark.asyncio
async def test_get_weather_falls_back_to_stub_on_provider_error(
    monkeypatch,
) -> None:
    """``get_weather()`` catches WTTrInProvider errors and returns
    StubProvider data — the UI never sees an exception."""
    # Force the env to pick wttr_in (default), then make the network
    # call raise.
    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_PROVIDER", "wttr_in")
    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_LOCATION", "test-loc")

    from divoom_lib import weather_provider

    async def _explode(location=None):
        raise WeatherProviderError("network down")

    monkeypatch.setattr(weather_provider.WTTrInProvider, "fetch", _explode)

    info = await get_weather()
    assert info.provider == "stub"
    assert info.temperature_c == 22  # default stub
    assert info.weather_type == WeatherType.Clear


# ── 5. get_weather() entry point ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_weather_returns_weather_info(monkeypatch) -> None:
    """``get_weather()`` returns a frozen dataclass with the right
    fields, regardless of which provider is used."""
    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_PROVIDER", "stub")
    info = await get_weather()
    assert isinstance(info, WeatherInfo)
    # Frozen — assignment should raise.
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.temperature_c = 99  # type: ignore[misc]


@pytest.mark.asyncio
async def test_get_weather_stub_provider_via_env(monkeypatch) -> None:
    """Setting the env var to "stub" forces the stub provider
    (useful for CI / tests)."""
    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_PROVIDER", "stub")
    info = await get_weather()
    assert info.provider == "stub"


def test_resolve_location_priority() -> None:
    """Explicit argument wins; then lat/lon env; then location env;
    then the default."""
    # Explicit argument wins.
    assert _resolve_location("explicit") == "explicit"
    # Lat/lon env.
    import os
    os.environ["DIVOOM_CONTROL_WEATHER_LAT"] = "52.5"
    os.environ["DIVOOM_CONTROL_WEATHER_LON"] = "13.4"
    os.environ["DIVOOM_CONTROL_WEATHER_LOCATION"] = "fallback"
    try:
        # lat/lon takes priority over the location env.
        assert _resolve_location(None) == "52.5,13.4"
        # Explicit still wins.
        assert _resolve_location("explicit") == "explicit"
    finally:
        del os.environ["DIVOOM_CONTROL_WEATHER_LAT"]
        del os.environ["DIVOOM_CONTROL_WEATHER_LON"]
        del os.environ["DIVOOM_CONTROL_WEATHER_LOCATION"]


def test_resolve_location_uses_location_env_when_no_lat_lon() -> None:
    """Without lat/lon set, the location env is used."""
    import os
    for k in ("DIVOOM_CONTROL_WEATHER_LAT", "DIVOOM_CONTROL_WEATHER_LON"):
        os.environ.pop(k, None)
    os.environ["DIVOOM_CONTROL_WEATHER_LOCATION"] = "Tokyo"
    try:
        assert _resolve_location(None) == "Tokyo"
        assert _resolve_location("Osaka") == "Osaka"  # explicit wins
    finally:
        del os.environ["DIVOOM_CONTROL_WEATHER_LOCATION"]


def test_resolve_location_default(tmp_path, monkeypatch) -> None:
    """No env, no argument, no saved city -> "" so wttr.in geolocates by the
    caller's IP (replaces the old hardcoded Berlin default).

    HOME is redirected deliberately. Since P3.1 the last tier before "" is the
    city saved in `~/.config/divoom-control/config.ini`, so without this the
    assertion would depend on whether the DEVELOPER had set a weather city — it
    passes on a machine that has never used the feature and flips red on one
    that has. A test whose result depends on the user's own config is not
    testing the code.
    """
    import os
    for k in ("DIVOOM_CONTROL_WEATHER_LAT", "DIVOOM_CONTROL_WEATHER_LON", "DIVOOM_CONTROL_WEATHER_LOCATION"):
        os.environ.pop(k, None)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert _resolve_location(None) == ""


# ── Sanity: WeatherProviderKind enum ──────────────────────────────────


def test_provider_kind_enum_values() -> None:
    assert WeatherProviderKind.WTTR_IN.value == "wttr_in"
    assert WeatherProviderKind.STUB.value == "stub"
