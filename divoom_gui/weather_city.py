# gui/weather_city.py

import logging
from pathlib import Path

from divoom_gui.cloud_panels import CloudPanelMixin
from divoom_lib.utils.atomic_io import atomic_write_config
from divoom_lib.weather_provider import WEATHER_CONFIG_SECTION, saved_location

logger = logging.getLogger("divoom_gui")


class WeatherCityMixin(CloudPanelMixin):
    """Manual weather-location override, backed by `Weather/SearchCity`.

    Weather normally geolocates by the caller's IP, which is right almost
    always and wrong in exactly the cases people notice — a VPN, a datacentre
    egress, or living near a border. This is the escape hatch, and it stays an
    override: no city set means IP geolocation, unchanged.

    **Why coordinates and not the city name.** `Weather/SearchCity` is a Divoom
    cloud endpoint and returns `CityId`, `CityName`, `Country`, `Lat`, `Lon`.
    The thing that actually fetches weather is wttr.in, which has never heard of
    a Divoom `CityId`. Latitude and longitude are the one field pair both
    namespaces agree on, so the saved value is wttr.in's `"lat,lon"` form. The
    name is stored alongside it for display only — never for lookup.

    The daemon needs no change for this: `MediaSyncMixin._get_live_params`
    already resolves the location and sends it as `params["location"]` (R67/C2),
    and `resolve_location` now consults the saved value. One resolver, one
    answer, sent over the wire — which was the whole point of R67/C2.
    """

    @staticmethod
    def _weather_config_path() -> Path:
        return Path.home() / ".config" / "divoom-control" / "config.ini"

    def search_weather_city(self, keyword: str) -> dict:
        """Cities matching `keyword`, asked of the DAEMON.

        R70 P2.1/P2.4. This used to run the cloud call in the GUI process and
        return [] on any failure, explaining itself: "Returns [] rather than
        raising for the same reason every other cloud browse in this GUI does:
        a search that errors should show 'no results', not break the panel it
        lives in."

        The premise was false. A panel that says "the background service is not
        running" is not broken, it is honest — and the daemon answers
        `Weather/SearchCity failed (RC=1): Failed` where this returned nothing
        at all. Stated as care, that rationale spread to five panels before
        anyone noticed it was hiding four different failures behind one empty
        list.

        An empty keyword is still an empty result, not an error: there is
        nothing to report and nothing went wrong.
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return {"ok": True, "items": [], "error": "", "cause": ""}
        return self._cloud_list(
            "city search results", lambda c: c.search_weather_city(keyword))

    def get_weather_city(self) -> dict:
        """The saved override, as `{"location": ..., "name": ...}`.

        Both empty means "no override — geolocating by IP", which the UI must
        say out loud rather than showing a blank field that looks unset-by-
        accident.
        """
        import configparser

        name = ""
        try:
            path = self._weather_config_path()
            if path.exists():
                cfg = configparser.ConfigParser()
                cfg.read(path)
                if cfg.has_option(WEATHER_CONFIG_SECTION, "city_name"):
                    name = cfg.get(WEATHER_CONFIG_SECTION, "city_name") or ""
        except Exception as e:
            logger.warning(f"get_weather_city failed: {e}")
        return {"location": saved_location(), "name": name}

    def set_weather_city(self, lat: str = "", lon: str = "",
                         name: str = "") -> bool:
        """Save (or, with empty lat/lon, clear) the weather-location override.

        Clearing is a first-class outcome, not an edge case: the user must be
        able to get back to IP geolocation without editing a config file.
        """
        import configparser

        lat = str(lat or "").strip()
        lon = str(lon or "").strip()
        try:
            location = ""
            if lat and lon:
                # Validated as numbers before being written: this string goes
                # straight into a wttr.in URL, and a junk value would produce a
                # confusing weather result rather than an obvious error.
                location = f"{float(lat)},{float(lon)}"
            path = self._weather_config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            cfg = configparser.ConfigParser()
            if path.exists():
                cfg.read(path)
            if WEATHER_CONFIG_SECTION not in cfg:
                cfg[WEATHER_CONFIG_SECTION] = {}
            cfg[WEATHER_CONFIG_SECTION]["location"] = location
            cfg[WEATHER_CONFIG_SECTION]["city_name"] = str(name or "") if location else ""
            atomic_write_config(path, cfg, mode=0o600)  # config.ini holds creds
            logger.info(
                "weather location set to %s",
                f"{location} ({name})" if location else "IP geolocation")
            return True
        except ValueError:
            logger.error(f"set_weather_city got non-numeric coordinates: {lat!r},{lon!r}")
            return False
        except Exception as e:
            logger.error(f"set_weather_city failed: {e}")
            return False
