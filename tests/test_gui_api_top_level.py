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
        # push_weather was deleted in R70 P5.3: no JS caller, and it fetched
        # weather and switched channels in the GUI process — the pre-R67 path.
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

    # ---- live_job_list ------------------------------------------------------

    def test_live_job_list_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            self.assertEqual(self.api.live_job_list("AA:BB"),
                             {"success": False, "error": "daemon unavailable"})

    def test_live_job_list_delegates_to_daemon(self):
        fake = MagicMock()
        fake.live_job_list.return_value = {"success": True, "jobs": []}
        with patch.object(self.api, "_client", return_value=fake):
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
            status = self.api.mcp_server_status()
        self.assertTrue(start_result["running"])
        self.assertEqual(start_result["pid"], 123)
        fake_ctl.start.assert_called_with(mac="AA:BB")
        self.assertFalse(stop_result["running"])
        self.assertTrue(status["running"])

    def test_start_mcp_server_empty_mac_passes_none(self):
        from divoom_gui.mcp_control import MCPController, MCPStatus
        fake_ctl = MagicMock()
        fake_ctl.start.return_value = MCPStatus(running=False)
        with patch.object(MCPController, "instance", return_value=fake_ctl):
            self.api.start_mcp_server(mac="")
        fake_ctl.start.assert_called_with(mac=None)
