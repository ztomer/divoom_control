import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from divoom_lib.utils import media_source
from divoom_lib.utils import media_source_feishin as feishin_mod






def test_get_feishin_playing_track():
    """Feishin returns a track via Navidrome Subsonic API."""
    api_response = {
        "subsonic-response": {
            "status": "ok",
            "nowPlaying": {
                "entry": [{
                    "title": "Feishin Song",
                    "artist": "Feishin Artist",
                    "coverArt": "ar-42",
                }]
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(api_response).encode("utf-8")
    with patch.object(feishin_mod, "_feishin_is_running", return_value=True), \
         patch.object(feishin_mod, "_feishin_creds",
                      return_value=("http://server:4533", "u=admin&s=abc&t=def")), \
         patch("urllib.request.urlopen", return_value=MagicMock(__enter__=lambda self: mock_resp)):
        res = feishin_mod.get_feishin_playing_track()
    assert res == {
        "track": "Feishin Song",
        "artist": "Feishin Artist",
        "source": "Feishin",
        "artwork_url": "http://server:4533/rest/getCoverArt.view?f=json&c=divoom&v=1.16.0&u=admin&s=abc&t=def&id=ar-42&size=500",
    }


def test_get_feishin_nothing_playing():
    """Feishin running but no track playing."""
    api_response = {
        "subsonic-response": {
            "status": "ok",
            "nowPlaying": {}
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(api_response).encode("utf-8")
    with patch.object(feishin_mod, "_feishin_is_running", return_value=True), \
         patch.object(feishin_mod, "_feishin_creds",
                      return_value=("http://server:4533", "u=admin&s=abc&t=def")), \
         patch("urllib.request.urlopen", return_value=MagicMock(__enter__=lambda self: mock_resp)):
        res = feishin_mod.get_feishin_playing_track()
    assert res is None


def test_get_feishin_not_running():
    """Feishin not running → no track."""
    with patch.object(feishin_mod, "_feishin_is_running", return_value=False):
        res = feishin_mod.get_feishin_playing_track()
    assert res is None


def test_get_feishin_no_creds():
    """Feishin running but no credentials found."""
    with patch.object(feishin_mod, "_feishin_is_running", return_value=True), \
         patch.object(feishin_mod, "_feishin_creds", return_value=None):
        res = feishin_mod.get_feishin_playing_track()
    assert res is None






def test_fetch_stock_ticker():
    mock_data = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": 150.0,
                        "chartPreviousClose": 145.0,
                    }
                }
            ]
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=MagicMock(__enter__=lambda self: mock_resp)):
        res = media_source.fetch_stock_ticker("AAPL")
        assert res == {
            "price": 150.0,
            "change": 5.0,
            "pct_change": 3.45,
        }


def test_render_stock_ticker_frame(tmp_path):
    data = {"price": 150.0, "change": 5.0, "pct_change": 3.45}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_stock_ticker_frame("AAPL", data, size=16)
        assert out_path.exists()
        img = Image.open(out_path)
        assert img.size == (16, 16)


def test_get_system_stats():
    with patch("psutil.cpu_percent", return_value=12.5), \
         patch("psutil.virtual_memory") as mock_mem, \
         patch("psutil.sensors_battery", return_value=MagicMock(percent=85)):
        mock_mem.return_value.percent = 45.2
        stats = media_source.get_system_stats()
        assert stats == {"cpu": 12, "mem": 45, "battery": 85}


def test_render_system_stats_frame(tmp_path):
    stats = {"cpu": 12, "mem": 45, "battery": 85}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_system_stats_frame(stats, size=16)
        assert out_path.exists()
        img = Image.open(out_path)
        assert img.size == (16, 16)


# ── R61 coverage push: get_current_playing_track branches ──────────────────




















# ── R61 coverage push: fetch_album_art_url error/malformed paths ───────────






# ── R61 coverage push: render_and_downsample_artwork error/fallback paths ──


class _HidingImageProxy:
    """Proxies to the real PIL.Image module but raises AttributeError for
    the given attribute names, to exercise the resample-filter fallback
    chain (Image.Resampling.LANCZOS -> Image.LANCZOS -> Image.ANTIALIAS)."""

    def __init__(self, hidden):
        self._hidden = hidden

    def __getattr__(self, name):
        if name in self._hidden:
            raise AttributeError(name)
        return getattr(Image, name)


def _jpeg_bytes():
    high_res = Image.new("RGB", (100, 100), (10, 20, 30))
    buf = BytesIO()
    high_res.save(buf, format="JPEG")
    return buf.getvalue()








# ── R61 coverage push: fetch_stock_ticker error/malformed paths ────────────


def test_fetch_stock_ticker_empty_result_returns_none():
    mock_data = {"chart": {"result": []}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=MagicMock(__enter__=lambda self: mock_resp)):
        assert media_source.fetch_stock_ticker("AAPL") is None


def test_fetch_stock_ticker_network_error_returns_none():
    with patch("urllib.request.urlopen", side_effect=OSError("network down")):
        assert media_source.fetch_stock_ticker("AAPL") is None


# ── R61 coverage push: render_stock_ticker_frame branches ──────────────────


def test_render_stock_ticker_frame_down_16(tmp_path):
    data = {"price": 100.0, "change": -2.0, "pct_change": -2.0}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_stock_ticker_frame("AAPL", data, size=16)
    assert out_path.exists()


def test_render_stock_ticker_frame_size_32_up(tmp_path):
    data = {"price": 150.0, "change": 5.0, "pct_change": 3.3}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_stock_ticker_frame("AAPL", data, size=32)
    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (32, 32)


def test_render_stock_ticker_frame_size_32_down(tmp_path):
    data = {"price": 90.0, "change": -3.0, "pct_change": -3.2}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_stock_ticker_frame("AAPL", data, size=32)
    assert out_path.exists()


# ── R61 coverage push: get_system_stats error paths ────────────────────────


def test_get_system_stats_battery_sensor_exception_returns_none_battery():
    with patch("psutil.cpu_percent", return_value=10.0), \
         patch("psutil.virtual_memory") as mock_mem, \
         patch("psutil.sensors_battery", side_effect=RuntimeError("no battery")):
        mock_mem.return_value.percent = 20.0
        stats = media_source.get_system_stats()
    assert stats == {"cpu": 10, "mem": 20, "battery": None}


def test_get_system_stats_outer_exception_returns_defaults():
    with patch("psutil.cpu_percent", side_effect=RuntimeError("boom")):
        stats = media_source.get_system_stats()
    assert stats == {"cpu": 0, "mem": 0, "battery": None}


# ── R61 coverage push: render_system_stats_frame branches ──────────────────


def test_render_system_stats_frame_battery_none_defaults_to_100(tmp_path):
    stats = {"cpu": 50, "mem": 60, "battery": None}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_system_stats_frame(stats, size=16)
    assert out_path.exists()


def test_render_system_stats_frame_size_32(tmp_path):
    stats = {"cpu": 12, "mem": 45, "battery": 85}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_system_stats_frame(stats, size=32)
    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (32, 32)


def test_render_system_stats_frame_size_20_small_bars_min_clamped(tmp_path):
    """size=20 -> scale ~0.625 -> computed bar_h < 3, exercising the min-clamp branch."""
    stats = {"cpu": 30, "mem": 40, "battery": 50}
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_system_stats_frame(stats, size=20)
    assert out_path.exists()


# ── R61 coverage push: render_notification_frame (previously untested) ────


def test_render_notification_frame_mail(tmp_path):
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_notification_frame("mail", size=16)
    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (16, 16)


def test_render_notification_frame_whatsapp_scaled(tmp_path):
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_notification_frame("WhatsApp", size=32)
    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (32, 32)


def test_render_notification_frame_telegram(tmp_path):
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_notification_frame("Telegram", size=16)
    assert out_path.exists()


def test_render_notification_frame_unknown_app_generic_bell(tmp_path):
    with patch("divoom_lib.utils.media_source.Path") as mock_path:
        mock_path.return_value.parent.parent.parent = tmp_path
        out_path = media_source.render_notification_frame("SomeOtherApp", size=16)
    assert out_path.exists()
