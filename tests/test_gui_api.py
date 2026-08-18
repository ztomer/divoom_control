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

class TestDivoomGuiAPI(unittest.TestCase):
    def setUp(self):
        # Prevent actually touching credentials files or presetting configs on disk during unit testing
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
        """R32 §D Text Channel: push_text renders the text to a device-sized
        image and pushes it via display.show_image (the LPWA 0x87 path didn't
        render on the LED matrices — nothing appeared)."""
        import os
        dev = MagicMock()
        dev.is_connected = True
        captured = {}

        async def _show_image(path):
            # Capture while the temp file still exists (push_text unlinks it).
            captured["path"] = path
            captured["exists"] = os.path.isfile(path)
            captured["ends_png"] = str(path).endswith(".png")
            return True

        dev.display.show_image = AsyncMock(side_effect=_show_image)
        self.api.current_divoom = dev
        self.api.current_target_mode = "single"
        ok = self.api.push_text("HI", color="#FF0000", speed=40, effect_style=1)
        self.assertTrue(ok)
        dev.display.show_image.assert_awaited_once()
        self.assertTrue(captured.get("exists"), "text image should exist during the push")
        self.assertTrue(captured.get("ends_png"))

    def test_push_text_empty_noop(self):
        """Empty text is a no-op (returns False, pushes nothing)."""
        dev = MagicMock()
        dev.display.show_image = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.current_target_mode = "single"
        self.assertFalse(self.api.push_text("   "))
        dev.display.show_image.assert_not_called()

    def test_render_text_png_produces_sized_image(self):
        """The text renderer produces a square device-sized RGB PNG with the
        requested color present (no anti-aliasing)."""
        from PIL import Image
        from divoom_gui.api.lighting import LightingApi
        path = LightingApi._render_text_png("HI", "#FF0000", 16, 1)
        try:
            img = Image.open(path).convert("RGB")
            self.assertEqual(img.size, (16, 16))
            colors = {c for _, c in img.getcolors(maxcolors=4096)}
            self.assertIn((255, 0, 0), colors, "the fill color should appear in the render")
        finally:
            import os
            os.unlink(path)

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
        dev.timeplan.set_time_manage_info = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        self.api.set_memorial(0, True, 12, 25, 9, 0, "Xmas")
        dev.alarm.set_memorial_time.assert_called_with(0, 1, 12, 25, 9, 0, 1, "Xmas")
        self.api.set_timeplan(1, True, 7, 30, 0b0011111, 0)
        dev.timeplan.set_time_manage_info.assert_called_with(1, 7, 30, 31, 0, 0, 0, 10, 0)

    def test_r8_sync_time_and_auto_off_instantiated(self):
        """R8: time-sync + auto-power-off use the un-faceted helper classes."""
        dev = MagicMock()
        self.api.current_divoom = dev
        with patch("divoom_lib.system.date_time.DateTimeCommand") as DT:
            DT.return_value.update_date_time = AsyncMock(return_value=True)
            self.assertTrue(self.api.sync_time())
            DT.assert_called_once_with(dev)
        with patch("divoom_lib.system.device_settings.DeviceSettings") as DS:
            DS.return_value.set_auto_power_off = AsyncMock(return_value=True)
            self.assertTrue(self.api.set_auto_power_off(60))
            DS.return_value.set_auto_power_off.assert_called_with(60)

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

    # ── macOS notification mirroring (daemon-owned) ─────────────────────
    # The daemon is the single owner of the monitor; the GUI delegates over
    # RPC and must NOT poll the DB itself
    # (docs/archive/superseded/PLANNING_daemon_ownership.md).

    def _fake_client(self, *, state="idle", counters=None, error=None):
        """A DaemonClient stub whose notification RPCs return canned replies."""
        c = MagicMock()
        reply = {"success": error is None, "state": state,
                 "counters": counters or {"seen": 0, "routed": 0, "dropped": 0}}
        if error:
            reply["error"] = error
        c.start_notifications.return_value = reply
        c.stop_notifications.return_value = {"success": True, "state": "idle"}
        c.notification_status.return_value = reply
        c.set_routing.return_value = {"success": True}
        return c

    def test_notification_listener_initial_state(self):
        """No daemon → not running; stop is a safe no-op."""
        with patch.object(self.api, "_client", return_value=None):
            self.assertFalse(self.api.is_notification_listener_running())
            self.assertFalse(self.api.stop_notification_listener()["running"])

    @patch("sys.platform", new="darwin")
    @patch("divoom_client.macos_notifications.find_notification_db_path",
           return_value=Path("/fake/db.sqlite"))
    def test_start_notification_listener_delegates_to_daemon(self, _db):
        client = self._fake_client(state="active")
        with patch.object(self.api, "_client", return_value=client):
            result = self.api.start_notification_listener()
        self.assertTrue(result["running"])
        self.assertEqual(result["db_path"], "/fake/db.sqlite")
        client.start_notifications.assert_called_once()

    @patch("sys.platform", new="darwin")
    def test_start_notification_listener_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            result = self.api.start_notification_listener()
        self.assertFalse(result["running"])
        self.assertIn("daemon", result["error"])

    @patch("sys.platform", new="linux")
    def test_start_notification_listener_macos_only(self):
        result = self.api.start_notification_listener()
        self.assertFalse(result["running"])
        self.assertIn("macOS", result["error"])

    @patch("sys.platform", new="darwin")
    @patch("divoom_client.macos_notifications.find_notification_db_path",
           return_value=Path("/fake/db.sqlite"))
    def test_start_notification_listener_reports_daemon_error(self, _db):
        client = self._fake_client(state="error", error="db not found")
        with patch.object(self.api, "_client", return_value=client):
            result = self.api.start_notification_listener()
        self.assertFalse(result["running"])
        self.assertIn("db not found", result["error"])

    def test_stop_notification_listener_delegates(self):
        client = self._fake_client(state="active")
        with patch.object(self.api, "_client", return_value=client):
            result = self.api.stop_notification_listener()
        self.assertFalse(result["running"])
        client.stop_notifications.assert_called_once()

    def test_gui_does_not_instantiate_local_monitor(self):
        """Regression for the §1.2 double-route fix: the GUI must never build
        its own MacNotificationMonitor — that is the daemon's job."""
        with patch("divoom_client.macos_notifications.MacNotificationMonitor") as mock_cls, \
             patch.object(self.api, "_client", return_value=self._fake_client(state="active")), \
             patch("sys.platform", new="darwin"), \
             patch("divoom_client.macos_notifications.find_notification_db_path", return_value=None), \
             patch("divoom_client.macos_notifications.load_routing_table", return_value=[]):
            self.api.start_notification_listener()
            self.api.stop_notification_listener()
            self.api.is_notification_listener_running()
            self.api.get_notification_listener_status()
        mock_cls.assert_not_called()

    # ── status snapshot + routing save (Settings card) ────────────────

    @patch("sys.platform", new="darwin")
    @patch("divoom_client.macos_notifications.find_notification_db_path",
           return_value=Path("/fake/db.sqlite"))
    def test_get_notification_listener_status_shape(self, _db):
        """The status dict has every key the JS side renders; counters + state
        come from the daemon, rules from disk."""
        client = self._fake_client(state="active",
                                   counters={"seen": 12, "routed": 8, "dropped": 4})
        with patch("divoom_client.macos_notifications.load_routing_table",
                   return_value=[("whatsapp", 6), ("com.apple.mail", 7)]), \
             patch.object(self.api, "_client", return_value=client):
            s = self.api.get_notification_listener_status()

        self.assertTrue(s["platform_supported"])
        self.assertTrue(s["running"])
        self.assertEqual(s["db_path"], "/fake/db.sqlite")
        self.assertEqual(s["counters"], {"seen": 12, "routed": 8, "dropped": 4})
        self.assertEqual(s["rules"], [["whatsapp", 6], ["com.apple.mail", 7]])
        self.assertIn("routing_path", s)
        self.assertIsNone(s["error"])

    @patch("sys.platform", new="linux")
    def test_status_unsupported_off_macos(self):
        """On non-darwin, status reports unsupported and the toggle is disabled upstream."""
        s = self.api.get_notification_listener_status()
        self.assertFalse(s["platform_supported"])
        self.assertFalse(s["running"])
        self.assertIsNotNone(s["error"])
        # Rules still load from the file (or defaults) even off-macOS.
        self.assertIsInstance(s["rules"], list)

    def test_save_notification_routing_delegates_to_daemon(self):
        """save_notification_routing validates then forwards to set_routing."""
        client = self._fake_client()
        with patch("divoom_client.macos_notifications.load_routing_table",
                   return_value=[("whatsapp", 6)]), \
             patch.object(self.api, "_client", return_value=client):
            result = self.api.save_notification_routing('[["whatsapp", 6]]')
        self.assertIsNone(result["error"])
        self.assertEqual(result["rules"], [["whatsapp", 6]])
        client.set_routing.assert_called_once_with([("whatsapp", 6)])

    def test_save_notification_routing_rejects_invalid_json(self):
        """Invalid JSON returns the previous rules and a non-null error,
        without ever touching the daemon."""
        client = self._fake_client()
        with patch("divoom_client.macos_notifications.load_routing_table",
                   return_value=[("whatsapp", 6)]), \
             patch.object(self.api, "_client", return_value=client):
            result = self.api.save_notification_routing("this is not json")
        self.assertIsNotNone(result["error"])
        self.assertIn("Invalid", result["error"])
        self.assertEqual(result["rules"], [["whatsapp", 6]])
        client.set_routing.assert_not_called()

    def test_save_notification_routing_daemon_unavailable(self):
        """No daemon → previous rules + error, nothing written."""
        with patch("divoom_client.macos_notifications.load_routing_table",
                   return_value=[("whatsapp", 6)]), \
             patch.object(self.api, "_client", return_value=None):
            result = self.api.save_notification_routing('[["whatsapp", 6]]')
        self.assertIn("daemon", result["error"])
        self.assertEqual(result["rules"], [["whatsapp", 6]])

    # ── R53: daemon health + reconnect (daemon-down banner backend) ────

    def test_daemon_health_reports_up(self):
        with patch("divoom_gui.daemon_bridge.daemon_alive", return_value=True):
            res = json.loads(self.api.daemon_health())
        self.assertTrue(res["daemon"])

    def test_daemon_health_reports_down(self):
        with patch("divoom_gui.daemon_bridge.daemon_alive", return_value=False):
            res = json.loads(self.api.daemon_health())
        self.assertFalse(res["daemon"])

    def test_daemon_health_probe_error_is_down(self):
        """A probe that raises reads as down, never propagates."""
        with patch("divoom_gui.daemon_bridge.daemon_alive", side_effect=OSError("boom")):
            res = json.loads(self.api.daemon_health())
        self.assertFalse(res["daemon"])

    def test_daemon_health_remote_assumed_up(self):
        """A configured remote daemon is never spawned/probed locally — report
        healthy and let real calls surface any transport error."""
        import os
        with patch.dict(os.environ, {"DIVOOM_DAEMON_HOST": "192.168.1.50"}), \
             patch("divoom_gui.daemon_bridge.daemon_alive", return_value=False):
            res = json.loads(self.api.daemon_health())
        self.assertTrue(res["daemon"])  # remote short-circuits the local probe

    def test_reconnect_daemon_success_resets_and_reensures(self):
        """reconnect_daemon drops the (possibly dead) cached client and hands the
        freshly ensured one back — the fix for the never-reset stale client."""
        self.api._daemon_client = "stale-dead-client"
        fake = MagicMock()
        with patch("divoom_gui.daemon_bridge.ensure_daemon", return_value=fake) as ens:
            res = json.loads(self.api.reconnect_daemon())
        self.assertTrue(res["daemon"])
        self.assertIs(self.api._daemon_client, fake)
        ens.assert_called_once()

    def test_reconnect_daemon_failure_reports_down(self):
        self.api._daemon_client = "stale"
        with patch("divoom_gui.daemon_bridge.ensure_daemon", return_value=None):
            res = json.loads(self.api.reconnect_daemon())
        self.assertFalse(res["daemon"])
        self.assertIsNone(self.api._daemon_client)

    def test_reconnect_daemon_swallows_spawn_error(self):
        self.api._daemon_client = "stale"
        with patch("divoom_gui.daemon_bridge.ensure_daemon",
                   side_effect=RuntimeError("spawn boom")):
            res = json.loads(self.api.reconnect_daemon())
        self.assertFalse(res["daemon"])
        self.assertIsNone(self.api._daemon_client)

    # ── R53: hot-channel last-checked (daemon-owned; GUI writes via daemon,
    #        reads the shared state file) ──────────────────────────────────

    def test_hot_channel_update_passes_active_address_to_daemon(self):
        """The GUI hands the daemon the device address so the daemon stamps the
        last-checked state under the SAME key the GUI reads by."""
        fake = MagicMock()
        fake.hot_update.return_value = {"success": True, "started": True}
        self.api._daemon_client = fake
        # _active_device_size is cached in the instance __dict__ by
        # _wire_collaborators, so patch at the instance level (a class patch is
        # shadowed); _active_device_mac patches fine either way.
        with patch.object(self.api, "_active_device_mac",
                          return_value="AA:BB:CC:DD:EE:FF"), \
             patch.object(self.api, "_active_device_size", return_value=64):
            json.loads(self.api.hot_channel_update())
        fake.hot_update.assert_called_once()
        assert fake.hot_update.call_args.kwargs.get("address") == "AA:BB:CC:DD:EE:FF"
        assert fake.hot_update.call_args.kwargs.get("device_size") == 64

    def test_hot_get_check_resolves_active_device(self):
        """With no explicit address, hot_get_check reads the store for the active
        device (the same key the write used)."""
        with patch.object(self.api, "_active_device_mac",
                          return_value="AA:BB:CC:DD:EE:FF"), \
             patch("divoom_lib.hot_update_state.get_check",
                   return_value={"checked_at": 3.0}) as g:
            out = json.loads(self.api.hot_get_check())
        assert out == {"checked_at": 3.0}
        g.assert_called_once_with("AA:BB:CC:DD:EE:FF")

    def test_hot_get_check_explicit_address_wins(self):
        with patch.object(self.api, "_active_device_mac", return_value="other"), \
             patch("divoom_lib.hot_update_state.get_check", return_value={}) as g:
            self.api.hot_get_check("LAN:192.168.1.5")
        g.assert_called_once_with("LAN:192.168.1.5")

    # ── gallery_hot_api: custom art push / query, hot status polling
    #    (client-boundary methods — mock at ``_client()``, not BLE) ──────────

    def test_hot_channel_update_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            out = json.loads(self.api.hot_channel_update())
        assert out == {"success": False, "error": "no daemon available"}

    def test_hot_update_status_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            out = json.loads(self.api.hot_update_status())
        assert out == {"phase": "error", "error": "no daemon"}

    def test_hot_update_status_delegates_to_daemon(self):
        fake = MagicMock()
        fake.hot_update_progress.return_value = {"phase": "downloading", "pct": 42}
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.hot_update_status())
        assert out == {"phase": "downloading", "pct": 42}
        fake.hot_update_progress.assert_called_once()

    def test_custom_art_push_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            out = json.loads(self.api.custom_art_push("[1,2,3]", 0))
        assert out == {"success": False, "error": "no daemon available"}

    def test_custom_art_push_invalid_json(self):
        fake = MagicMock()
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_push("not json", 0))
        assert out == {"success": False, "error": "invalid payload"}
        fake.custom_art_push.assert_not_called()

    def test_custom_art_push_dict_payload_uses_slots(self):
        """A {slot: file_id} mapping is preferred — page sent once, slots kwarg."""
        fake = MagicMock()
        fake.custom_art_push.return_value = {"success": True}
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_push('{"0": "f1", "2": "f2"}', 3))
        assert out == {"success": True}
        fake.custom_art_push.assert_called_once_with([], 3, slots={"0": "f1", "2": "f2"})

    def test_custom_art_push_list_payload(self):
        """Legacy file-id list form: passed through with an explicit slot."""
        fake = MagicMock()
        fake.custom_art_push.return_value = {"success": True}
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_push('["f1", "f2"]', 1, slot=5))
        assert out == {"success": True}
        fake.custom_art_push.assert_called_once_with(["f1", "f2"], 1, 5)

    def test_custom_art_query_page_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            out = json.loads(self.api.custom_art_query_page(2))
        assert out == {"success": False, "error": "no daemon available"}

    def test_custom_art_query_page_delegates(self):
        fake = MagicMock()
        fake.custom_art_query_page.return_value = {"success": True, "slots": [1, 0, 1]}
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_query_page(2))
        assert out == {"success": True, "slots": [1, 0, 1]}
        fake.custom_art_query_page.assert_called_once_with(2)

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

    def _fake_wall_client(self):
        """A fake daemon client for wall ops: wall_configure succeeds and
        device_call (target='wall') records the dotted method + returns True."""
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}
        fake.device_status.return_value = {"success": True, "connected": False,
                                           "mac": None, "lan_ip": None, "wall": True}
        fake.device_call.return_value = {"success": True, "result": True}
        return fake

    def test_wall_operations(self):
        """R17 P5: wall ops route through the daemon-owned wall via device_call
        (target='wall')."""
        fake = self._fake_wall_client()
        self.api._daemon_client = fake
        slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16, "width": 120, "height": 120}}
        self.api.update_wall_slots(json.dumps(slots))
        self.assertEqual(self.api.wall_slots, slots)
        self.api.current_target_mode = "wall"

        self.assertTrue(self.api.set_solid_light("00FFCC", 100))
        fake.device_call.assert_called_with("set_light", ["00FFCC", 100], {},
                                            target="wall", blobs=None, token=None)

        self.assertTrue(self.api.set_clock(3))
        # show_clock is called with clock=3 (kwargs)
        last = fake.device_call.call_args
        self.assertEqual(last.args[0], "show_clock")
        self.assertEqual(last.kwargs.get("target"), "wall")

    def test_vj_and_visualization_selectors(self):
        """2.c/2.d: VJ + EQ selectors dispatch to the daemon-owned wall."""
        fake = self._fake_wall_client()
        self.api._daemon_client = fake
        self.api.update_wall_slots(json.dumps(
            {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16, "width": 120, "height": 120}}
        ))
        self.api.current_target_mode = "wall"

        self.assertTrue(self.api.set_vj_effect(5))
        self.assertEqual(fake.device_call.call_args.args[0], "show_effects")

        self.assertTrue(self.api.set_visualization(3))
        self.assertEqual(fake.device_call.call_args.args[0], "show_visualization")

    def test_vj_visualization_no_target(self):
        """With no connected device and no wall, selectors fail gracefully (no raise)."""
        self.api.current_divoom = None
        self.api.wall_slots = {}
        self.assertFalse(self.api.set_vj_effect(0))
        self.assertFalse(self.api.set_visualization(0))

    def test_hot_channel_bridges_delegate(self):
        """4.c/4.d: target + schedule bridges delegate to hotchannel_config."""
        cfg = {"enabled": False, "interval": 3600, "classify": 18, "targets": ["AA"]}
        with patch("divoom_lib.hotchannel_config.set_targets", return_value=True) as mset, \
             patch("divoom_lib.hotchannel_config.load_config", return_value=cfg), \
             patch("divoom_lib.hotchannel_config.get_targets", return_value=["AA"]), \
             patch("divoom_lib.hotchannel_config.save_config", return_value=True) as msave:

            self.assertTrue(self.api.set_sync_targets(json.dumps(["AA", "BB"])))
            mset.assert_called_once_with(["AA", "BB"])

            self.assertEqual(json.loads(self.api.get_hot_channel_config())["targets"], ["AA"])

            self.assertTrue(self.api.save_hot_channel_config(json.dumps({"enabled": True})))
            msave.assert_called_once()

            cands = json.loads(self.api.get_sync_candidates())
            sel = {c["address"]: c["selected"] for c in cands}
            self.assertTrue(sel.get("AA"))  # persisted target shows as selected

    def test_ticker_preview_returns_data_url(self):
        """5.d: get_ticker_preview renders a frame and returns a PNG data URL."""
        from pathlib import Path as _P
        with patch("divoom_lib.utils.media_source.fetch_stock_ticker",
                   return_value={"price": 100.0, "change": 1.0, "pct_change": 1.0}), \
             patch("divoom_lib.utils.media_source.render_stock_ticker_frame",
                   return_value=_P("/tmp/ticker_preview_test.png")), \
             patch.object(type(self.api), "_frame_to_data_url",
                          staticmethod(lambda p: "data:image/png;base64,AAA")):
            res = json.loads(self.api.get_ticker_preview("AAPL", 32))
            self.assertTrue(res["ok"])
            self.assertEqual(res["size"], 32)
            self.assertTrue(res["preview"].startswith("data:image/png;base64,"))

    def test_apply_stock_ticker_no_target(self):
        """5.a: clear failure when there is no connected device."""
        self.api.current_divoom = None
        self.api.wall_slots = {}
        with patch("divoom_lib.utils.media_source.fetch_stock_ticker",
                   return_value={"price": 1.0, "change": 0.0, "pct_change": 0.0}):
            res = json.loads(self.api.apply_stock_ticker("AAPL"))
            self.assertFalse(res["success"])
            self.assertEqual(res["error"], "No device connected")

    def test_ticker_persistence(self):
        """5.e: tickers save/load, de-duped and upper-cased."""
        import tempfile, os
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp()) / "tickers.json"
        # Override the setUp-wide Path.exists=False so the read path works.
        with patch.object(type(self.api), "_tickers_path", lambda self: tmp), \
             patch("pathlib.Path.exists", return_value=True):
            self.assertTrue(self.api.set_tickers(json.dumps(["aapl", "AAPL", "btc-usd", ""])))
            self.assertEqual(json.loads(self.api.get_tickers()), ["AAPL", "BTC-USD"])

    def test_system_stats_preview_and_apply(self):
        """Area 7: system-monitor widget renders a frame and reports stats."""
        from pathlib import Path as _P
        with patch("divoom_lib.utils.media_source.get_system_stats",
                   return_value={"cpu": 12, "mem": 43, "battery": 80}), \
             patch("divoom_lib.utils.media_source.render_system_stats_frame",
                   return_value=_P("/tmp/sysmon_test.png")), \
             patch.object(type(self.api), "_frame_to_data_url",
                          staticmethod(lambda p: "data:image/png;base64,BBB")):
            prev = json.loads(self.api.get_system_stats_preview(32))
            self.assertTrue(prev["ok"])
            self.assertEqual(prev["stats"]["cpu"], 12)
            self.assertTrue(prev["preview"].startswith("data:image/png;base64,"))

            # apply with no device → clear failure
            self.api.current_divoom = None
            self.api.wall_slots = {}
            res = json.loads(self.api.apply_system_stats())
            self.assertFalse(res["success"])
            self.assertEqual(res["error"], "No device connected")

    @patch("urllib.request.urlopen")
    def test_fetch_gallery_and_batch_sync(self, mock_urlopen):
        """Test cloud gallery catalog scraping and concurrent monthly best async streams."""
        # Mock fetch_gallery HTTP JSON response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "FileList": [
                {"FileName": "NeonSkull", "FileId": "9999", "LikeCnt": 1500, "FileType": 5, "PixelAmbId": "amb123"}
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # Mock authentication credentials
        self.api.cached_creds = MagicMock()
        self.api.cached_creds.token = "token123"
        self.api.cached_creds.user_id = 99
        self.api.cached_creds.is_valid.return_value = True

        # Pre-seed cached data for the offline cache loader check.
        # Use a real-looking file_id (not "9999") so the rebuild-on-stale path
        # doesn't trigger (see gui/gallery_sync.py load_cached_gallery).
        cached_items = [
            {"name": "NeonSkull", "file_id": "group1/M00/01/AAA_neon", "likes": 1500, "magic": 5, "preview_url": "data:image/png;base64,..."}
        ]

        import threading
        import time

        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=json.dumps(cached_items)):
            gallery_json = self.api.fetch_gallery(classify=1)
            gallery = json.loads(gallery_json)
            self.assertEqual(len(gallery), 1)
            self.assertEqual(gallery[0]["name"], "NeonSkull")
            self.assertEqual(gallery[0]["file_id"], "group1/M00/01/AAA_neon")

            # Wait for background fetch worker to finish executing under mocked Path
            for t in threading.enumerate():
                if t.name == "DivoomGalleryFetch":
                    t.join(timeout=5.0)

        # R17 P5: the daemon downloads + streams the asset; the GUI delegates
        # via sync_artwork. Wall target because wall_slots is set + no single
        # device is connected.
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}
        fake.sync_artwork.return_value = {"success": True}
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}

        artwork_json = json.dumps({"file_id": "9999"})
        sync_success = self.api.batch_sync_artwork(artwork_json)
        self.assertTrue(sync_success)
        fake.sync_artwork.assert_called_once_with("9999", target="wall")

    def test_stock_ticker_apply(self):
        """Test Yahoo Stock ticker downsampling and display coordination pipeline."""
        mock_data = {"price": 105.5, "change": 1.2, "pct_change": 1.15}
        with patch("divoom_lib.utils.media_source.fetch_stock_ticker", return_value=mock_data) as mock_fetch, \
             patch("divoom_lib.utils.media_source.render_stock_ticker_frame", return_value=Path("/tmp/ticker.png")) as mock_render:
            
            # Single connected device path
            self.api.current_divoom = MagicMock()
            self.api.current_divoom.is_connected = True
            self.api.current_divoom.display.show_image = AsyncMock(return_value=True)

            res = self.api.apply_stock_ticker("AAPL")
            res_dict = json.loads(res)
            self.assertTrue(res_dict["success"])
            self.assertEqual(res_dict["price"], 105.5)
            mock_fetch.assert_called_with("AAPL")
            mock_render.assert_called_with("AAPL", mock_data, size=16)

    def test_lan_device_operations(self):
        """Add / load / delete LAN devices against a real temp presets file (the
        writers are atomic — temp-file + os.replace — so a write_text mock would
        be bypassed; use real storage instead)."""
        import tempfile
        # This test needs a real file on disk, so drop setUp's global
        # Path.exists/Path.home patches for its duration.
        self.presets_patcher.stop()
        self.home_patcher.stop()
        try:
            with tempfile.TemporaryDirectory() as d:
                presets = Path(d) / "presets.json"
                with patch.object(self.api, "_get_presets_file", return_value=presets):
                    # Add device
                    self.assertTrue(self.api.add_lan_device("192.168.1.100", 123))

                    # Load devices
                    devices = json.loads(self.api.load_lan_devices())
                    self.assertEqual(len(devices), 1)
                    self.assertEqual(devices[0]["ip"], "192.168.1.100")
                    self.assertEqual(devices[0]["token"], 123)

                    # Delete device
                    self.assertTrue(self.api.delete_lan_device("192.168.1.100"))

                    # Load again to check empty
                    self.assertEqual(json.loads(self.api.load_lan_devices()), [])
        finally:
            # Restore so tearDown's stop() calls match.
            self.presets_patcher.start()
            self.home_patcher.start()

    def test_run_async_times_out_instead_of_hanging(self):
        """A3: a wedged async chain must not block the JS-API thread forever — it
        raises after the timeout instead."""
        async def _hang():
            await asyncio.sleep(5)
        with self.assertRaises(RuntimeError):
            self.api._run_async(_hang(), timeout=0.2)

    def test_run_async_returns_result(self):
        async def _quick():
            return 42
        self.assertEqual(self.api._run_async(_quick(), timeout=5), 42)


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

    def test_get_scoreboard_state_success(self):
        dev = MagicMock()
        dev.scoreboard.get_scoreboard = AsyncMock(
            return_value={"on_off": 1, "red_score": 5, "blue_score": 3})
        self.api.current_divoom = dev
        self.assertEqual(self.api.get_scoreboard_state(),
                         {"on_off": 1, "red_score": 5, "blue_score": 3})

    def test_get_scoreboard_state_no_device(self):
        self.api.current_divoom = None
        self.assertIsNone(self.api.get_scoreboard_state())

    def test_get_scoreboard_state_exception(self):
        dev = MagicMock()
        dev.scoreboard.get_scoreboard = AsyncMock(side_effect=RuntimeError("boom"))
        self.api.current_divoom = dev
        self.assertIsNone(self.api.get_scoreboard_state())

    # ---- volume / brightness / work-mode getters ------------------------

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

    def test_push_text_unlink_oserror_is_swallowed(self):
        dev = MagicMock()
        dev.display.show_image = AsyncMock(return_value=True)
        self.api.current_divoom = dev
        with patch("os.unlink", side_effect=OSError("already gone")):
            self.assertTrue(self.api.lighting.push_text("HI"))

    # ---- _device_size: exception in the state-getter callable falls
    # back to the 16px default --------------------------------------------

    def test_device_size_falls_back_to_16_on_error(self):
        self.api.__dict__["_active_device_size"] = MagicMock(side_effect=RuntimeError("boom"))
        self.assertEqual(self.api.lighting._device_size(), 16)

    # ---- _render_text_png scaling branches -------------------------------

    def test_render_text_png_scales_down_wide_overflow(self):
        from divoom_gui.api.lighting import LightingApi
        path = LightingApi._render_text_png("HELLO WORLD THIS IS LONG", "#00FF00", 16, 1)
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            self.assertEqual(img.size, (16, 16))
        finally:
            import os
            os.unlink(path)

    def test_render_text_png_scales_down_tall_overflow(self):
        # At a small device size the fixed 16px-tall glyph overflows
        # vertically even when the text is short — exercises the
        # height-driven rescale branch (th * scale > sz).
        from divoom_gui.api.lighting import LightingApi
        path = LightingApi._render_text_png("HI", "#00FF00", 8, 1)
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            self.assertEqual(img.size, (8, 8))
        finally:
            import os
            os.unlink(path)

    def test_render_text_png_save_failure_reraises_and_cleans_up(self):
        from divoom_gui.api.lighting import LightingApi
        import glob
        import os
        import tempfile as _tempfile
        pattern = str(Path(_tempfile.gettempdir()) / "divoom_text_*")
        before = set(glob.glob(pattern))
        with patch("PIL.Image.Image.save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                LightingApi._render_text_png("HI", "#FFFFFF", 16, 1)
        # Real cleanup outside the patched scope (unlink was NOT patched
        # here, so _render_text_png's own except-branch already removed
        # the orphaned temp file; assert no leak remains).
        after = set(glob.glob(pattern))
        for leaked in after - before:
            os.unlink(leaked)
        self.assertEqual(after - before, set())

    def test_render_text_png_save_and_cleanup_both_fail(self):
        """Both the save AND the best-effort unlink fail: the nested
        ``except OSError: pass`` must swallow the cleanup error and the
        original save error still propagates."""
        from divoom_gui.api.lighting import LightingApi
        import glob
        import os
        import tempfile as _tempfile
        pattern = str(Path(_tempfile.gettempdir()) / "divoom_text_*")
        before = set(glob.glob(pattern))
        with patch("PIL.Image.Image.save", side_effect=OSError("disk full")), \
             patch("os.unlink", side_effect=OSError("also gone")):
            with self.assertRaises(OSError):
                LightingApi._render_text_png("HI", "#FFFFFF", 16, 1)
        # os.unlink was mocked out during the call, so the mkstemp'd file
        # really does leak on disk; clean it up for real now that the
        # patch is out of scope (best-effort — not the behavior under test).
        for leaked in set(glob.glob(pattern)) - before:
            os.unlink(leaked)

    # ---- set_brightness: lan vs. BLE dispatch, exception, no-target ----

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

class TestConnectionApiCoverage(unittest.TestCase):
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

    # ---- scan_devices: no daemon / success / exception --------------------

    def test_scan_devices_no_daemon_returns_empty_list(self):
        with patch.object(self.api.connection, "_client", return_value=None):
            result = self.api.connection.scan_devices()
        self.assertEqual(json.loads(result), [])

    def test_scan_devices_success_returns_devices(self):
        fake = MagicMock()
        fake.scan.return_value = {"devices": [{"mac": "AA:BB"}]}
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = self.api.connection.scan_devices(timeout=5)
        self.assertEqual(json.loads(result), [{"mac": "AA:BB"}])
        fake.scan.assert_called_with(timeout=5, limit=4)

    def test_scan_devices_exception_returns_empty_list(self):
        fake = MagicMock()
        fake.scan.side_effect = RuntimeError("boom")
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = self.api.connection.scan_devices()
        self.assertEqual(json.loads(result), [])

    # ---- get_capabilities: no daemon / success -----------------------------

    def test_get_capabilities_no_daemon_returns_empty_dict(self):
        with patch.object(self.api.connection, "_client", return_value=None):
            result = self.api.connection.get_capabilities()
        self.assertEqual(json.loads(result), {})

    def test_get_capabilities_success(self):
        fake = MagicMock()
        fake.device_call.return_value = {"result": {"leds": 16}}
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = self.api.connection.get_capabilities()
        self.assertEqual(json.loads(result), {"leds": 16})
        fake.device_call.assert_called_with("get_capabilities", [], {}, target="device")

    # ---- _client: lazy daemon spawn + caching ------------------------------

    def test_connection_client_spawns_and_caches_daemon(self):
        self.api._daemon_client = None
        with patch("divoom_gui.daemon_bridge.ensure_daemon", return_value="FAKE_CLIENT") as mock_ensure:
            result = self.api.connection._client()
            self.assertEqual(result, "FAKE_CLIENT")
            self.assertEqual(self.api._daemon_client, "FAKE_CLIENT")
            # Second call must reuse the cached client, not spawn again.
            self.api.connection._client()
            mock_ensure.assert_called_once()

    # ---- probe_lan: no daemon / no-ip / reachable / unreachable / exception

    def test_probe_lan_no_daemon(self):
        with patch.object(self.api.connection, "_client", return_value=None):
            result = json.loads(self.api.connection.probe_lan())
        self.assertFalse(result["reachable"])
        self.assertIn("Daemon unavailable", result["detail"])

    def test_probe_lan_no_ip_configured(self):
        fake = MagicMock()
        fake.probe_lan.return_value = {"device_ip": None, "reachable": False}
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = json.loads(self.api.connection.probe_lan())
        self.assertFalse(result["reachable"])
        self.assertIn("No LAN IP", result["detail"])

    def test_probe_lan_reachable(self):
        fake = MagicMock()
        fake.probe_lan.return_value = {"device_ip": "192.168.1.5", "reachable": True}
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = json.loads(self.api.connection.probe_lan())
        self.assertTrue(result["reachable"])
        self.assertIn("192.168.1.5:9000", result["detail"])

    def test_probe_lan_unreachable_with_ip(self):
        fake = MagicMock()
        fake.probe_lan.return_value = {"device_ip": "192.168.1.5", "reachable": False}
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = json.loads(self.api.connection.probe_lan())
        self.assertFalse(result["reachable"])
        self.assertIn("192.168.1.5:9000", result["detail"])

    def test_probe_lan_exception(self):
        fake = MagicMock()
        fake.probe_lan.side_effect = RuntimeError("boom")
        with patch.object(self.api.connection, "_client", return_value=fake):
            result = json.loads(self.api.connection.probe_lan())
        self.assertFalse(result["reachable"])
        self.assertIn("boom", result["detail"])

    # ---- save_lan_config: fresh file / merge existing / exception ---------

    def test_save_lan_config_writes_fresh_file(self):
        with patch("divoom_lib.utils.atomic_io.atomic_write_config") as mock_write:
            result = self.api.connection.save_lan_config("192.168.1.10", 1234)
        self.assertTrue(result)
        mock_write.assert_called_once()
        cfg = mock_write.call_args.args[1]
        self.assertEqual(cfg["lan"]["device_ip"], "192.168.1.10")
        self.assertEqual(cfg["lan"]["local_token"], "1234")

    def test_save_lan_config_merges_existing_file(self):
        with patch.object(Path, "exists", return_value=True), \
             patch("configparser.ConfigParser.read") as mock_read, \
             patch("divoom_lib.utils.atomic_io.atomic_write_config") as mock_write:
            result = self.api.connection.save_lan_config("10.0.0.5", 99)
        self.assertTrue(result)
        mock_read.assert_called_once()
        mock_write.assert_called_once()

    def test_save_lan_config_merges_existing_lan_section(self):
        """The ``"lan" not in cfg`` guard's False arm: a config file that
        already has a [lan] section must be updated in place, not replaced."""
        def _fake_read(cfg_self, *a, **kw):
            cfg_self["lan"] = {"device_ip": "old.ip", "local_token": "1"}

        with patch.object(Path, "exists", return_value=True), \
             patch("configparser.ConfigParser.read", _fake_read), \
             patch("divoom_lib.utils.atomic_io.atomic_write_config") as mock_write:
            result = self.api.connection.save_lan_config("10.0.0.5", 99)
        self.assertTrue(result)
        cfg = mock_write.call_args.args[1]
        self.assertEqual(cfg["lan"]["device_ip"], "10.0.0.5")
        self.assertEqual(cfg["lan"]["local_token"], "99")

    def test_save_lan_config_exception_returns_false(self):
        with patch("divoom_lib.utils.atomic_io.atomic_write_config", side_effect=OSError("disk full")):
            result = self.api.connection.save_lan_config("1.2.3.4", 1)
        self.assertFalse(result)

    # ---- get_transport_status: ble/lan/cloud availability + creds error ---

    def test_get_transport_status_ble_connected_no_cloud(self):
        with patch.object(self.api.connection, "_device_status",
                          return_value={"connected": True, "mac": "AA:BB", "lan_ip": None}), \
             patch("divoom_lib.divoom_auth.get_cached_credentials", return_value=None):
            result = json.loads(self.api.connection.get_transport_status())
        self.assertTrue(result["ble"]["available"])
        self.assertEqual(result["ble"]["detail"], "AA:BB")
        self.assertFalse(result["lan"]["available"])
        self.assertFalse(result["cloud"]["available"])
        self.assertTrue(result["external"]["available"])

    def test_get_transport_status_lan_and_cloud_authenticated(self):
        creds = MagicMock()
        creds.is_valid.return_value = True
        with patch.object(self.api.connection, "_device_status",
                          return_value={"connected": True, "mac": "AA:BB", "lan_ip": "10.0.0.5"}), \
             patch("divoom_lib.divoom_auth.get_cached_credentials", return_value=creds):
            result = json.loads(self.api.connection.get_transport_status())
        self.assertFalse(result["ble"]["available"])
        self.assertTrue(result["lan"]["available"])
        self.assertEqual(result["lan"]["detail"], "10.0.0.5:9000")
        self.assertTrue(result["cloud"]["available"])
        self.assertEqual(result["cloud"]["detail"], "Authenticated")

    def test_get_transport_status_creds_lookup_exception_is_swallowed(self):
        with patch.object(self.api.connection, "_device_status",
                          return_value={"connected": False, "mac": None, "lan_ip": None}), \
             patch("divoom_lib.divoom_auth.get_cached_credentials", side_effect=RuntimeError("boom")):
            result = json.loads(self.api.connection.get_transport_status())
        self.assertFalse(result["cloud"]["available"])

    # ---- _device_status: no daemon / success / failure --------------------

    def test_device_status_no_daemon(self):
        with patch.object(self.api.connection, "_client", return_value=None):
            st = self.api.connection._device_status()
        self.assertEqual(st, {"connected": False, "mac": None, "lan_ip": None, "wall": False})

    def test_device_status_success(self):
        fake = MagicMock()
        fake.device_status.return_value = {
            "success": True, "connected": True, "mac": "AA", "lan_ip": None, "wall": False,
        }
        with patch.object(self.api.connection, "_client", return_value=fake):
            st = self.api.connection._device_status()
        self.assertTrue(st["connected"])

    def test_device_status_failure_falls_back_to_default(self):
        fake = MagicMock()
        fake.device_status.return_value = {"success": False}
        with patch.object(self.api.connection, "_client", return_value=fake):
            st = self.api.connection._device_status()
        self.assertEqual(st, {"connected": False, "mac": None, "lan_ip": None, "wall": False})

    # ---- update_wall_slots (ConnectionApi's own copy) ----------------------

    def test_connection_update_wall_slots(self):
        slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}
        self.api.connection.update_wall_slots(json.dumps(slots))
        self.assertEqual(self.api.wall_slots, slots)

    # ---- window controls (ConnectionApi's own copies) ----------------------

    def test_connection_minimize_window_with_and_without_window(self):
        self.api.connection.minimize_window()
        self.api.window.minimize.assert_called_once()
        self.api.window = None
        self.api.connection.minimize_window()  # must not raise

    def test_connection_maximize_window_with_and_without_window(self):
        self.api.connection.maximize_window()
        self.api.window.toggle_fullscreen.assert_called_once()
        self.api.window = None
        self.api.connection.maximize_window()  # must not raise

    def test_connection_close_window_stops_loop_and_destroys_window(self):
        with patch("threading.Thread") as mock_thread:
            self.api.connection.close_window()
        mock_thread.assert_called_once()

    def test_connection_close_window_no_loop_thread(self):
        conn = self.api.connection
        original = conn._loop_thread
        conn._loop_thread = None
        try:
            with patch("threading.Thread") as mock_thread:
                conn.close_window()
            mock_thread.assert_called_once()  # window destroy is still scheduled
        finally:
            conn._loop_thread = original

    def test_connection_close_window_no_window(self):
        self.api.window = None
        with patch("threading.Thread") as mock_thread:
            self.api.connection.close_window()
        mock_thread.assert_not_called()


# ── R61 planning item 1 coverage push: DivoomGuiAPI top-level (gui_api.py)
# — thin pass-through wrappers (get_transport_status, switch_channel,
# get_alarms, live_job_*, device_call, ...) that the collaborator-level tests
# above never touch because they call self.api.<collaborator>.<method>()
# directly. Also covers __init__ branches (cached-creds failure, virtual
# device cache load success/failure) and the MCP subprocess controller
# wrappers. ──────────────────────────────────────────────────────────────

class TestGuiApiTopLevelCoverage(unittest.TestCase):
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

    # ---- __init__: cached-creds lookup failure is swallowed ----------------

    def test_init_swallows_cached_credentials_error(self):
        with patch("divoom_lib.divoom_auth.get_cached_credentials", side_effect=RuntimeError("boom")):
            api = DivoomGuiAPI()
        try:
            self.assertIsNone(api.cached_creds)
        finally:
            api.loop_thread.stop()

    # ---- __init__: virtual-device cache load (primary path present) -------

    @staticmethod
    def _primary_path_exists(path_obj):
        return str(path_obj).endswith("virtual_device.json") and ".config" in str(path_obj)

    def test_init_loads_virtual_device_from_primary_path(self):
        device_info = {"BluetoothDeviceId": 42, "DevicePassword": 7}
        with patch.object(Path, "exists", self._primary_path_exists), \
             patch.object(Path, "read_text", return_value=json.dumps(device_info)):
            api = DivoomGuiAPI()
        try:
            self.assertEqual(api.device_id, 42)
            self.assertEqual(api.device_pw, 7)
        finally:
            api.loop_thread.stop()

    def test_init_virtual_device_bad_json_is_swallowed(self):
        with patch.object(Path, "exists", self._primary_path_exists), \
             patch.object(Path, "read_text", return_value="not valid json{"):
            api = DivoomGuiAPI()
        try:
            self.assertEqual(api.device_id, 0)
            self.assertEqual(api.device_pw, 0)
        finally:
            api.loop_thread.stop()

    # ---- _client: lazy daemon spawn -----------------------------------------

    def test_client_spawns_daemon_when_none_cached(self):
        self.api._daemon_client = None
        with patch("divoom_gui.daemon_bridge.ensure_daemon", return_value="FAKE") as mock_ensure:
            result = self.api._client()
        self.assertEqual(result, "FAKE")
        self.assertEqual(self.api._daemon_client, "FAKE")
        mock_ensure.assert_called_once()

    # ---- thin pass-through wrappers to ConnectionApi -----------------------

    def test_connection_wrappers_forward_to_collaborator(self):
        self.api.connection = MagicMock()
        self.api.connection.get_transport_status.return_value = "TS"
        self.api.connection.save_lan_config.return_value = True
        self.api.connection.probe_lan.return_value = "PL"

        self.assertEqual(self.api.get_transport_status(), "TS")
        self.assertTrue(self.api.save_lan_config("1.2.3.4", 99))
        self.api.connection.save_lan_config.assert_called_with("1.2.3.4", 99)
        self.assertEqual(self.api.probe_lan(), "PL")

    # ---- thin pass-through wrappers to Lighting/Tools/Widgets APIs ---------

    def test_lighting_wrappers_forward_to_collaborator(self):
        self.api.lighting = MagicMock()
        self.api.lighting.switch_channel.return_value = True
        self.assertTrue(self.api.switch_channel("clock"))
        self.api.lighting.switch_channel.assert_called_with("clock")

        self.api.lighting.set_temperature_channel.return_value = True
        self.assertTrue(self.api.set_temperature_channel(celsius=False, color="#ABCDEF"))
        self.api.lighting.set_temperature_channel.assert_called_with(False, "#ABCDEF")

        self.api.lighting.set_clock_rich.return_value = True
        self.assertTrue(self.api.set_clock_rich(style=1))

        self.api.lighting.display_wall_image.return_value = True
        self.assertTrue(self.api.display_wall_image("/tmp/a.png", 16))

        self.api.lighting.display_custom_art.return_value = True
        self.assertTrue(self.api.display_custom_art("/tmp/b.png"))

        self.api.lighting.set_brightness.return_value = True
        self.assertTrue(self.api.set_brightness(80))

        self.api.lighting.set_volume.return_value = True
        self.assertTrue(self.api.set_volume(5))

    def test_tools_and_widgets_wrappers_forward_to_collaborator(self):
        self.api.tools = MagicMock()
        self.api.tools.get_alarms.return_value = "ALARMS"
        self.assertEqual(self.api.get_alarms(), "ALARMS")

        self.api.tools.set_low_power.return_value = True
        self.assertTrue(self.api.set_low_power(True))
        self.api.tools.set_low_power.assert_called_with(True)

        self.api.tools.get_device_name.return_value = "Bedroom Pixoo"
        self.assertEqual(self.api.get_device_name(), "Bedroom Pixoo")

        self.api.widgets = MagicMock()
        self.api.widgets.push_weather.return_value = True
        self.assertTrue(self.api.push_weather())

        self.api.widgets.get_weather.return_value = {"temp": 70}
        self.assertEqual(self.api.get_weather(), {"temp": 70})

    # ---- close_window: daemon-shutdown branch + swallowed lifecycle error -

    def test_close_window_stops_daemon_when_lifecycle_shared(self):
        fake_client = MagicMock()
        self.api._daemon_client = fake_client
        with patch("divoom_lib.lifecycle_config.get_keep_daemon_alive", return_value=False), \
             patch("divoom_lib.lifecycle_config.should_stop_daemon_on_dashboard_quit", return_value=True), \
             patch("threading.Thread"):
            self.api.close_window()
        fake_client.shutdown.assert_called_once()

    def test_close_window_swallows_lifecycle_check_error(self):
        fake_client = MagicMock()
        self.api._daemon_client = fake_client
        with patch("divoom_lib.lifecycle_config.get_keep_daemon_alive", side_effect=RuntimeError("boom")), \
             patch("threading.Thread"):
            self.api.close_window()  # must not raise
        fake_client.shutdown.assert_not_called()

    # ---- live_job_start / live_job_stop / live_job_list ---------------------

    def test_live_job_methods_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            self.assertEqual(self.api.live_job_start("AA:BB", "kind", {}),
                             {"success": False, "error": "daemon unavailable"})
            self.assertEqual(self.api.live_job_stop("AA:BB", "kind"),
                             {"success": False, "error": "daemon unavailable"})
            self.assertEqual(self.api.live_job_list("AA:BB"),
                             {"success": False, "error": "daemon unavailable"})

    def test_live_job_methods_delegate_to_daemon(self):
        fake = MagicMock()
        fake.live_job_start.return_value = {"success": True}
        fake.live_job_stop.return_value = {"success": True}
        fake.live_job_list.return_value = {"success": True, "jobs": []}
        with patch.object(self.api, "_client", return_value=fake):
            self.assertEqual(self.api.live_job_start("AA:BB", "kind", {"x": 1}), {"success": True})
            fake.live_job_start.assert_called_with("AA:BB", "kind", {"x": 1})
            self.assertEqual(self.api.live_job_stop("AA:BB", "kind"), {"success": True})
            fake.live_job_stop.assert_called_with("AA:BB", "kind")
            self.assertEqual(self.api.live_job_list("AA:BB"), {"success": True, "jobs": []})
            fake.live_job_list.assert_called_with("AA:BB")

    # ---- get_notification_listener_status: daemon-unavailable branch ------

    def test_get_notification_listener_status_daemon_unavailable(self):
        with patch("sys.platform", new="darwin"), \
             patch("divoom_client.macos_notifications.find_notification_db_path", return_value=None), \
             patch("divoom_client.macos_notifications.load_routing_table", return_value=[]), \
             patch.object(self.api, "_client", return_value=None):
            s = self.api.get_notification_listener_status()
        self.assertTrue(s["platform_supported"])
        self.assertFalse(s["running"])
        self.assertEqual(s["error"], "daemon unavailable")

    # ---- save_notification_routing: invalid entries + daemon-side failure --

    def test_save_notification_routing_invalid_entries(self):
        with patch("divoom_client.macos_notifications.load_routing_table", return_value=[("x", 1)]):
            result = self.api.save_notification_routing('[["whatsapp", "not-an-int"]]')
        self.assertIsNotNone(result["error"])
        self.assertIn("Invalid routing entries", result["error"])
        self.assertEqual(result["rules"], [["x", 1]])

    def test_save_notification_routing_set_routing_failure(self):
        fake = MagicMock()
        fake.set_routing.return_value = {"success": False, "error": "device busy"}
        with patch("divoom_client.macos_notifications.load_routing_table", return_value=[("x", 1)]), \
             patch.object(self.api, "_client", return_value=fake):
            result = self.api.save_notification_routing('[["whatsapp", 6]]')
        self.assertEqual(result["error"], "device busy")
        self.assertEqual(result["rules"], [["x", 1]])

    # ---- device_call: no daemon / delegates --------------------------------

    def test_device_call_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            result = json.loads(self.api.device_call("get_capabilities"))
        self.assertEqual(result, {"success": False, "error": "daemon unavailable"})

    def test_device_call_delegates_to_daemon(self):
        fake = MagicMock()
        fake.device_call.return_value = {"success": True, "result": 42}
        with patch.object(self.api, "_client", return_value=fake):
            result = json.loads(self.api.device_call(
                "get_brightness", [1], {"a": 2}, target="wall", blobs={"b": "x"}, token="tok"))
        self.assertEqual(result, {"success": True, "result": 42})
        fake.device_call.assert_called_with(
            "get_brightness", [1], {"a": 2}, target="wall", blobs={"b": "x"}, token="tok")

    # ---- open_file_dialog: no window / picked / cancelled / exception -----

    def test_open_file_dialog_no_window(self):
        self.api.window = None
        self.assertIsNone(self.api.open_file_dialog())

    def test_open_file_dialog_returns_selected_path(self):
        self.api.window.create_file_dialog.return_value = ["/tmp/picked.png"]
        self.assertEqual(self.api.open_file_dialog(), "/tmp/picked.png")

    def test_open_file_dialog_empty_result_returns_none(self):
        self.api.window.create_file_dialog.return_value = []
        self.assertIsNone(self.api.open_file_dialog())

    def test_open_file_dialog_none_result_returns_none(self):
        self.api.window.create_file_dialog.return_value = None
        self.assertIsNone(self.api.open_file_dialog())

    def test_open_file_dialog_exception_returns_none(self):
        self.api.window.create_file_dialog.side_effect = RuntimeError("boom")
        self.assertIsNone(self.api.open_file_dialog())

    # ---- MCP server subprocess controller wrappers -------------------------

    def test_mcp_server_lifecycle_delegates_to_controller(self):
        from divoom_gui.mcp_control import MCPController, MCPStatus
        fake_ctl = MagicMock()
        fake_ctl.start.return_value = MCPStatus(running=True, pid=123, started_at=1.0,
                                                mac="AA:BB", log_path="/tmp/log",
                                                last_log_lines=["hi"], error=None)
        fake_ctl.stop.return_value = MCPStatus(running=False)
        fake_ctl.is_running.return_value = True
        fake_ctl.status.return_value = MCPStatus(running=True, pid=123)
        with patch.object(MCPController, "instance", return_value=fake_ctl):
            start_result = self.api.start_mcp_server(mac="AA:BB")
            stop_result = self.api.stop_mcp_server()
            running = self.api.is_mcp_server_running()
            status = self.api.mcp_server_status()
        self.assertTrue(start_result["running"])
        self.assertEqual(start_result["pid"], 123)
        fake_ctl.start.assert_called_with(mac="AA:BB")
        self.assertFalse(stop_result["running"])
        self.assertTrue(running)
        self.assertTrue(status["running"])

    def test_start_mcp_server_empty_mac_passes_none(self):
        from divoom_gui.mcp_control import MCPController, MCPStatus
        fake_ctl = MagicMock()
        fake_ctl.start.return_value = MCPStatus(running=False)
        with patch.object(MCPController, "instance", return_value=fake_ctl):
            self.api.start_mcp_server(mac="")
        fake_ctl.start.assert_called_with(mac=None)


if __name__ == "__main__":
    unittest.main()
