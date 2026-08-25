import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

from tests.support.gui_api_base import GuiApiTestBase

class TestGuiApiNotifications(GuiApiTestBase):
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
