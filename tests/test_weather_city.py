"""The manual weather-location override (P3.1).

Weather geolocates by IP, which is right almost always and wrong exactly where
people notice — VPN, datacentre egress, living near a border. This is the escape
hatch. The tests below pin the three things that make it correct rather than
merely present:

* it is an OVERRIDE — no city set must still mean IP geolocation;
* it stores COORDINATES, because `Weather/SearchCity` is a Divoom endpoint and
  the thing that fetches weather is wttr.in, which has never heard of a Divoom
  `CityId`. Lat/lon is the one field pair both namespaces agree on;
* it can be CLEARED, without editing a config file by hand.
"""
from __future__ import annotations

import configparser

import pytest

from divoom_gui.weather_city import WeatherCityMixin
from divoom_lib import weather_provider


@pytest.fixture
def gui(tmp_path, monkeypatch):
    """A mixin instance whose config.ini is in tmp_path, not the real HOME."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Every env override off, so tests see the saved tier rather than an env one.
    for var in ("DIVOOM_CONTROL_WEATHER_LAT", "DIVOOM_CONTROL_WEATHER_LON",
                "DIVOOM_CONTROL_WEATHER_LOCATION"):
        monkeypatch.delenv(var, raising=False)
    return WeatherCityMixin()


# ── persistence ───────────────────────────────────────────────────────────────

def test_saving_a_city_stores_coordinates_not_the_name(gui, tmp_path):
    assert gui.set_weather_city("52.52", "13.405", "Berlin") is True

    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / ".config" / "divoom-control" / "config.ini")
    # The name is display-only; the LOCATION must be what wttr.in can resolve.
    assert cfg.get("weather", "location") == "52.52,13.405"
    assert cfg.get("weather", "city_name") == "Berlin"


def test_a_saved_city_round_trips(gui):
    gui.set_weather_city("35.68", "139.69", "Tokyo")
    assert gui.get_weather_city() == {"location": "35.68,139.69", "name": "Tokyo"}


def test_no_saved_city_reads_as_no_override(gui):
    assert gui.get_weather_city() == {"location": "", "name": ""}


def test_clearing_restores_ip_geolocation(gui):
    """Clearing is a first-class outcome, not an edge case — the user must be
    able to get back to IP geolocation without hand-editing a config file."""
    gui.set_weather_city("52.52", "13.405", "Berlin")
    assert gui.set_weather_city("", "", "") is True

    assert gui.get_weather_city() == {"location": "", "name": ""}
    assert weather_provider.resolve_location(None) == ""


def test_non_numeric_coordinates_are_refused(gui):
    """The saved string goes straight into a wttr.in URL, so junk in it produces
    a confusing weather answer rather than an obvious error. Refuse at write."""
    assert gui.set_weather_city("north", "west", "Nowhere") is False
    assert gui.get_weather_city()["location"] == ""


def test_saving_preserves_other_config_sections(gui, tmp_path):
    """config.ini is shared — it also holds gallery settings and credentials.
    Writing the weather section must not truncate the file."""
    path = tmp_path / ".config" / "divoom-control" / "config.ini"
    path.parent.mkdir(parents=True)
    path.write_text("[gallery]\ndefault = 18\n")

    gui.set_weather_city("1.0", "2.0", "Somewhere")

    cfg = configparser.ConfigParser()
    cfg.read(path)
    assert cfg.get("gallery", "default") == "18"
    assert cfg.get("weather", "location") == "1.0,2.0"


# ── resolution order ──────────────────────────────────────────────────────────

def test_a_saved_city_is_used_when_no_env_override_is_set(gui):
    gui.set_weather_city("48.85", "2.35", "Paris")
    assert weather_provider.resolve_location(None) == "48.85,2.35"


def test_an_explicit_argument_still_wins(gui):
    gui.set_weather_city("48.85", "2.35", "Paris")
    assert weather_provider.resolve_location("Reykjavik") == "Reykjavik"


def test_env_vars_outrank_the_saved_city(gui, monkeypatch):
    """Deliberately below the env vars. Those are a per-run override, and the
    dev-bundle/launchd case R67/C2 fixed depends on them — a stored preference
    must not silently outrank a deliberate one."""
    gui.set_weather_city("48.85", "2.35", "Paris")
    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_LOCATION", "Oslo")
    assert weather_provider.resolve_location(None) == "Oslo"

    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_LAT", "1.5")
    monkeypatch.setenv("DIVOOM_CONTROL_WEATHER_LON", "2.5")
    assert weather_provider.resolve_location(None) == "1.5,2.5"


def test_a_corrupt_config_falls_through_to_ip_geolocation(gui, tmp_path):
    """A malformed config must not take out the live weather job. Falling
    through to IP geolocation is a working answer; raising is not."""
    path = tmp_path / ".config" / "divoom-control" / "config.ini"
    path.parent.mkdir(parents=True)
    path.write_text("this is not ini [[[\n")

    assert weather_provider.saved_location() == ""
    assert weather_provider.resolve_location(None) == ""


# ── search ────────────────────────────────────────────────────────────────────

def test_search_forwards_to_the_daemon(gui, monkeypatch):
    """R70 P2.1: the seam is the DAEMON now, not a CloudClient built here."""
    seen = {}

    class _Client:
        def search_weather_city(self, keyword):
            seen["keyword"] = keyword
            return [{"CityName": "Berlin", "Lat": 52.52, "Lon": 13.405}]

    monkeypatch.setattr(type(gui), "_client", lambda self: _Client(), raising=False)
    result = gui.search_weather_city("  berlin  ")
    assert result["ok"] is True
    assert result["items"] == [{"CityName": "Berlin", "Lat": 52.52, "Lon": 13.405}]
    assert seen["keyword"] == "berlin", "the keyword must be trimmed"


def test_an_empty_keyword_never_reaches_the_daemon(gui, monkeypatch):
    class _Boom:
        def search_weather_city(self, keyword):
            raise AssertionError("an empty keyword must not be sent")

    monkeypatch.setattr(type(gui), "_client", lambda self: _Boom(), raising=False)
    result = gui.search_weather_city("   ")
    assert result["ok"] is True and result["items"] == []


def test_a_failing_search_says_WHY_rather_than_reading_as_no_results(gui, monkeypatch):
    """This test used to assert the opposite, and its name said so.

    It read: "A search that errors should show 'no results', not break the
    panel it lives in — the same contract every other cloud browse in this GUI
    has." That contract was the R70 defect: four different failures (empty,
    unreachable, unauthenticated, cloud error) rendered as one blank list, and
    the rationale being written down as care is how it spread to five panels.

    A panel that names the failure is not broken. It is the only version a user
    can act on. (House rule #8: a test pinning a wrong behaviour is part of the
    defect, not coverage to protect.)
    """
    from divoom_client.daemon_cloud import CloudUnavailable

    class _Boom:
        def search_weather_city(self, keyword):
            raise CloudUnavailable("Weather/SearchCity failed (RC=1): Failed", "cloud")

    monkeypatch.setattr(type(gui), "_client", lambda self: _Boom(), raising=False)
    result = gui.search_weather_city("berlin")
    assert result["ok"] is False
    assert result["items"] == []
    assert "RC=1" in result["error"]
    assert result["cause"] == "cloud"


def test_the_methods_are_reachable_on_the_real_gui_api():
    """The mixin is only useful if it is actually mixed in — pywebview exposes
    DivoomGuiAPI's methods by name, so a missing mixin is a missing feature with
    no other symptom."""
    from divoom_gui.gui_api import DivoomGuiAPI

    for name in ("search_weather_city", "get_weather_city", "set_weather_city"):
        assert callable(getattr(DivoomGuiAPI, name, None)), name
