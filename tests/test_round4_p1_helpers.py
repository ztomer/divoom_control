"""Tests for Round 4 P1 feature helpers.

Covers:
  - divoom_lib.system.control.Control   (set_keyboard, set_hot, set_light_mode)
  - divoom_lib.system.sound.SoundControl (set_sound_control, set_auto_power_off, etc.)
  - divoom_lib.display.design.Design    (set_eq, set_language, user-define time)
  - divoom_lib.models.config.DivoomConfig (new screensize field)

Uses AsyncMock for the CommandSender — no real device required.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bleak import BleakClient

from divoom_lib.divoom import Divoom
from divoom_lib.display.design import Design
from divoom_lib.models import COMMANDS
from divoom_lib.models.config import DivoomConfig
from divoom_lib.system.control import Control
from divoom_lib.system.sound import SoundControl
from divoom_lib.game import (
    Game,
    GAME_ID_DINO,
    GAME_ID_2048,
    GAME_ID_MAGIC_BALL,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=BleakClient)
    client.is_connected = False
    client.address = "AA:BB:CC:DD:EE:FF"
    return client


@pytest.fixture
def fake_divoom(mock_client):
    """A Divoom instance with all sub-modules reachable and a mock send_command."""
    with patch("divoom_lib.divoom.BleakClient", return_value=mock_client):
        d = Divoom(
            mac="AA:BB:CC:DD:EE:FF",
            logger=logging.getLogger("test"),
            client=mock_client,
            screensize=32,
        )
    d._divoom = d  # backward-compat alias used by some modules
    d.send_command = AsyncMock(return_value=True)
    d.send_command_and_wait_for_response = AsyncMock(return_value=None)
    return d


# ── DivoomConfig ─────────────────────────────────────────────────────────────


class TestDivoomConfig:
    def test_default_screensize_is_none(self):
        cfg = DivoomConfig()
        assert cfg.screensize is None

    def test_screensize_32_round_trips(self):
        cfg = DivoomConfig(screensize=32)
        assert cfg.screensize == 32

    def test_existing_fields_preserved(self):
        cfg = DivoomConfig(
            mac="11:22:33:44:55:66",
            write_characteristic_uuid="wc",
            device_name="MyDivoom",
            screensize=16,
        )
        assert cfg.mac == "11:22:33:44:55:66"
        assert cfg.write_characteristic_uuid == "wc"
        assert cfg.device_name == "MyDivoom"
        assert cfg.screensize == 16


# ── Control ─────────────────────────────────────────────────────────────────


class TestControl:
    @pytest.mark.asyncio
    async def test_set_keyboard_0x23(self, fake_divoom):
        ctrl = Control(fake_divoom)
        ok = await ctrl.set_keyboard(0x01)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set keyboard"], [0x01]
        )
        assert COMMANDS["set keyboard"] == 0x23

    @pytest.mark.asyncio
    async def test_set_hot_enabled(self, fake_divoom):
        ctrl = Control(fake_divoom)
        ok = await ctrl.set_hot(enabled=True)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set hot"], [0x01]
        )
        assert COMMANDS["set hot"] == 0x26

    @pytest.mark.asyncio
    async def test_set_hot_disabled(self, fake_divoom):
        ctrl = Control(fake_divoom)
        await ctrl.set_hot(enabled=False)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set hot"], [0x00]
        )

    @pytest.mark.asyncio
    async def test_set_light_mode_channel(self, fake_divoom):
        ctrl = Control(fake_divoom)
        ok = await ctrl.set_light_mode(channel=5)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set light mode"], [5]
        )
        assert COMMANDS["set light mode"] == 0x45


# ── SoundControl ─────────────────────────────────────────────────────────────


class TestSoundControl:
    @pytest.mark.asyncio
    async def test_set_sound_control_enable(self, fake_divoom):
        sc = SoundControl(fake_divoom)
        ok = await sc.set_sound_control(1)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set sound ctrl"], [1]
        )
        assert COMMANDS["set sound ctrl"] == 0xA7

    @pytest.mark.asyncio
    async def test_set_song_display_control(self, fake_divoom):
        sc = SoundControl(fake_divoom)
        await sc.set_song_display_control(1)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set song dis ctrl"], [1]
        )
        assert COMMANDS["set song dis ctrl"] == 0x83

    @pytest.mark.asyncio
    async def test_set_auto_power_off_30_minutes(self, fake_divoom):
        sc = SoundControl(fake_divoom)
        await sc.set_auto_power_off(30)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set auto power off"], [30, 0]
        )
        assert COMMANDS["set auto power off"] == 0xAB


# ── Design (0xBD sub-cmd dispatch) ──────────────────────────────────────────


class TestDesign:
    @pytest.mark.asyncio
    async def test_set_eq_dyn_static(self, fake_divoom):
        d = Design(fake_divoom)
        ok = await d.set_eq(dynamic=True, mode=2, stream=False)
        assert ok is True
        # 0xBD 0x1E [0x01, 0x02, 0x00]
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x1E, 0x01, 0x02, 0x00]
        )
        assert COMMANDS["set design"] == 0xBD

    @pytest.mark.asyncio
    async def test_set_eq_streaming(self, fake_divoom):
        d = Design(fake_divoom)
        await d.set_eq(dynamic=False, mode=0, stream=True)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x1E, 0x00, 0x00, 0x01]
        )

    @pytest.mark.asyncio
    async def test_set_language_english(self, fake_divoom):
        d = Design(fake_divoom)
        await d.set_language(0)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x26, 0x00]
        )

    @pytest.mark.asyncio
    async def test_set_user_define_time(self, fake_divoom):
        d = Design(fake_divoom)
        await d.set_user_define_time(7, 30, 15)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x14, 7, 30, 15]
        )

    @pytest.mark.asyncio
    async def test_get_user_define_time(self, fake_divoom):
        fake_divoom.send_command_and_wait_for_response = AsyncMock(
            return_value=bytes([10, 20, 30])
        )
        d = Design(fake_divoom)
        result = await d.get_user_define_time()
        assert result == {"hour": 10, "minute": 20, "second": 30}

    @pytest.mark.asyncio
    async def test_get_user_define_time_short_response(self, fake_divoom):
        """Less than 3 bytes → returns None."""
        fake_divoom.send_command_and_wait_for_response = AsyncMock(
            return_value=bytes([10, 20])  # only 2 bytes
        )
        d = Design(fake_divoom)
        result = await d.get_user_define_time()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_define_time_none(self, fake_divoom):
        fake_divoom.send_command_and_wait_for_response = AsyncMock(
            return_value=None
        )
        d = Design(fake_divoom)
        result = await d.get_user_define_time()
        assert result is None

    # ── Round 9: screen config + factory reset (0xBD EXT) ──────────────
    @pytest.mark.asyncio
    async def test_set_screen_dir(self, fake_divoom):
        d = Design(fake_divoom)
        ok = await d.set_screen_dir(2)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x23, 2]
        )

    @pytest.mark.asyncio
    async def test_set_screen_dir_masks_byte(self, fake_divoom):
        d = Design(fake_divoom)
        await d.set_screen_dir(259)  # 0x103 -> 0x03
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x23, 3]
        )

    @pytest.mark.asyncio
    async def test_set_screen_mirror_on_off(self, fake_divoom):
        d = Design(fake_divoom)
        await d.set_screen_mirror(True)
        fake_divoom.send_command.assert_awaited_with(
            COMMANDS["set design"], [0x24, 1]
        )
        await d.set_screen_mirror(False)
        fake_divoom.send_command.assert_awaited_with(
            COMMANDS["set design"], [0x24, 0]
        )

    @pytest.mark.asyncio
    async def test_factory_reset(self, fake_divoom):
        d = Design(fake_divoom)
        ok = await d.factory_reset()
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x25, 1]
        )

    # ── Round 37: custom art page management (CmdManager.p1 / g) ───────
    @pytest.mark.asyncio
    async def test_use_user_define_index_page_0(self, fake_divoom):
        ok = await fake_divoom.design.use_user_define_index(0)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x17, 0x00]
        )

    @pytest.mark.asyncio
    async def test_use_user_define_index_page_1(self, fake_divoom):
        ok = await fake_divoom.design.use_user_define_index(1)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x17, 0x01]
        )

    @pytest.mark.asyncio
    async def test_use_user_define_index_page_2(self, fake_divoom):
        ok = await fake_divoom.design.use_user_define_index(2)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x17, 0x02]
        )

    @pytest.mark.asyncio
    async def test_clear_user_define_index_page_0(self, fake_divoom):
        ok = await fake_divoom.design.clear_user_define_index(0)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x16, 0x00]
        )

    @pytest.mark.asyncio
    async def test_clear_user_define_index_page_1(self, fake_divoom):
        ok = await fake_divoom.design.clear_user_define_index(1)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x16, 0x01]
        )

    @pytest.mark.asyncio
    async def test_clear_user_define_index_page_2(self, fake_divoom):
        ok = await fake_divoom.design.clear_user_define_index(2)
        assert ok is True
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set design"], [0x16, 0x02]
        )


# ── Divoom facade wiring ────────────────────────────────────────────────────


class TestDivoomFacade:
    def test_screensize_propagates_to_cfg(self, mock_client):
        with patch("divoom_lib.divoom.BleakClient", return_value=mock_client):
            d = Divoom(
                mac="AA:BB:CC:DD:EE:FF",
                screensize=32,
                client=mock_client,
            )
        assert d._conn.cfg.screensize == 32

    def test_default_screensize_is_none(self, mock_client):
        with patch("divoom_lib.divoom.BleakClient", return_value=mock_client):
            d = Divoom(
                mac="AA:BB:CC:DD:EE:FF",
                client=mock_client,
            )
        assert d._conn.cfg.screensize is None

    def test_sound_control_registered(self, fake_divoom):
        assert hasattr(fake_divoom, "sound")
        assert isinstance(fake_divoom.sound, SoundControl)

    def test_design_registered(self, fake_divoom):
        assert hasattr(fake_divoom, "design")
        assert isinstance(fake_divoom.design, Design)

    def test_control_registered(self, fake_divoom):
        assert hasattr(fake_divoom, "control")
        assert isinstance(fake_divoom.control, Control)


# ── Game (Phase E.7) ────────────────────────────────────────────────────────


class TestGame:
    @pytest.mark.asyncio
    async def test_show_game_dino(self, fake_divoom):
        g = Game(fake_divoom)
        ok = await g.show_game(value=GAME_ID_DINO)
        assert ok is True
        # 0xA0 [state=0x01, game_id=0x01]
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set game"], [0x01, 0x01]
        )
        assert COMMANDS["set game"] == 0xA0
        assert GAME_ID_DINO == 0x01
        assert GAME_ID_2048 == 0x02
        assert GAME_ID_MAGIC_BALL == 0x05

    @pytest.mark.asyncio
    async def test_hide_game(self, fake_divoom):
        g = Game(fake_divoom)
        await g.hide_game()
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set game"], [0x00, 0x00]
        )

    @pytest.mark.asyncio
    async def test_set_key_down(self, fake_divoom):
        g = Game(fake_divoom)
        await g.set_key_down(0x03)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set game ctrl info"], [0x03]
        )
        assert COMMANDS["set game ctrl info"] == 0x17

    @pytest.mark.asyncio
    async def test_set_key_up(self, fake_divoom):
        g = Game(fake_divoom)
        await g.set_key_up(0x04)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set game ctrl key up info"], [0x04]
        )
        assert COMMANDS["set game ctrl key up info"] == 0x21

    @pytest.mark.asyncio
    async def test_set_magic_ball_answer(self, fake_divoom):
        g = Game(fake_divoom)
        await g.set_magic_ball_answer(7)
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["send game shark"], [7]
        )
        assert COMMANDS["send game shark"] == 0x88

    @pytest.mark.asyncio
    async def test_exit_game(self, fake_divoom):
        g = Game(fake_divoom)
        await g.exit_game()
        fake_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set game"], [0x00, 0x00]
        )

    def test_game_registered(self, fake_divoom):
        assert hasattr(fake_divoom, "game")
        assert isinstance(fake_divoom.game, Game)
