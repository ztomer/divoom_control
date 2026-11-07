import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

from tests.support.gui_api_base import GuiApiTestBase


class TestGuiApiHotAndCustomArt(GuiApiTestBase):
    def test_hot_channel_update_targets_and_stamps_the_panel_it_names(self):
        """The daemon updates the panel the click named and stamps the
        last-checked state under it -- the SAME key the GUI reads by. It was
        the panel the bench selected when the call RAN (P5.7)."""
        fake = MagicMock()
        fake.hot_update.return_value = {"success": True, "started": True}
        self.api._daemon_client = fake
        with patch.object(self.api, "_size_of", side_effect=lambda mac, default=16: 64):
            json.loads(self.api.hot_channel_update("AA:BB:CC:DD:EE:FF"))
        fake.hot_update.assert_called_once()
        assert fake.hot_update.call_args.kwargs.get("address") == "AA:BB:CC:DD:EE:FF"
        assert fake.hot_update.call_args.kwargs.get("device_size") == 64

    def test_hot_channel_update_naming_no_panel_or_the_wall_is_refused(self):
        fake = MagicMock()
        self.api._daemon_client = fake
        for mac in ("", "MatrixWall"):
            assert json.loads(self.api.hot_channel_update(mac))["success"] is False
        fake.hot_update.assert_not_called()

    def test_hot_verdict_reads_the_panel_it_names(self):
        with patch("divoom_lib.hot_verdict.get", return_value={"at": 3, "outcome": "ok"}) as g:
            out = json.loads(self.api.hot_verdict("LAN:192.168.1.5"))
        assert out == {"at": 3, "outcome": "ok"}
        g.assert_called_once_with("LAN:192.168.1.5")

    def test_the_button_names_itself_as_the_path(self):
        """U.5: the daemon records WHICH path ran the update."""
        fake = MagicMock()
        fake.hot_update.return_value = {"success": True, "started": True}
        self.api._daemon_client = fake
        with patch.object(self.api, "_size_of", side_effect=lambda mac, default=16: 16):
            self.api.hot_channel_update("AA:BB:CC:DD:EE:FF")
        assert fake.hot_update.call_args.kwargs.get("by") == "button"

    def test_sync_now_runs_each_panel_by_sync_now_and_never_connects(self):
        """U.5 / D.DV2c: Sync Now asks the daemon to update each registered
        panel, naming itself; it never opens a link itself (the fleet owns
        the panel's link) and never re-writes the last-connected panel."""
        import threading

        fake = MagicMock()
        fake.hot_update.return_value = {"success": True, "started": True}
        fake.hot_update_progress.return_value = {"phase": "done", "result": {}}
        self.api._daemon_client = fake
        self.api.window = MagicMock()
        done = threading.Event()
        self.api.window.evaluate_js.side_effect = lambda js: done.set() if "onSyncNowComplete" in js else None
        regs = [("AA:00", 18), ("BB:00", 17)]
        with (
            patch("divoom_lib.settings_devices.registered_devices", return_value=regs),
            patch.object(self.api, "_size_of", side_effect=lambda mac, default=16: 16),
            patch.object(self.api, "connect_single_device") as connect,
        ):
            assert json.loads(self.api.sync_now())["success"] is True
            assert done.wait(10), "Sync Now never completed"
        connect.assert_not_called()
        calls = [c.kwargs for c in fake.hot_update.call_args_list]
        assert [c["address"] for c in calls] == ["AA:00", "BB:00"]
        assert all(c["by"] == "sync_now" for c in calls)

    # ── gallery_hot_api: custom art push / query, hot status polling
    #    (client-boundary methods — mock at ``_client()``, not BLE) ──────────

    def test_hot_channel_update_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            out = json.loads(self.api.hot_channel_update("AA:BB:CC:DD:EE:FF"))
        assert out == {"success": False, "error": "no daemon available"}

    def test_custom_art_push_no_daemon(self):
        with patch.object(self.api, "_client", return_value=None):
            out = json.loads(self.api.custom_art_push("AA:BB:CC:DD:EE:FF", "[1,2,3]", 0))
        assert out == {"success": False, "error": "no daemon available"}

    def test_custom_art_push_invalid_json(self):
        fake = MagicMock()
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_push("AA:BB:CC:DD:EE:FF", "not json", 0))
        assert out == {"success": False, "error": "invalid payload"}
        fake.custom_art_push.assert_not_called()

    def test_custom_art_push_dict_payload_uses_slots(self):
        """A {slot: file_id} mapping is preferred — page sent once, slots kwarg."""
        fake = MagicMock()
        fake.custom_art_push.return_value = {"success": True}
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_push("AA:BB:CC:DD:EE:FF", '{"0": "f1", "2": "f2"}', 3))
        assert out == {"success": True}
        fake.custom_art_push.assert_called_once_with([], 3, slots={"0": "f1", "2": "f2"}, mac="AA:BB:CC:DD:EE:FF")

    def test_custom_art_push_list_payload(self):
        """Legacy file-id list form: passed through with an explicit slot."""
        fake = MagicMock()
        fake.custom_art_push.return_value = {"success": True}
        with patch.object(self.api, "_client", return_value=fake):
            out = json.loads(self.api.custom_art_push("AA:BB:CC:DD:EE:FF", '["f1", "f2"]', 1, slot=5))
        assert out == {"success": True}
        fake.custom_art_push.assert_called_once_with(["f1", "f2"], 1, 5, mac="AA:BB:CC:DD:EE:FF")
