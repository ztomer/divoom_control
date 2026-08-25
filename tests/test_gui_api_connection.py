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
