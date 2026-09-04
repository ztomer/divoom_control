import unittest
import asyncio
import logging
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_music_functions")

class TestMusicFunctions(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.divoom = None
        self.device_id = None
        
        try:
            ble_device, device_id = await discover_device(name_substring="Timoo")
            if ble_device:
                self.device_id = device_id
                self.divoom = Divoom(mac=self.device_id, logger=logger)
                await self.divoom.connect()
                logger.info(f"Connected to Divoom device at {self.divoom.mac}")
            else:
                logger.error("No Divoom device found for testing.")
        except Exception as e:
            logger.error(f"Error during device setup: {e}")
            self.divoom = None # Ensure divoom is None if connection fails

        if not self.divoom or not self.divoom.is_connected:
            raise unittest.SkipTest("Could not connect to Divoom device, skipping this test.")

    async def asyncTearDown(self):
        if self.divoom and self.divoom.is_connected:
            await self.divoom.disconnect()
            logger.info("Disconnected from Divoom device.")

    async def test_get_volume(self):
        logger.info("--- Running test_get_volume ---")
        volume = await self.divoom.music.get_volume()
        self.assertIsNotNone(volume, "Failed to get volume.")
        self.assertIsInstance(volume, int, "Volume should be an integer.")
        self.assertGreaterEqual(volume, 0, "Volume should be non-negative.")
        self.assertLessEqual(volume, 15, "Volume should be between 0 and 15.")
        logger.info(f"Retrieved volume: {volume}")

    async def test_get_play_status(self):
        logger.info("--- Running test_get_play_status ---")
        status = await self.divoom.music.get_play_status()
        self.assertIsNotNone(status, "Failed to get play status.")
        self.assertIsInstance(status, int, "Play status should be an integer.")
        self.assertIn(status, [0, 1], "Play status should be 0 (pause) or 1 (play).")
        logger.info(f"Retrieved play status: {status}")

    async def test_get_sd_music_list_total_num(self):
        logger.info("--- Running test_get_sd_music_list_total_num ---")
        total_num = await self.divoom.music.get_sd_music_list_total_num()
        self.assertIsNotNone(total_num, "Failed to get total number of SD music tracks.")
        self.assertIsInstance(total_num, int, "Total number should be an integer.")
        self.assertGreaterEqual(total_num, 0, "Total number should be non-negative.")
        logger.info(f"Retrieved total number of SD music tracks: {total_num}")

    async def test_get_sd_music_info(self):
        logger.info("--- Running test_get_sd_music_info ---")
        music_info = await self.divoom.music.get_sd_music_info()
        # This might return None if no music is playing or SD card is not present
        # We'll assert that if it returns a dict, it has expected keys
        if music_info is not None:
            self.assertIsInstance(music_info, dict, "Music info should be a dictionary.")
            expected_keys = ["current_time", "total_time", "music_id", "status", "volume", "play_mode"]
            for key in expected_keys:
                self.assertIn(key, music_info, f"Music info missing key: {key}")
            logger.info(f"Retrieved SD music info: {music_info}")
        else:
            logger.warning("Could not retrieve SD music info (possibly no SD card or music playing).")
            # We don't fail the test if it's None, as it might be a valid state.
            # A more robust test would ensure an SD card is present.

    async def test_get_sd_play_name(self):
        logger.info("--- Running test_get_sd_play_name ---")
        play_name = await self.divoom.music.get_sd_play_name()
        if play_name is not None:
            self.assertIsInstance(play_name, str, "SD play name should be a string.")
            logger.info(f"Retrieved SD play name: {play_name}")
        else:
            logger.warning("Could not retrieve SD play name (possibly no music playing).")
            # Similar to get_sd_music_info, not failing if None.

if __name__ == '__main__':
    unittest.main()
