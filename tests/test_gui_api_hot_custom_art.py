import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

from tests.support.gui_api_base import GuiApiTestBase

class TestGuiApiHotAndCustomArt(GuiApiTestBase):
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

