"""Tests for unified DisplayPreview object model, multi-device isolation,
and the play_gallery_art API bridge.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from divoom_gui.gallery_sync import GallerySyncMixin


class DummyApi(GallerySyncMixin):
    def __init__(self):
        self._daemon_client = MagicMock()
        self._window = MagicMock()

    def _client(self):
        return self._daemon_client

    def display_wall_image(self, mac: str, path: str, cell_size: int | None = None) -> dict:
        return {"success": True, "mac": mac, "path": path}


def test_play_gallery_art_missing_file_id():
    api = DummyApi()
    res = api.play_gallery_art("11:22:33:44:55:01", "")
    assert res == {"success": False, "error": "missing file_id"}


def test_play_gallery_art_naming_no_panel_is_refused():
    """P5.7: it pushed to the panel the bench selected when it RAN."""
    res = DummyApi().play_gallery_art("", "art123")
    assert res == {"success": False, "error": "No panel selected"}


def test_play_gallery_art_cached_file(tmp_path: Path):
    api = DummyApi()
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_id = "group1/M00/01/TEST/art123"
    safe_name = file_id.replace("/", "_")
    gif_file = cache_dir / f"{safe_name}.gif"
    gif_file.write_bytes(b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

    with patch.object(Path, "home", return_value=tmp_path):
        res = api.play_gallery_art("11:22:33:44:55:01", file_id)
        assert res.get("success") is True
        assert res.get("path") == str(gif_file.absolute())
        assert res.get("mac") == "11:22:33:44:55:01"


def test_preview_controller_js_syntax_and_structure():
    """Verify preview_controller.js exports DisplayPreview and DisplayPreviewRegistry."""
    js_path = Path("divoom_gui/web_ui/preview_controller.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")
    assert "class DisplayPreview" in content
    assert "class DisplayPreviewRegistry" in content
    assert "window.DisplayPreview = DisplayPreview;" in content
    assert "window.DisplayPreviewRegistry = new DisplayPreviewRegistry();" in content
    assert "BITMAP_FONT_3X5" in content
    assert "renderClockGlyph" in content
    assert "renderEqGlyph" in content
    assert "renderCloudGlyph" in content


def test_channel_preview_bitmap_digits():
    """Verify channel_preview.js uses integer pixel squares rather than vector text."""
    js_path = Path("divoom_gui/web_ui/channel_preview.js")
    content = js_path.read_text(encoding="utf-8")
    assert "renderBitmapDigitsSVG" in content
    assert "CLOCK_DIGITS_3X5" in content
    assert "image-rendering:pixelated;" in content


def test_channel_controls_sync_structure():
    """Verify channel_preview.js exports syncChannelControlsToDisplay and binds options."""
    js_path = Path("divoom_gui/web_ui/channel_preview.js")
    content = js_path.read_text(encoding="utf-8")
    assert "window.syncChannelControlsToDisplay = function" in content
    # The values come from the display's own settings (P5.2), never a global.
    assert 'window.ChannelSettings.of(disp, channel)' in content


def test_spatial_rooms_get_wall_slots_structure():
    """Verify spatial_rooms.js exports getWallSlots as unified spatial layout source."""
    js_path = Path("divoom_gui/web_ui/spatial_rooms.js")
    content = js_path.read_text(encoding="utf-8")
    assert "getWallSlots" in content
    assert "window.SpatialRooms" in content
