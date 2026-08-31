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

class TestToolsApiCoverage(unittest.TestCase):
    """R61 planning item 1 coverage push: ToolsApi (divoom_gui/api/tools.py)
    error paths, validation branches, and getters the main suite above
    doesn't exercise directly (alarm cache disk I/O, exception handlers,
    read-only getters, out-of-range validation reached via the collaborator
    directly rather than through the GuiApi wrapper's pre-validation)."""

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

    # ---- alarm cache (disk fallback for flaky device read-back) --------

    def test_load_alarm_cache_missing_file_returns_empty(self):
        self.assertEqual(self.api.tools._load_alarm_cache(), [])

    def test_load_alarm_cache_reads_real_file(self):
        self.presets_patcher.stop()
        try:
            cache_path = self.api.tools._alarm_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps([{"status": 1}]), encoding="utf-8")
            self.assertEqual(self.api.tools._load_alarm_cache(), [{"status": 1}])
        finally:
            self.presets_patcher.start()

    def test_load_alarm_cache_corrupt_json_returns_empty(self):
        self.presets_patcher.stop()
        try:
            cache_path = self.api.tools._alarm_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text("{not json", encoding="utf-8")
            self.assertEqual(self.api.tools._load_alarm_cache(), [])
        finally:
            self.presets_patcher.start()

    def test_load_alarm_cache_non_list_json_falls_through(self):
        self.presets_patcher.stop()
        try:
            cache_path = self.api.tools._alarm_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            self.assertEqual(self.api.tools._load_alarm_cache(), [])
        finally:
            self.presets_patcher.start()

    def test_store_alarm_cache_write_failure_is_logged_not_raised(self):
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            self.api.tools._store_alarm_cache(0, {"status": 1})  # must not raise

    def test_store_and_load_alarm_cache_roundtrip(self):
        self.presets_patcher.stop()
        try:
            self.api.tools._store_alarm_cache(2, {"status": 1, "hour": 7, "minute": 30, "week": 0})
            alarms = self.api.tools._load_alarm_cache()
            self.assertEqual(len(alarms), 3)
            self.assertEqual(alarms[2]["hour"], 7)
        finally:
            self.presets_patcher.start()

    # ---- get_alarms: device happy/empty/exception + no-device cache ----

    def test_get_alarms_device_success(self):
        dev = MagicMock()
        dev.alarm.get_alarm_time = AsyncMock(return_value=[{"status": 1}])
        self.api.current_divoom = dev
        self.assertEqual(json.loads(self.api.tools.get_alarms()), [{"status": 1}])

    def test_get_alarms_device_empty_falls_back_to_cache(self):
        dev = MagicMock()
        dev.alarm.get_alarm_time = AsyncMock(return_value=[])
        self.api.current_divoom = dev
        self.assertEqual(json.loads(self.api.tools.get_alarms()), [])

    def test_get_alarms_device_exception_falls_back_to_cache(self):
        dev = MagicMock()
        dev.alarm.get_alarm_time = AsyncMock(side_effect=RuntimeError("BLE gone"))
        self.api.current_divoom = dev
        self.assertEqual(json.loads(self.api.tools.get_alarms()), [])

    def test_get_alarms_no_device_uses_cache(self):
        self.api.current_divoom = None
        self.assertEqual(json.loads(self.api.tools.get_alarms()), [])

    # ---- set_alarm: both arms of the ok→cache-write branch + exception --

    def test_set_alarm_rejected_by_device_skips_cache_write(self):
        dev = MagicMock()
        dev.alarm.set_alarm = AsyncMock(return_value=False)
        self.api.current_divoom = dev
        self.assertFalse(self.api.tools.set_alarm(0, True, 6, 0, 0))
        self.assertEqual(self.api.tools._load_alarm_cache(), [])

    def test_set_alarm_exception_returns_false(self):
        dev = MagicMock()
        dev.alarm.set_alarm = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.tools.set_alarm(0, True, 6, 0, 0))

    # ---- sleep aid: no-device + exception for both start and stop ------

    def test_start_sleep_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.tools.start_sleep())

    def test_start_sleep_exception(self):
        dev = MagicMock()
        dev.sleep.show_sleep = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.tools.start_sleep())

    def test_stop_sleep_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.tools.stop_sleep())

    def test_stop_sleep_exception(self):
        dev = MagicMock()
        dev.sleep.show_sleep = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.tools.stop_sleep())

    # ---- _tool_call exception path (no-target arm is covered by the
    # existing test_r8_no_device / test_r9_no_device tests) ---------------

    def test_tool_call_exception_returns_false(self):
        dev = MagicMock()
        dev.timer.set_timer = MagicMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.tools.set_timer("start"))

    # ---- get_device_name ------------------------------------------------

    def test_get_device_name_success(self):
        dev = MagicMock()
        dev.device.get_device_name = AsyncMock(return_value="Bedroom Pixoo")
        self.api.current_divoom = dev
        self.assertEqual(self.api.tools.get_device_name(), "Bedroom Pixoo")

    def test_get_device_name_no_device(self):
        self.api.current_divoom = None
        self.assertIsNone(self.api.tools.get_device_name())

    def test_get_device_name_exception(self):
        dev = MagicMock()
        dev.device.get_device_name = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertIsNone(self.api.tools.get_device_name())

    # ---- set_low_power (on/off coercion through DeviceSettings) --------

    def test_set_low_power_on_and_off(self):
        dev = MagicMock()
        self.api.current_divoom = dev
        with patch("divoom_lib.system.device_settings.DeviceSettings") as DS:
            DS.return_value.set_low_power_switch = AsyncMock(return_value=True)
            self.assertTrue(self.api.tools.set_low_power(True))
            DS.return_value.set_low_power_switch.assert_called_with(1)
            self.assertTrue(self.api.tools.set_low_power("off"))
            DS.return_value.set_low_power_switch.assert_called_with(0)

    # ---- factory_reset: ToolsApi's OWN confirm-token guard (defense in
    # depth vs. the GuiApi wrapper's identical pre-check) ------------------

    def test_tools_api_factory_reset_rejects_bad_token_directly(self):
        dev = MagicMock()
        dev.design.factory_reset = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertFalse(self.api.tools.factory_reset("nope"))
        dev.design.factory_reset.assert_not_called()

    # ---- scoreboard set/get: success, no-device, exception --------------

    def test_set_scoreboard_success(self):
        dev = MagicMock()
        dev.scoreboard.set_scoreboard = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.set_scoreboard(1, 10, 20))
        dev.scoreboard.set_scoreboard.assert_called_with(1, 10, 20)

    def test_set_scoreboard_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.set_scoreboard(1))

    def test_set_scoreboard_exception(self):
        dev = MagicMock()
        dev.scoreboard.set_scoreboard = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertFalse(self.api.set_scoreboard(1))

    def test_get_volume_success(self):
        dev = MagicMock()
        dev.music.get_volume = AsyncMock(return_value=8)
        self.api.current_divoom = dev
        self.assertEqual(self.api.get_volume(), 8)

    def test_get_volume_no_device(self):
        self.api.current_divoom = None
        self.assertIsNone(self.api.get_volume())

    def test_get_volume_exception(self):
        dev = MagicMock()
        dev.music.get_volume = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertIsNone(self.api.get_volume())

    def test_get_brightness_success(self):
        dev = MagicMock()
        dev.device.get_brightness = AsyncMock(return_value=75)
        self.api.current_divoom = dev
        self.assertEqual(self.api.get_brightness(), 75)

    def test_get_brightness_no_device(self):
        self.api.current_divoom = None
        self.assertIsNone(self.api.get_brightness())

    def test_get_brightness_exception(self):
        dev = MagicMock()
        dev.device.get_brightness = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertIsNone(self.api.get_brightness())

    def test_get_work_mode_success(self):
        dev = MagicMock()
        dev.device.get_work_mode = AsyncMock(return_value=2)
        self.api.current_divoom = dev
        self.assertEqual(self.api.get_work_mode(), 2)

    def test_get_work_mode_no_device(self):
        self.api.current_divoom = None
        self.assertIsNone(self.api.get_work_mode())

    def test_get_work_mode_exception(self):
        dev = MagicMock()
        dev.device.get_work_mode = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertIsNone(self.api.get_work_mode())

    # ---- send_notification: ToolsApi's own range guard, reached directly

    def test_tools_send_notification_out_of_range_direct(self):
        self.assertFalse(self.api.tools.send_notification(99))
