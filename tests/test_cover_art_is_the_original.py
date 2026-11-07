"""#1 (2026-09-12, second reading): the cover card shows the ORIGINAL art.

The first fix made the cover ``pixelated``; the user's read was the right
one: the cover is a photo and should scale smoothly, while the device
preview beside it is the device-size frame and stays pixelated. The cover
was blurry because it was handed the 16x16 frame. ``get_current_track_info``
now also returns ``artwork`` (the daemon's bytes as a data URL, MIME as
sniffed by the daemon), and the card puts that on the cover.
"""

import base64
import json
from unittest.mock import MagicMock

from divoom_gui.media_sync import MediaSyncMixin


class _Host(MediaSyncMixin):
    def __init__(self, reply):
        self._reply = reply
        self.wall_slots = {}

    def _client(self):
        c = MagicMock()
        c.now_playing.return_value = self._reply
        return c

    def _artwork_preview(self, artwork_b64, size):  # the device-size frame path
        return "data:image/png;base64,FRAME"


def test_track_info_carries_original_artwork_and_device_frame_separately():
    art = base64.b64encode(b"\xff\xd8\xff\xe0real-jpeg-bytes").decode()
    host = _Host(
        {
            "available": True,
            "playing": True,
            "has_track": True,
            "title": "T",
            "artist": "A",
            "is_playing": True,
            "artwork_b64": art,
            "artwork_mime": "image/jpeg",
        }
    )
    info = json.loads(host.get_current_track_info("AA:00:00:00:00:01"))
    assert info["artwork"] == f"data:image/jpeg;base64,{art}", "cover gets the original bytes"
    assert info["preview"] == "data:image/png;base64,FRAME", "device preview stays the frame"
    assert info["artwork"] != info["preview"]


def test_track_info_without_artwork_has_neither():
    host = _Host(
        {"available": True, "playing": True, "has_track": True, "title": "T", "artist": "A", "is_playing": True}
    )
    info = json.loads(host.get_current_track_info("AA:00:00:00:00:01"))
    assert info["artwork"] == "" and info["preview"] == ""


def test_a_paused_track_is_shown_paused_not_idle_and_not_live():
    """D.FX2: the daemon says `playing: false` for a paused track (it is not
    playing) and `has_track: true` (there is one). The card shows the track,
    marked paused -- neither the idle card nor a live player."""
    host = _Host(
        {
            "available": True,
            "playing": False,
            "has_track": True,
            "is_playing": False,
            "title": "Golden Spires",
            "artist": "Mastodon",
        }
    )
    info = json.loads(host.get_current_track_info("AA:00:00:00:00:01"))
    assert info["track"] == "Golden Spires", "a paused track is still shown"
    assert info["is_playing"] is False, "and it is shown paused"


def test_no_track_is_the_idle_card():
    host = _Host({"available": True, "playing": False, "has_track": False})
    info = json.loads(host.get_current_track_info("AA:00:00:00:00:01"))
    assert info == {"available": True, "playing": False, "hint": ""}


def _declarations(css: str, selector: str) -> str:
    import re

    body = css.split(selector + " {", 1)[1].split("}", 1)[0]
    return re.sub(r"/\*.*?\*/", "", body, flags=re.S)


def test_cover_css_is_not_pixelated_but_device_preview_is():
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "widgets_extra.css").read_text()
    cover = _declarations(css, ".music-previews-container .music-cover-preview img")
    assert "image-rendering" not in cover, "the cover is a photo; it must scale smoothly"
    device = _declarations(css, ".music-device-preview-wrap .device-preview-img")
    assert "pixelated" in device, "the device frame is diodes"
