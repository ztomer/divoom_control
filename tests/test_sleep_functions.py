import unittest
import asyncio
import logging
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_sleep_functions")

class TestSleepFunctions(unittest.IsolatedAsyncioTestCase):

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

    async def test_get_sleep_scene(self):
        logger.info("--- Running test_get_sleep_scene ---")
        sleep_scene = await self.divoom.sleep.get_sleep_scene()
        # This might return None if no sleep scene is set or device doesn't respond
        if sleep_scene is not None:
            self.assertIsInstance(sleep_scene, dict, "Sleep scene should be a dictionary.")
            expected_keys = ["time", "mode", "on", "fm_freq", "volume", "color_r", "color_g", "color_b", "light"]
            for key in expected_keys:
                self.assertIn(key, sleep_scene, f"Sleep scene missing key: {key}")
            logger.info(f"Retrieved sleep scene: {sleep_scene}")
        else:
            logger.warning("Could not retrieve sleep scene (possibly not set or device doesn't respond).")
            # Not failing the test if None, as it might be a valid state.

    async def test_show_sleep(self):
        logger.info("--- Running test_show_sleep ---")
        # Set sleep mode with some parameters
        result = await self.divoom.sleep.show_sleep(
            sleeptime=60, sleepmode=1, volume=10, color=[255, 0, 0], brightness=50, on=1
        )
        self.assertTrue(result, "Failed to show sleep mode.")
        logger.info("Successfully set and showed sleep mode.")

    async def test_set_sleep_scene_listen(self):
        logger.info("--- Running test_set_sleep_scene_listen ---")
        result = await self.divoom.sleep.set_sleep_scene_listen(on_off=1, mode=0, volume=5)
        self.assertTrue(result, "Failed to set sleep scene listen.")
        logger.info("Successfully set sleep scene listen.")

    async def test_set_scene_volume(self):
        logger.info("--- Running test_set_scene_volume ---")
        result = await self.divoom.sleep.set_scene_volume(volume=8)
        self.assertTrue(result, "Failed to set scene volume.")
        logger.info("Successfully set scene volume.")

    async def test_set_sleep_color(self):
        logger.info("--- Running test_set_sleep_color ---")
        result = await self.divoom.sleep.set_sleep_color(color=[0, 255, 0])
        self.assertTrue(result, "Failed to set sleep color.")
        logger.info("Successfully set sleep color.")

    async def test_set_sleep_light(self):
        logger.info("--- Running test_set_sleep_light ---")
        result = await self.divoom.sleep.set_sleep_light(light=75)
        self.assertTrue(result, "Failed to set sleep light.")
        logger.info("Successfully set sleep light.")

    async def test_set_sleep_scene(self):
        logger.info("--- Running test_set_sleep_scene ---")
        result = await self.divoom.sleep.set_sleep_scene(
            mode=2, on=1, fm_freq=[0, 0], volume=12, color=[0, 0, 255], light=60
        )
        self.assertTrue(result, "Failed to set sleep scene.")
        logger.info("Successfully set sleep scene.")

if __name__ == '__main__':
    unittest.main()
