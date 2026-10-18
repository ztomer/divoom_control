"""P5.4 — the weather card shows the frame the panel shows.

`get_weather_preview` is the card's only source. It asks the daemon for
`render_widget {kind: "weather"}` -- the call the weather live job's frame comes
from -- and hands the GUI that PNG plus the reading the frame was drawn from.
What these pin:

* the PNG is the daemon's bytes, not a drawing (the drift test proves the
  funnel; this proves the card's method is on it);
* the reading beside the frame is the reading IN the frame: one reply, so the
  text and the picture cannot come from two fetches that disagree;
* the location is the one the live job is started with, so the card cannot
  preview a different city than the panel shows;
* a failure is a stated reason, never a fabricated reading.
"""
from __future__ import annotations

import base64
import io
import json

import pytest

from divoom_gui.media_sync import MediaSyncMixin


def _checker(size: int) -> bytes:
    return b"".join(
        b"\xff\x00\x80" if (x + y) % 2 == 0 else b"\x00\x40\xff"
        for y in range(size) for x in range(size))


class _Daemon:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list[tuple] = []

    def render_widget(self, kind, size=16, params=None):
        self.calls.append((kind, size, dict(params or {})))
        return self.reply


#: The panel the card previews for (P5.7: the call names it).
PANEL = "AA:00:00:00:00:01"


class _Host(MediaSyncMixin):
    """The mixin with only the state it reads: no device, no wall."""

    def __init__(self, daemon):
        self._daemon = daemon
        self.wall_slots = {}
        self.pixels = {}

    def _client(self):
        return self._daemon

    def _panel_pixels(self, mac):
        return self.pixels.get(mac)


def _ok_reply(size=16, **extras):
    reply = {"success": True, "kind": "weather", "size": size,
             "frame_rgb_b64": base64.b64encode(_checker(size)).decode()}
    reply.update(extras)
    return reply


@pytest.fixture
def location(monkeypatch):
    import divoom_lib.weather_provider as wp
    monkeypatch.setattr(wp, "resolve_location", lambda _explicit: "59.91,10.75")
    return "59.91,10.75"


def test_the_card_gets_the_daemons_weather_frame_byte_for_byte(location):
    from PIL import Image

    daemon = _Daemon(_ok_reply(temperature_c=-3, weather=8, location="Oslo"))
    r = json.loads(_Host(daemon).get_weather_preview(PANEL, 16))

    assert r["ok"] is True, r
    assert daemon.calls and daemon.calls[0][0] == "weather"
    head, b64 = r["preview"].split(",", 1)
    assert head == "data:image/png;base64"
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    assert img.size == (16, 16)
    assert img.tobytes() == _checker(16), "the card is not showing the daemon's frame"


def test_the_reading_beside_the_frame_is_the_reading_in_it(location):
    daemon = _Daemon(_ok_reply(temperature_c=-3, weather=8, location="Oslo"))
    r = json.loads(_Host(daemon).get_weather_preview(PANEL, 16))

    assert (r["temperature_c"], r["weather"], r["location"]) == (-3, 8, "Oslo")
    assert len(daemon.calls) == 1, "one reply carries both the frame and the reading"


def test_the_card_previews_the_city_the_live_job_is_started_with(location):
    daemon = _Daemon(_ok_reply(temperature_c=1, weather=1, location="Oslo"))
    host = _Host(daemon)
    host.get_weather_preview(PANEL, 16)

    assert daemon.calls[0][2].get("location") == location
    assert host._get_live_params(PANEL).get("location") == location


def test_size_defaults_to_the_live_jobs_size(location):
    """32, not the 16 every default in the chain falls back to, so a preview
    that ignored the panel's size could not pass by agreeing with a default.
    Both are the size of the panel the call NAMES (P5.7)."""
    daemon = _Daemon(_ok_reply(size=32, temperature_c=1, weather=1, location="Oslo"))
    host = _Host(daemon)
    host.pixels = {PANEL: 32}
    r = json.loads(host.get_weather_preview(PANEL, 0))

    assert host._get_live_params(PANEL)["size"] == 32
    assert daemon.calls[0][1] == 32
    assert r["size"] == 32


def test_a_daemon_failure_is_a_reason_not_a_reading(location):
    r = json.loads(_Host(_Daemon(
        {"success": False, "error": "weather: wttr.in returned 503"})).get_weather_preview(PANEL, 16))

    assert r["ok"] is False
    assert "503" in r["error"]
    assert "temperature_c" not in r and "preview" not in r


def test_no_daemon_says_why(location):
    r = json.loads(_Host(None).get_weather_preview(PANEL, 16))

    assert r["ok"] is False
    assert r["error"], "an unreachable daemon must still give the card a reason"


def test_no_city_from_anyone_says_unknown(monkeypatch):
    """Neither the daemon nor an override named a city: the card says unknown
    rather than a stand-in that would read as the user's location."""
    import divoom_lib.weather_provider as wp
    monkeypatch.setattr(wp, "resolve_location", lambda _explicit: "")
    r = json.loads(_Host(_Daemon(_ok_reply(temperature_c=4, weather=1))).get_weather_preview(PANEL, 16))

    assert r["ok"] is True and r["location"] == "unknown"
