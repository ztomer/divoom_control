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

MAC = "AA:00:00:00:00:01"

class TestLightingApiCoverage(unittest.TestCase):
    """R61 planning item 1 coverage push: LightingApi
    (divoom_gui/api/lighting.py) exception handlers, the text-render
    scaling branches, and the getter/dispatch methods (set_brightness,
    set_volume, display_wall_image, set_clock_rich) not exercised by the
    main suite above."""

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
            def live_jobs_stop_for(self, mac):
                raise RuntimeError("boom")
        self.api._daemon_client = _BadClient()
        self.api.lighting._stop_live_widgets(MAC)  # must not raise

    def _on(self, dev):
        """P5.6: the display a write names resolves to `dev` (and no mac to nothing)."""
        self.api.lighting._display = lambda mac, **_kw: dev if mac else None

    # ---- exception handlers for the single-device static-takeover ops ---

    def test_set_solid_light_exception(self):
        dev = MagicMock()
        dev.display.show_light = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.set_solid_light(MAC, "#ff0000", 50)["success"])

    def test_set_clock_exception(self):
        dev = MagicMock()
        dev.display.show_clock = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.set_clock(MAC, 1)["success"])

    def test_switch_channel_exception(self):
        dev = MagicMock()
        dev.display.switch_channel = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.switch_channel(MAC, "clock")["success"])

    def test_set_vj_effect_exception(self):
        dev = MagicMock()
        dev.display.show_effects = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.set_vj_effect(MAC, 1)["success"])

    def test_set_visualization_exception(self):
        dev = MagicMock()
        dev.display.show_visualization = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.set_visualization(MAC, 1)["success"])

    # ---- push_text: outer exception + inner unlink-OSError swallow -----

    def test_push_text_dispatch_exception_returns_false(self):
        dev = MagicMock()
        dev.display.show_image = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.push_text(MAC, "HI")["success"])

    def test_device_size_falls_back_to_16_on_error(self):
        self.api.__dict__["_size_of"] = MagicMock(side_effect=RuntimeError("boom"))
        self.assertEqual(self.api.lighting._device_size(MAC), 16)

    # ---- _render_text_png scaling branches -------------------------------

    # ---- display_wall_image: single-device path, wall path + previews,
    # non-dict previews reset, previews exception, outer exception --------

    def _wall_fake_client(self, previews_result=True):
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}

        def _device_call(method, args=None, kwargs=None, target="device",
                         blobs=None, token=None, mac=None):
            if method == "get_last_previews":
                if isinstance(previews_result, Exception):
                    raise previews_result
                return {"success": True, "result": previews_result}
            return {"success": True, "result": True}
        fake.device_call.side_effect = _device_call
        return fake

    def test_display_wall_image_no_target_is_handled_error(self):
        self._on(None)
        self.api.wall_slots = {}
        result = self.api.lighting.display_wall_image(MAC, "/tmp/x.png", 16)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_single_device_path(self):
        dev = MagicMock()
        dev._mac = MAC
        dev.display.show_image = AsyncMock(return_value=True)
        self._on(dev)
        # Wall slots exist, and a panel is named: the panel gets it (P5.7; it
        # went to the wall whenever slots existed).
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image(MAC, "/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {})
        dev.display.show_image.assert_awaited_once_with("/tmp/x.png")

    def test_display_wall_image_wall_path_with_previews(self):
        fake = self._wall_fake_client(previews_result={"AA:BB": "data:image/png;base64,xx"})
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image("MatrixWall", "/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {"AA:BB": "data:image/png;base64,xx"})

    def test_display_wall_image_wall_path_non_dict_previews_resets_to_empty(self):
        fake = self._wall_fake_client(previews_result="not-a-dict")
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image("MatrixWall", "/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_previews_exception_logged_not_raised(self):
        fake = self._wall_fake_client(previews_result=RuntimeError("preview fetch boom"))
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        result = self.api.lighting.display_wall_image("MatrixWall", "/tmp/x.png", 16)
        self.assertTrue(result["success"])
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_outer_exception_returns_error_dict(self):
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        fake = MagicMock()
        fake.wall_configure.side_effect = RuntimeError("daemon exploded")
        self.api._daemon_client = fake
        result = self.api.lighting.display_wall_image("MatrixWall", "/tmp/x.png", 16)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["previews"], {})

    def test_display_wall_image_failure_names_the_panels_that_failed(self):
        """P6.3: the daemon's wall reply names each panel whose write failed
        (`failed`, with the reason) apart from each slot with no panel
        (`degraded`); the bridge hands both to the page instead of keeping
        only the message."""
        a, b, c = "AA:00:00:00:00:01", "BB:00:00:00:00:02", "CC:00:00:00:00:03"
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}
        fake.device_call.return_value = {
            "success": False, "code": "device_failed", "result": False,
            "error": f"wall: {b} did not take it (the write failed); {c} has no panel linked",
            "failed": {b: "the write failed"}, "degraded": [c]}
        self.api._daemon_client = fake
        self.api.wall_slots = {m: {"x": i, "y": 0, "size": 16} for i, m in enumerate((a, b, c))}
        result = self.api.lighting.display_wall_image("MatrixWall", "/tmp/x.png", 16)
        self.assertFalse(result["success"])
        self.assertEqual(result["failed"], {b: "the write failed"})
        self.assertEqual(result["degraded"], [c])
        self.assertIn(b, result["error"])

    # ---- set_clock_rich: success, exception, no-target ------------------

    def test_set_clock_rich_success(self):
        dev = MagicMock()
        dev.display.set_clock_rich = AsyncMock(return_value=True)
        self._on(dev)
        self.assertTrue(self.api.lighting.set_clock_rich(
            MAC, style=2, twentyfour=False, humidity=True, weather=True, date=True, color="#123456")["success"])
        kw = dev.display.set_clock_rich.call_args.kwargs
        self.assertEqual(kw["style"], 2)
        self.assertTrue(kw["humidity"])
        self.assertTrue(kw["weather"])

    def test_set_clock_rich_exception(self):
        dev = MagicMock()
        dev.display.set_clock_rich = MagicMock(side_effect=RuntimeError("boom"))
        self._on(dev)
        self.assertFalse(self.api.lighting.set_clock_rich(MAC)["success"])

    def test_set_clock_rich_no_target(self):
        self._on(None)
        self.assertFalse(self.api.lighting.set_clock_rich(MAC)["success"])

    def test_stop_live_widgets_passes_target_mac(self):
        mock_client = MagicMock()
        self.api._daemon_client = mock_client
        self.api.lighting._stop_live_widgets("11:22:33:44:55:66")
        mock_client.live_jobs_stop_for.assert_called_once_with("11:22:33:44:55:66")

    def test_stop_live_widgets_on_the_wall_stops_every_slot(self):
        mock_client = MagicMock()
        self.api._daemon_client = mock_client
        self.api.wall_slots = {"AA:00:00:00:00:01": {}, "BB:00:00:00:00:02": {}}
        self.api.lighting._stop_live_widgets("MatrixWall")
        self.assertEqual([c.args for c in mock_client.live_jobs_stop_for.call_args_list],
                         [("AA:00:00:00:00:01",), ("BB:00:00:00:00:02",)])

    def test_stop_live_widgets_naming_no_panel_stops_nothing(self):
        """A mac-less stop is the daemon's ACTIVE panel: never what a write meant."""
        mock_client = MagicMock()
        self.api._daemon_client = mock_client
        self.api.lighting._stop_live_widgets(None)
        mock_client.live_jobs_stop_for.assert_not_called()

    def test_display_wall_image_stops_live_widgets(self):
        dev = MagicMock()
        dev._mac = "11:22:33:44:55:66"
        dev.display.show_image = AsyncMock(return_value=True)
        mock_client = MagicMock()
        self.api._daemon_client = mock_client
        self.api.lighting._display = lambda mac, **_kw: dev if mac == "11:22:33:44:55:66" else None
        result = self.api.lighting.display_wall_image("11:22:33:44:55:66", "/tmp/fake.png", 16)
        self.assertTrue(result["success"])
        mock_client.live_jobs_stop_for.assert_called_with("11:22:33:44:55:66")

    def test_play_gallery_art_pushes_to_the_display_it_names(self):
        """The push -- and its live-widget stop, which `display_wall_image`
        does -- goes to the display the click named (P5.7)."""
        mock_client = MagicMock()
        self.api._daemon_client = mock_client
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat") as mock_stat, \
             patch.object(self.api, "display_wall_image", return_value={"success": True}) as mock_wall_img:
            mock_stat.return_value.st_size = 100
            res = self.api.play_gallery_art("11:22:33:44:55:66", "art_123")
            self.assertTrue(res["success"])
            self.assertEqual(mock_wall_img.call_args.args[0], "11:22:33:44:55:66")


