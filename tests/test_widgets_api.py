"""Direct unit tests for `divoom_gui/api/widgets.py` (WidgetsApi).

R61 coverage push: this collaborator was previously only exercised via a
Mock in test_gui_api.py (the real class body — push_weather/_tool_call/
get_weather — was never actually run). These tests build a REAL WidgetsApi
on a real AsyncLoopThread (so `_run_async`'s `run_coroutine_threadsafe`
has somewhere to land), with `get_weather`/`Weather.set` mocked at their
import sites so no network or BLE device is touched.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_gui.api import AsyncLoopThread
from divoom_gui.api.widgets import WidgetsApi
from divoom_lib.models import WeatherType


class _FakeDivoom:
    """Stand-in device target: records every send_command call."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls = []

    async def send_command(self, command, args):
        self.calls.append((command, args))
        return self.ok


class _FakeWeatherInfo:
    def __init__(self, temperature_c=21, weather_type=int(WeatherType.Clear),
                 location="Berlin", provider="stub", fetched_at=123.0):
        self.temperature_c = temperature_c
        self.weather_type = weather_type
        self.location = location
        self.provider = provider
        self.fetched_at = fetched_at


@pytest.fixture
def loop_thread():
    t = AsyncLoopThread()
    t.start()
    assert t.ready.wait(timeout=2.0), "loop thread never became ready"
    yield t
    t.stop()


def _api(loop_thread, current_divoom=None):
    return WidgetsApi(
        loop_thread=loop_thread,
        daemon_client_getter=lambda: None,
        state_getter=lambda: {"current_divoom": current_divoom},
    )


# ── push_weather / _tool_call ──────────────────────────────────────────────


def test_push_weather_happy_path_switches_channel_then_sets_weather(loop_thread, monkeypatch):
    """push_weather must (1) fetch weather, (2) switch to the temperature
    channel, then (3) push temp+icon via Weather.set — all against the
    CURRENT device target — and return True on success."""
    import divoom_lib.weather_provider as wp

    info = _FakeWeatherInfo(temperature_c=25, weather_type=int(WeatherType.Rain))

    async def _fake_get_weather(*a, **k):
        return info

    monkeypatch.setattr(wp, "get_weather", _fake_get_weather)

    target = _FakeDivoom(ok=True)
    api = _api(loop_thread, current_divoom=target)
    assert api.push_weather() is True
    # Two send_command calls: the channel switch, then Weather.set's 0x5F frame.
    assert len(target.calls) == 2
    from divoom_lib.models import COMMANDS
    assert target.calls[0][0] == COMMANDS["set light mode"]
    assert target.calls[1][0] == COMMANDS["set temp"]
    assert target.calls[1][1][1] == int(WeatherType.Rain)  # weather_type byte


def test_push_weather_returns_false_when_no_current_device(loop_thread):
    """_tool_call: no current_divoom (nothing selected/connected) → False,
    without ever touching the network or a device."""
    api = _api(loop_thread, current_divoom=None)
    assert api.push_weather() is False


def test_push_weather_returns_false_and_logs_on_exception(loop_thread, monkeypatch):
    """_tool_call's except branch: an exception anywhere in the tool
    coroutine (here: the weather fetch itself) is swallowed to False, not
    raised to the pywebview JS-API thread."""
    import divoom_lib.weather_provider as wp

    async def _boom(*a, **k):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(wp, "get_weather", _boom)

    target = _FakeDivoom(ok=True)
    api = _api(loop_thread, current_divoom=target)
    assert api.push_weather() is False
    assert target.calls == []  # never got as far as sending anything


def test_push_weather_returns_false_when_device_send_fails(loop_thread, monkeypatch):
    """If the device rejects/NAKs the command (send_command → False), the
    bool(...) coercion in _tool_call must surface that as False."""
    import divoom_lib.weather_provider as wp

    async def _fake_get_weather(*a, **k):
        return _FakeWeatherInfo()

    monkeypatch.setattr(wp, "get_weather", _fake_get_weather)

    target = _FakeDivoom(ok=False)
    api = _api(loop_thread, current_divoom=target)
    assert api.push_weather() is False


# ── get_weather ─────────────────────────────────────────────────────────────






# ── get_weather: now a DAEMON client (R67/C2) ─────────────────────────────


def _api_with_client(loop_thread, client):
    return WidgetsApi(
        loop_thread=loop_thread,
        daemon_client_getter=lambda: client,
        state_getter=lambda: {"current_divoom": None},
    )


class _FakeWeatherClient:
    """Records the location it was asked for, and replies with a fixed reading."""

    def __init__(self, reply):
        self.reply = reply
        self.asked_location = None

    def weather(self, location=""):
        self.asked_location = location
        return self.reply


def test_get_weather_reads_the_daemon_not_a_second_fetch(loop_thread):
    """R67/C2: the GUI used to fetch weather itself while the daemon fetched it
    again for the device — two code paths for one fact, and potentially two
    different cities. The card must now report what the DAEMON says, so it
    cannot disagree with what the panel shows."""
    client = _FakeWeatherClient({
        "success": True, "temperature_c": 17,
        "weather_type": int(WeatherType.Snow), "location": "Oslo",
    })
    result = _api_with_client(loop_thread, client).get_weather()

    assert result["temperature_c"] == 17
    assert result["weather_type"] == int(WeatherType.Snow)
    assert result["location"] == "Oslo"
    assert result["provider"] == "daemon", "the reading came from the daemon"
    assert "error" not in result


def test_get_weather_sends_the_resolved_location(loop_thread, monkeypatch):
    """The location is resolved LOCALLY and sent along, so the daemon does not
    geolocate independently — the gap that let preview and device differ."""
    import divoom_lib.weather_provider as wp

    monkeypatch.setattr(wp, "_resolve_location", lambda _explicit: "Reykjavik")
    client = _FakeWeatherClient({
        "success": True, "temperature_c": 2,
        "weather_type": int(WeatherType.Clear), "location": "Reykjavik",
    })
    _api_with_client(loop_thread, client).get_weather()
    assert client.asked_location == "Reykjavik"


def test_get_weather_reports_a_daemon_error_honestly(loop_thread):
    """A weather card that silently shows a fabricated 0C is the dead-but-green
    state this round is about. The failure must be visible."""
    client = _FakeWeatherClient({"success": False, "error": "wttr.in returned 503"})
    result = _api_with_client(loop_thread, client).get_weather()

    assert result["provider"] == "error"
    assert result["location"] == "unavailable"
    assert "503" in result["error"]


def test_get_weather_without_a_daemon_is_an_error_not_a_reading(loop_thread):
    result = _api_with_client(loop_thread, None).get_weather()
    assert result["provider"] == "error"
    assert "error" in result
