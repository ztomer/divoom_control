"""
Unit tests for divoom_lib.media.music.Music.

These are pure protocol-encoding/decoding tests: the CommandSender dependency
(BLE/network transport) is mocked out entirely, so no hardware or event loop
plumbing beyond asyncio is required. Byte layouts mirror the constants in
divoom_lib.models.constants (GSPN_*, GSML_*, GV_VOLUME, GPS_STATUS, GSMLTN_*,
GSMI_*) and the command ids in divoom_lib.models.commands.
"""

import logging
import unittest
from unittest.mock import AsyncMock, MagicMock

from divoom_lib.media.music import Music
from divoom_lib.models import COMMANDS

logger = logging.getLogger("test_music_media_unit")


def make_music(response=None, send_result=True):
    """Build a Music instance wired to a mocked CommandSender."""
    mock_divoom = MagicMock()
    mock_divoom.logger = logger
    mock_divoom.send_command = AsyncMock(return_value=send_result)
    mock_divoom.send_command_and_wait_for_response = AsyncMock(return_value=response)
    return Music(mock_divoom), mock_divoom


class TestGetSdPlayName(unittest.IsolatedAsyncioTestCase):
    async def test_decodes_name_from_response(self):
        name = "Song"
        response = len(name).to_bytes(2, byteorder="little") + name.encode("utf-8")
        music, mock_divoom = make_music(response=response)

        result = await music.get_sd_play_name()

        self.assertEqual(result, "Song")
        mock_divoom.send_command_and_wait_for_response.assert_awaited_once_with(
            COMMANDS["get sd play name"]
        )

    async def test_none_response_returns_none(self):
        music, _ = make_music(response=None)
        self.assertIsNone(await music.get_sd_play_name())

    async def test_too_short_response_returns_none(self):
        music, _ = make_music(response=bytes([1]))
        self.assertIsNone(await music.get_sd_play_name())

    async def test_incomplete_name_bytes_returns_none(self):
        # name_len claims 10 bytes but only 4 are actually present
        response = (10).to_bytes(2, byteorder="little") + b"Song"
        music, _ = make_music(response=response)
        self.assertIsNone(await music.get_sd_play_name())


class TestGetSdMusicList(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _entry(music_id, name):
        return (
            music_id.to_bytes(2, byteorder="little")
            + len(name).to_bytes(2, byteorder="little")
            + name.encode("utf-8")
        )

    async def test_parses_multiple_entries(self):
        response = self._entry(1, "A") + self._entry(2, "BB")
        music, mock_divoom = make_music(response=response)

        result = await music.get_sd_music_list(0, 10)

        self.assertEqual(result, [{"id": 1, "name": "A"}, {"id": 2, "name": "BB"}])
        args = mock_divoom.send_command_and_wait_for_response.call_args[0]
        self.assertEqual(args[0], COMMANDS["get sd music list"])
        self.assertEqual(args[1], [0, 0, 10, 0])

    async def test_none_response_returns_empty_list(self):
        music, _ = make_music(response=None)
        self.assertEqual(await music.get_sd_music_list(0, 10), [])

    async def test_too_short_response_returns_empty_list(self):
        music, _ = make_music(response=bytes([1, 2, 3]))
        self.assertEqual(await music.get_sd_music_list(0, 10), [])

    async def test_incomplete_trailing_entry_keeps_prior_entries(self):
        # First entry complete; second entry's declared name_len overruns
        # the buffer, so parsing should stop and keep what it already has.
        broken_tail = (
            (2).to_bytes(2, byteorder="little")
            + (10).to_bytes(2, byteorder="little")
            + b"X"
        )
        response = self._entry(1, "A") + broken_tail
        music, _ = make_music(response=response)

        result = await music.get_sd_music_list(0, 10)

        self.assertEqual(result, [{"id": 1, "name": "A"}])


class TestVolume(unittest.IsolatedAsyncioTestCase):
    async def test_get_volume_returns_value(self):
        music, _ = make_music(response=bytes([10]))
        self.assertEqual(await music.get_volume(), 10)

    async def test_get_volume_none_response(self):
        music, _ = make_music(response=None)
        self.assertIsNone(await music.get_volume())

    async def test_set_volume_sends_command(self):
        music, mock_divoom = make_music()
        result = await music.set_volume(12)
        self.assertTrue(result)
        mock_divoom.send_command.assert_awaited_once_with(COMMANDS["set volume"], [12])


class TestPlayStatus(unittest.IsolatedAsyncioTestCase):
    async def test_get_play_status_returns_value(self):
        music, _ = make_music(response=bytes([1]))
        self.assertEqual(await music.get_play_status(), 1)

    async def test_get_play_status_none_response(self):
        music, _ = make_music(response=None)
        self.assertIsNone(await music.get_play_status())

    async def test_set_play_status_sends_command(self):
        music, mock_divoom = make_music()
        result = await music.set_play_status(1)
        self.assertTrue(result)
        mock_divoom.send_command.assert_awaited_once_with(COMMANDS["set playstate"], [1])


class TestSdPlaybackControl(unittest.IsolatedAsyncioTestCase):
    async def test_set_sd_play_music_id_encodes_little_endian(self):
        music, mock_divoom = make_music()
        await music.set_sd_play_music_id(300)
        mock_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set sd play music id"], list((300).to_bytes(2, "little"))
        )

    async def test_set_sd_last_next_previous(self):
        music, mock_divoom = make_music()
        await music.set_sd_last_next(0)
        mock_divoom.send_command.assert_awaited_once_with(COMMANDS["set sd last next"], [0])

    async def test_set_sd_last_next_next(self):
        music, mock_divoom = make_music()
        await music.set_sd_last_next(1)
        mock_divoom.send_command.assert_awaited_once_with(COMMANDS["set sd last next"], [1])

    async def test_send_sd_list_over_sends_command_with_no_args(self):
        music, mock_divoom = make_music()
        result = await music.send_sd_list_over()
        self.assertTrue(result)
        mock_divoom.send_command.assert_awaited_once_with(COMMANDS["send sd list over"])


class TestSdMusicListTotalNum(unittest.IsolatedAsyncioTestCase):
    async def test_returns_total(self):
        response = (300).to_bytes(2, byteorder="little")
        music, _ = make_music(response=response)
        self.assertEqual(await music.get_sd_music_list_total_num(), 300)

    async def test_none_response(self):
        music, _ = make_music(response=None)
        self.assertIsNone(await music.get_sd_music_list_total_num())

    async def test_too_short_response(self):
        music, _ = make_music(response=bytes([1]))
        self.assertIsNone(await music.get_sd_music_list_total_num())


class TestSdMusicInfo(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _build_response(cur_time, total_time, music_id, status, volume, play_mode):
        return (
            cur_time.to_bytes(2, byteorder="little")
            + total_time.to_bytes(2, byteorder="little")
            + music_id.to_bytes(2, byteorder="little")
            + bytes([status, volume, play_mode])
        )

    async def test_get_sd_music_info_parses_all_fields(self):
        response = self._build_response(60, 200, 3, 1, 10, 2)
        music, _ = make_music(response=response)

        result = await music.get_sd_music_info()

        self.assertEqual(
            result,
            {
                "current_time": 60,
                "total_time": 200,
                "music_id": 3,
                "status": 1,
                "volume": 10,
                "play_mode": 2,
            },
        )

    async def test_get_sd_music_info_none_response(self):
        music, _ = make_music(response=None)
        self.assertIsNone(await music.get_sd_music_info())

    async def test_get_sd_music_info_too_short_response(self):
        music, _ = make_music(response=bytes(8))  # needs >= 9 bytes
        self.assertIsNone(await music.get_sd_music_info())

    async def test_set_sd_music_info_encodes_fields(self):
        music, mock_divoom = make_music()
        await music.set_sd_music_info(current_time=60, music_id=3, volume=10, status=1, play_mode=2)

        expected_args = list((60).to_bytes(2, "little")) + list((3).to_bytes(2, "little")) + [10, 1, 2]
        mock_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set sd music info"], expected_args
        )


class TestSdMusicPositionAndPlayMode(unittest.IsolatedAsyncioTestCase):
    async def test_set_sd_music_position_encodes_little_endian(self):
        music, mock_divoom = make_music()
        await music.set_sd_music_position(600)
        mock_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set sd music position"], list((600).to_bytes(2, "little"))
        )

    async def test_set_sd_music_play_mode_sends_single_byte(self):
        music, mock_divoom = make_music()
        await music.set_sd_music_play_mode(3)
        mock_divoom.send_command.assert_awaited_once_with(
            COMMANDS["set sd music play mode"], [3]
        )


class TestAppNeedGetMusicList(unittest.IsolatedAsyncioTestCase):
    async def test_sends_command_with_no_args(self):
        music, mock_divoom = make_music()
        result = await music.app_need_get_music_list()
        self.assertTrue(result)
        mock_divoom.send_command.assert_awaited_once_with(COMMANDS["app need get music list"])


if __name__ == "__main__":
    unittest.main()
