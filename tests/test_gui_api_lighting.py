import sys
import json
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

# Add paths to imports
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from gui_main import DivoomGuiAPI

class TestLightingApiCoverage(unittest.TestCase):
    """R61 planning item 1 coverage push: LightingApi
    (divoom_gui/api/lighting.py) exception handlers, the text-render
    scaling branches, and the getter/dispatch methods (set_brightness,
    set_volume, display_wall_image, set_temperature_channel, set_clock_rich,
    display_custom_art) not exercised by the main suite above."""

    def setUp(self):
        self.presets_patcher = patch("pathlib.Path.exists", return_value=False)
        self.presets_patcher.start()
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home_patcher = patch("pathlib.Path.home", return_value=Path(self.temp_dir.name))
        self.home_patcher.start()
        self.api = DivoomGuiAPI()
        self.api.window = MagicMock()

    def tearDown(self):
        self.presets_patcher.stop()
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    # ---- _stop_live_widgets: best-effort, swallows client errors --------

    def test_stop_live_widgets_swallows_client_error(self):
        class _BadClient:
            def live_jobs_stop_for(self):
                raise RuntimeError("boom")
        self.api._daemon_client = _BadClient()
        self.api.lighting._stop_live_widgets()  # must not raise

    # ---- exception handlers for the single-device static-takeover ops ---

    def test_set_solid_light_exception(self):
        dev = MagicMock()
        dev.display.show_light = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_solid_light("#ff0000", 50))

    def test_set_clock_exception(self):
        dev = MagicMock()
        dev.display.show_clock = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_clock(1))

    def test_switch_channel_exception(self):
        dev = MagicMock()
        dev.display.switch_channel = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.switch_channel("clock"))

    def test_set_vj_effect_exception(self):
        dev = MagicMock()
        dev.display.show_effects = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_vj_effect(1))

    def test_set_visualization_exception(self):
        dev = MagicMock()
        dev.display.show_visualization = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_visualization(1))

    # ---- push_text: outer exception + inner unlink-OSError swallow -----

    def test_push_text_dispatch_exception_returns_false(self):
        dev = MagicMock()
        dev.display.show_image = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.push_text("HI"))

    def test_device_size_falls_back_to_16_on_error(self):
        self.api.__dict__["_active_device_size"] = MagicMock(side_effect=RuntimeError("boom"))
        self.assertEqual(self.api.lighting._device_size(), 16)

    # ---- _render_text_png scaling branches -------------------------------

    def test_set_brightness_uses_lan_when_present(self):
        dev = MagicMock()
        dev.lan = MagicMock()
        dev.lan.set_brightness = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.lighting.set_brightness(80))
        dev.lan.set_brightness.assert_called_with(80)

    def test_set_brightness_uses_ble_when_no_lan(self):
        dev = MagicMock()
        dev.lan = None
        dev.device.set_brightness = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.lighting.set_brightness(50))
        dev.device.set_brightness.assert_called_with(50)

    def test_set_brightness_exception(self):
        dev = MagicMock()
        dev.lan = None
        dev.device.set_brightness = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_brightness(50))

    def test_set_brightness_no_target(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.lighting.set_brightness(50))

    # ---- set_volume: clamping + exception + no-target -------------------

    def test_set_volume_clamps_high_and_low(self):
        dev = MagicMock()
        dev.music.set_volume = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.lighting.set_volume(999))
        dev.music.set_volume.assert_called_with(15)
        self.assertTrue(self.api.lighting.set_volume(-5))
        dev.music.set_volume.assert_called_with(0)

    def test_set_volume_exception(self):
        dev = MagicMock()
        dev.music.set_volume = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_volume(5))

    def test_set_volume_no_target(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.lighting.set_volume(5))

    # ---- display_wall_image: single-device path, wall path + previews,
    # non-dict previews reset, previews exception, outer exception --------

    def _wall_fake_client(self, previews_result=True):
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}

        def _device_call(method, args=None, kwargs=None, target="device",
                         blobs=None, token=None):
            if method == "get_last_previews":
                if isinstance(previews_result, Exception):
                    raise previews_result
                return {"success": True, "result": previews_result}
            return {"success": True, "result": True}
        fake.device_call.side_effect = _device_call
        return fake

    def test_display_wall_image_no_target_is_handled_error(self):
        self.api.current_divoom = None
        self.api.wall_slots = {}
        result = self.api.lighting.display_wall_image("/tmp/x.png", 16)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_single_device_path(self):
        dev = MagicMock()
        dev.display.show_image = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.wall_slots = {}
        result = self.api.lighting.display_wall_image("/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {})
        dev.display.show_image.assert_awaited_once_with("/tmp/x.png")

    def test_display_wall_image_wall_path_with_previews(self):
        fake = self._wall_fake_client(previews_result={"AA:BB": "data:image/png;base64,xx"})
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image("/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {"AA:BB": "data:image/png;base64,xx"})

    def test_display_wall_image_wall_path_non_dict_previews_resets_to_empty(self):
        fake = self._wall_fake_client(previews_result="not-a-dict")
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image("/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_previews_exception_logged_not_raised(self):
        fake = self._wall_fake_client(previews_result=RuntimeError("preview fetch boom"))
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image("/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_outer_exception_returns_error_dict(self):
        self.api.current_divoom = None
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        fake = MagicMock()
        fake.wall_configure.side_effect = RuntimeError("daemon exploded")
        self.api._daemon_client = fake
        result = self.api.lighting.display_wall_image("/tmp/x.png", 16)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["previews"], {})

    # ---- set_temperature_channel: success, exception, no-target --------

    def test_set_temperature_channel_success(self):
        dev = MagicMock()
        dev.display.set_temperature_channel = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.lighting.set_temperature_channel(celsius=False, color="#00ff00"))
        dev.display.set_temperature_channel.assert_called_with(celsius=False, color="#00ff00")

    def test_set_temperature_channel_exception(self):
        dev = MagicMock()
        dev.display.set_temperature_channel = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_temperature_channel())

    def test_set_temperature_channel_no_target(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.lighting.set_temperature_channel())

    # ---- set_clock_rich: success, exception, no-target ------------------

    def test_set_clock_rich_success(self):
        dev = MagicMock()
        dev.display.set_clock_rich = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.lighting.set_clock_rich(
            style=2, twentyfour=False, humidity=True, weather=True, date=True, color="#123456"))
        kw = dev.display.set_clock_rich.call_args.kwargs
        self.assertEqual(kw["style"], 2)
        self.assertTrue(kw["humidity"])
        self.assertTrue(kw["weather"])

    def test_set_clock_rich_exception(self):
        dev = MagicMock()
        dev.display.set_clock_rich = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.set_clock_rich())

    def test_set_clock_rich_no_target(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.lighting.set_clock_rich())

    # ---- display_custom_art: success, exception, no-target --------------

    def test_display_custom_art_success(self):
        dev = MagicMock()
        dev.display.show_image = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.lighting.display_custom_art("/tmp/art.png"))
        dev.display.show_image.assert_awaited_once_with("/tmp/art.png")

    def test_display_custom_art_exception(self):
        dev = MagicMock()
        dev.display.show_image = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.lighting.display_custom_art("/tmp/art.png"))

    def test_display_custom_art_no_target(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.lighting.display_custom_art("/tmp/art.png"))


# ── R61 planning item 1 coverage push: ConnectionApi
# (divoom_gui/api/connection.py) was 24% covered — none of its scan /
# capabilities / probe-lan / lan-config / transport-status / window methods
# were exercised. DivoomGuiAPI's own wrappers route scan_devices through
# ScannerMixin and window controls through WindowApi, leaving ConnectionApi's
# identically-named methods dead from the top-level API's perspective. These
# tests call self.api.connection.<method>() directly instead. ──────────────
