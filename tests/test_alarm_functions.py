import unittest
import asyncio
import logging
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_alarm_functions")

class TestAlarmFunctions(unittest.IsolatedAsyncioTestCase):

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

    async def test_set_alarm(self):
        logger.info("--- Running test_set_alarm ---")
        # Set an alarm for 10:30 AM, Monday, enabled
        await self.divoom.alarm.set_alarm(
            alarm_index=0,
            status=1, # On
            hour=10,
            minute=30,
            week=1, # Monday
            mode=0, # ALARM_MUSIC
            trigger_mode=1, # ALARM_TRIGGER_MUSIC
            fm_freq=0,
            volume=50
        )
        logger.info("Set alarm for 10:30 AM Monday, enabled.")
        # In a real scenario, you'd want to verify this by getting the alarm back
        # For now, we just check if the command was sent without error.

    async def test_get_alarm(self):
        logger.info("--- Running test_get_alarm ---")
        alarm_settings = await self.divoom.alarm.get_alarm_time()
        self.assertIsNotNone(alarm_settings, "Failed to retrieve alarm settings.")
        logger.info(f"Retrieved alarm settings: {alarm_settings}")
        # Add more specific assertions based on expected structure of alarm_settings

    async def test_enable_disable_alarm(self):
        logger.info("--- Running test_enable_disable_alarm ---")
        # First, set an alarm to ensure it exists
        await self.divoom.alarm.set_alarm(
            alarm_index=0,
            status=1, # On
            hour=11,
            minute=0,
            week=2, # Tuesday
            mode=0,
            trigger_mode=1,
            fm_freq=0,
            volume=50
        )
        logger.info("Set alarm for 11:00 AM Tuesday, enabled.")

        # Disable the alarm
        await self.divoom.alarm.set_alarm(
            alarm_index=0,
            status=0, # Off
            hour=11,
            minute=0,
            week=2, # Tuesday
            mode=0,
            trigger_mode=1,
            fm_freq=0,
            volume=50
        )
        logger.info("Disabled alarm for 11:00 AM Tuesday.")

        # In a real scenario, you'd get the alarm settings back and assert enabled=False

    async def test_get_memorial_time(self):
        logger.info("--- Running test_get_memorial_time ---")
        memorial_settings = await self.divoom.alarm.get_memorial_time()
        self.assertIsNotNone(memorial_settings, "Failed to retrieve memorial settings.")
        logger.info(f"Retrieved memorial settings: {memorial_settings}")
        self.assertIsInstance(memorial_settings, list)
        if len(memorial_settings) > 0:
            self.assertIsInstance(memorial_settings[0], dict)
            self.assertIn("dialy_id", memorial_settings[0])
            self.assertIn("on_off", memorial_settings[0])
            self.assertIn("month", memorial_settings[0])
            self.assertIn("day", memorial_settings[0])
            self.assertIn("hour", memorial_settings[0])
            self.assertIn("minute", memorial_settings[0])
            self.assertIn("have_flag", memorial_settings[0])
            self.assertIn("title_name", memorial_settings[0])

    async def test_set_alarm_listen(self):
        logger.info("--- Running test_set_alarm_listen ---")
        
        # Enable alarm listen
        logger.info("Enabling alarm listen...")
        result = await self.divoom.alarm.set_alarm_listen(on_off=1, mode=0, volume=10)
        self.assertTrue(result)
        await asyncio.sleep(1.0)

        # Disable alarm listen
        logger.info("Disabling alarm listen...")
        result = await self.divoom.alarm.set_alarm_listen(on_off=0, mode=0, volume=10)
        self.assertTrue(result)
        logger.info("Successfully enabled and disabled alarm listen.")

    async def test_set_alarm_volume(self):
        logger.info("--- Running test_set_alarm_volume ---")
        
        # Set alarm volume
        logger.info("Setting alarm volume to 5...")
        result = await self.divoom.alarm.set_alarm_volume(volume=5)
        self.assertTrue(result)
        logger.info("Successfully set alarm volume.")

    async def test_set_alarm_volume_control(self):
        logger.info("--- Running test_set_alarm_volume_control ---")
        
        # Set alarm volume control
        logger.info("Setting alarm volume control...")
        result = await self.divoom.alarm.set_alarm_volume_control(control=0, index=0)
        self.assertTrue(result)
        logger.info("Successfully set alarm volume control.")

if __name__ == '__main__':
    unittest.main()
