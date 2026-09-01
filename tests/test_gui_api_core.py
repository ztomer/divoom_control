import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

from tests.support.gui_api_base import GuiApiTestBase

from gui_main import DivoomGuiAPI


class TestGuiApiCoreBasics(GuiApiTestBase):
    def test_window_controls(self):
        """Test native window minimize, maximize, and thread-delayed close controls."""
        self.api.minimize_window()
        self.api.window.minimize.assert_called_once()

        self.api.maximize_window()
        self.api.window.toggle_fullscreen.assert_called_once()

        with patch("threading.Thread") as mock_thread:
            self.api.close_window()
            mock_thread.assert_called_once()

    def test_push_text(self):
        """R32 §D Text Channel: push_text pushes a device-sized IMAGE via
        display.show_image — the LPWA 0x87 path never rendered on these LED
        matrices, so nothing appeared.

        R70 P3.3: the frame comes from the daemon now (`render_widget`
        kind=text) instead of a second bitmap-font renderer in this process, so
        the daemon is the seam this stubs.
        """
        import base64 as _b64
        import os

        dev = MagicMock()
        dev.is_connected = True
        captured = {}

        async def _show_image(path):
            # Capture while the file still exists on disk.
            captured["path"] = path
            captured["exists"] = os.path.isfile(path)
            captured["ends_png"] = str(path).endswith(".png")
            return True

        dev.display.show_image = AsyncMock(side_effect=_show_image)
        self.api.current_divoom = dev
        self.api.current_target_mode = "single"

        client = MagicMock()
        client.render_widget.return_value = {
            "success": True, "kind": "text", "size": 16,
            "frame_rgb_b64": _b64.b64encode(bytes(16 * 16 * 3)).decode(),
            "text": "HI",
        }
        with patch.object(type(self.api.lighting), "_client",
                          property(lambda self: client)):
            ok = self.api.push_text("HI", color="#FF0000", speed=40, effect_style=1)

        self.assertTrue(ok)
        dev.display.show_image.assert_awaited_once()
        self.assertTrue(captured.get("exists"), "text image should exist during the push")
        self.assertTrue(captured.get("ends_png"))
        client.render_widget.assert_called_once_with(
            "text", size=16, params={"text": "HI", "color": "#FF0000", "font_size": 1})

    def test_push_text_empty_noop(self):
        """Empty text is a no-op (returns False, pushes nothing)."""
        dev = MagicMock()
        dev.display.show_image = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.current_target_mode = "single"
        self.assertFalse(self.api.push_text("   "))
        dev.display.show_image.assert_not_called()

    def test_set_alarm(self):
        """R7 Alarms: set_alarm maps enabled→status and weekday mask through."""
        dev = MagicMock()
        dev.alarm.set_alarm = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        ok = self.api.set_alarm(2, True, 7, 30, 0b0011111)  # weekdays Mon-Fri
        self.assertTrue(ok)
        dev.alarm.set_alarm.assert_called_once_with(2, 1, 7, 30, 31, 0, 0)

    def test_set_alarm_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.set_alarm(0, True, 6, 0, 0))

    def test_sleep_start_stop(self):
        """R7 Sleep Aid: start_sleep passes minutes/volume/color; stop sets on=0."""
        dev = MagicMock()
        dev.sleep.show_sleep = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertTrue(self.api.start_sleep(20, "#ff0000", 8))
        kw = dev.sleep.show_sleep.call_args.kwargs
        self.assertEqual(kw.get("sleeptime"), 20)
        self.assertEqual(kw.get("volume"), 8)
        self.assertEqual(kw.get("on"), 1)
        self.assertEqual(list(kw.get("color")), [255, 0, 0])
        self.assertTrue(self.api.stop_sleep())
        self.assertEqual(dev.sleep.show_sleep.call_args.kwargs.get("on"), 0)

    def test_tools_timer_countdown_noise(self):
        """R7 Tools: action strings map to the right ctrl flags."""
        dev = MagicMock()
        dev.timer.set_timer = AsyncMock(return_value=True)
        dev.countdown.set_countdown = AsyncMock(return_value=True)
        dev.noise.set_noise = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.set_timer("start"); dev.timer.set_timer.assert_called_with(1)
        self.api.set_timer("reset"); dev.timer.set_timer.assert_called_with(2)
        self.api.set_countdown("start", 5, 30); dev.countdown.set_countdown.assert_called_with(0, 5, 30)
        self.api.set_countdown("stop", 5, 30); dev.countdown.set_countdown.assert_called_with(1, 5, 30)
        self.api.set_noise("start"); dev.noise.set_noise.assert_called_with(1)
        self.api.set_noise("stop"); dev.noise.set_noise.assert_called_with(2)

    def test_r8_device_settings(self):
        """R8: hour/temp/name/fm map to the right facade calls + bool coercion."""
        dev = MagicMock()
        dev.system.set_hour_type = AsyncMock(return_value=True)
        dev.device.set_temp_type = AsyncMock(return_value=True)
        dev.device.set_device_name = AsyncMock(return_value=True)
        dev.radio.set_radio_frequency = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.set_hour_type(True); dev.system.set_hour_type.assert_called_with(1)
        self.api.set_hour_type("false"); dev.system.set_hour_type.assert_called_with(0)
        self.api.set_temp_unit(True); dev.device.set_temp_type.assert_called_with(1)
        self.api.set_device_name("Bedroom"); dev.device.set_device_name.assert_called_with("Bedroom")
        self.api.set_fm_frequency(1015); dev.radio.set_radio_frequency.assert_called_with(1015)

    def test_r8_memorial_and_timeplan(self):
        """R8: memorial + timeplan pass through with status/have-flag derivation."""
        dev = MagicMock()
        dev.alarm.set_memorial_time = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.set_memorial(0, True, 12, 25, 9, 0, "Xmas")
        dev.alarm.set_memorial_time.assert_called_with(0, 1, 12, 25, 9, 0, 1, "Xmas")

    def test_r72_sync_time_and_auto_off_go_to_the_daemon(self):
        """R72 P1.2/P1.3: these used to build packets through divoom_lib.

        The old version patched `divoom_lib.system.date_time.DateTimeCommand`
        and `...device_settings.DeviceSettings` -- i.e. it pinned the duplicate
        implementation in place. Both now travel to the daemon through the
        device proxy, so the assertion is about the METHOD PATH, which is the
        thing that can silently be wrong: the daemon accepts
        `device.set_auto_power_off` but a wrong prefix falls through to a
        generic "unknown method".
        """
        dev = MagicMock()
        dev.system.set_date_time = AsyncMock(return_value=True)
        dev.device.set_auto_power_off = AsyncMock(return_value=True)
        self.api.current_divoom = dev

        self.assertTrue(self.api.sync_time())
        kwargs = dev.system.set_date_time.call_args.kwargs
        assert set(kwargs) == {"year", "month", "day", "hour", "minute", "second"}, kwargs
        # A real clock, not the daemon's 2000-01-01 default.
        assert kwargs["year"] >= 2024, kwargs

        self.assertTrue(self.api.set_auto_power_off(60))
        dev.device.set_auto_power_off.assert_called_with(60)

    def test_r8_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.set_hour_type(True))
        self.assertFalse(self.api.set_fm_frequency(900))

    def test_r9_screen_dir_mirror(self):
        """R9: screen dir/mirror reach d.design with bool/int coercion."""
        dev = MagicMock()
        dev.design.set_screen_dir = AsyncMock(return_value=True)
        dev.design.set_screen_mirror = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.set_screen_dir(2); dev.design.set_screen_dir.assert_called_with(2)
        self.api.set_screen_mirror("on"); dev.design.set_screen_mirror.assert_called_with(True)
        self.api.set_screen_mirror(0); dev.design.set_screen_mirror.assert_called_with(False)

    def test_r9_factory_reset_requires_token(self):
        """R9: factory_reset only fires with the literal 'RESET' token."""
        dev = MagicMock()
        dev.design.factory_reset = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.assertFalse(self.api.factory_reset())          # no token
        self.assertFalse(self.api.factory_reset("yes"))     # wrong token
        dev.design.factory_reset.assert_not_called()
        self.assertTrue(self.api.factory_reset("RESET"))    # correct token
        dev.design.factory_reset.assert_called_once()

    def test_r9_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.set_screen_dir(1))
        self.assertFalse(self.api.set_screen_mirror(True))
        self.assertFalse(self.api.factory_reset("RESET"))

    def test_r10_send_notification(self):
        """R10: text vs icon-only path + app_type range guard."""
        dev = MagicMock()
        dev.notification.show_notification = AsyncMock(return_value=True)
        dev.notification.show_notification_text = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        # icon-only when no text
        self.api.send_notification(6)
        dev.notification.show_notification.assert_called_with(6)
        dev.notification.show_notification_text.assert_not_called()
        # text path when text given
        self.api.send_notification(7, "Hi")
        dev.notification.show_notification_text.assert_called_with(7, "Hi")
        # blank/whitespace text falls back to icon-only
        self.api.send_notification(2, "   ")
        dev.notification.show_notification.assert_called_with(2)
        # out-of-range refused without sending
        dev.notification.show_notification.reset_mock()
        self.assertFalse(self.api.send_notification(0))
        self.assertFalse(self.api.send_notification(15))
        dev.notification.show_notification.assert_not_called()

    def test_r10_no_device(self):
        self.api.current_divoom = None
        self.assertFalse(self.api.send_notification(6))


    def test_scan_devices(self):
        """R17 P5: scanning is owned by the daemon; the GUI proxies via scan()."""
        fake = MagicMock()
        fake.scan.return_value = {"success": True, "devices": [
            {"name": "Pixoo-Test", "address": "11:22:33:44:55:66"}]}
        self.api._daemon_client = fake
        with patch.object(type(self.api), "_cache_discovered", return_value=None):
            res = json.loads(self.api.scan_devices(timeout=2, limit=1))
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["name"], "Pixoo-Test")
        fake.scan.assert_called_once_with(timeout=2.0, limit=1)

    def test_connect_single_device(self):
        """R17 P5: connect is delegated to the daemon; current_divoom becomes a
        DaemonDeviceProxy (the daemon owns the real BLE connection)."""
        from divoom_gui.daemon_bridge import DaemonDeviceProxy
        fake = MagicMock()
        fake.disconnect_device.return_value = {"success": True}
        fake.connect_device.return_value = {"success": True, "connected": True}
        # R57's reconnect_daemon() resets self._daemon_client and re-runs
        # ensure_daemon(); patch the seam (as the sibling reconnect tests do),
        # not the instance attr that reconnect_daemon() overwrites.
        with patch("divoom_gui.daemon_bridge.ensure_daemon", return_value=fake), \
             patch.object(type(self.api), "_device_name_for", return_value=None), \
             patch.object(type(self.api), "_persist_last_connected", return_value=None):
            success = self.api.connect_single_device("00:11:22:33:44:55")
        self.assertTrue(success)
        self.assertIsInstance(self.api.current_divoom, DaemonDeviceProxy)
        fake.connect_device.assert_called_once()
        self.assertEqual(fake.connect_device.call_args.kwargs.get("mac"), "00:11:22:33:44:55")

    def test_preset_persistence(self):
        """Test preset name loading when no files exist."""
        preset_names = self.api.load_preset_names()
        self.assertEqual(json.loads(preset_names), [])

        preset_data = self.api.load_preset_by_name("NonExistent")
        self.assertEqual(json.loads(preset_data), {})
