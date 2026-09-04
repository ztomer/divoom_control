import unittest
import asyncio
import logging
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_timeplan_functions")

class TestTimeplanFunctions(unittest.IsolatedAsyncioTestCase):

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

    async def test_set_time_manage_info_type1(self):
        logger.info("--- Running test_set_time_manage_info_type1 ---")
        # Set a time management info of type 1 (Other settings)
        result = await self.divoom.timeplan.set_time_manage_info(
            status=1, # On
            hour=12,
            minute=0,
            week=127, # All days
            mode=0,
            trigger_mode=0,
            fm_freq=0,
            volume=50,
            type=1 # Other settings
        )
        self.assertTrue(result, "Failed to set time manage info (Type 1).")
        logger.info("Successfully set time manage info (Type 1).")

    async def test_set_time_manage_info_type0(self):
        logger.info("--- Running test_set_time_manage_info_type0 ---")
        # Set a time management info of type 0 (Animation)
        fake_anim_data = [0x01, 0x02, 0x03, 0x04]
        result = await self.divoom.timeplan.set_time_manage_info(
            status=1, # On
            hour=13,
            minute=0,
            week=127, # All days
            mode=0,
            trigger_mode=4, # Animation
            fm_freq=0,
            volume=50,
            type=0, # Animation
            animation_id=1,
            animation_speed=100,
            animation_direction=0,
            animation_frame_count=1,
            animation_frame_delay=100,
            animation_frame_data=fake_anim_data
        )
        self.assertTrue(result, "Failed to set time manage info (Type 0).")
        logger.info("Successfully set time manage info (Type 0).")

    async def test_set_time_manage_ctrl(self):
        logger.info("--- Running test_set_time_manage_ctrl ---")
        # Enable time management function at index 0
        result = await self.divoom.timeplan.set_time_manage_ctrl(status=1, index=0)
        self.assertTrue(result, "Failed to enable time manage control.")
        logger.info("Successfully enabled time manage control.")

        # Disable time management function at index 0
        result = await self.divoom.timeplan.set_time_manage_ctrl(status=0, index=0)
        self.assertTrue(result, "Failed to disable time manage control.")
        logger.info("Successfully disabled time manage control.")

if __name__ == '__main__':
    unittest.main()
