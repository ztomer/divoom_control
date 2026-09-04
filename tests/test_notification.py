"""Unit tests for divoom_lib.tools.notification.Notification (Round 10).

Byte-exact validation of SPP_SET_ANDROID_ANCS (0x50) against the two wire forms
confirmed in the decompiled APK (CmdManager.a0 / CmdManager.V).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from divoom_lib.models import COMMANDS, NOTIFICATION_APPS
from divoom_lib.tools.notification import Notification


@pytest.fixture
def fake_divoom():
    d = MagicMock()
    d.logger = MagicMock()
    d.send_command = AsyncMock(return_value=True)
    return d


class TestNotification:
    def test_command_id(self):
        assert COMMANDS["set android ancs"] == 0x50

    def test_app_map_has_14(self):
        assert NOTIFICATION_APPS["WHATSAPP"] == 6
        assert NOTIFICATION_APPS["OK"] == 14
        assert len(NOTIFICATION_APPS) == 14

    @pytest.mark.asyncio
    async def test_icon_only_low_type_no_skip(self, fake_divoom):
        n = Notification(fake_divoom)
        ok = await n.show_notification(6)  # WhatsApp, < 8 → unchanged
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(0x50, [6])

    @pytest.mark.asyncio
    async def test_icon_only_high_type_skips_slot8(self, fake_divoom):
        n = Notification(fake_divoom)
        await n.show_notification(8)   # SKYPE → wire 9
        fake_divoom.send_command.assert_awaited_with(0x50, [9])
        await n.show_notification(14)  # OK → wire 15
        fake_divoom.send_command.assert_awaited_with(0x50, [15])

    @pytest.mark.asyncio
    async def test_text_form(self, fake_divoom):
        n = Notification(fake_divoom)
        await n.show_notification_text(7, "Hi")
        fake_divoom.send_command.assert_awaited_once_with(
            0x50, [7, 2, ord("H"), ord("i")]
        )

    @pytest.mark.asyncio
    async def test_text_truncated_to_128_bytes(self, fake_divoom):
        n = Notification(fake_divoom)
        await n.show_notification_text(1, "x" * 300)
        cmd, args = fake_divoom.send_command.await_args.args
        assert cmd == 0x50
        assert args[0] == 1
        assert args[1] == 128          # declared length byte
        assert len(args) == 2 + 128    # type + len + 128 payload bytes
