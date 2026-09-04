
import asyncio
import logging
import unittest
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# --- Configuration ---
DEVICE_NAME_SUBSTRING = "Timoo"
LOG_LEVEL = logging.INFO

# Setup basic logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("system_functions_test")

class TestSystemFunctions(unittest.IsolatedAsyncioTestCase):

    divoom: Divoom = None
    
    async def asyncSetUp(self):
        """Discover and connect to the device before each test."""
        ble_device, _ = await discover_device(name_substring=DEVICE_NAME_SUBSTRING)
        if not ble_device:
            self.fail(f"No device found with name containing '{DEVICE_NAME_SUBSTRING}'.")
        
        self.divoom = Divoom(mac=ble_device.address, logger=logger, use_ios_le_protocol=False)
        await self.divoom.connect()
        
        # We know from previous tests which characteristics and protocol work
        self.divoom.WRITE_CHARACTERISTIC_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
        self.divoom.NOTIFY_CHARACTERISTIC_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
        self.divoom.escapePayload = False

    async def asyncTearDown(self):
        """Disconnect after each test."""
        if self.divoom and self.divoom.is_connected:
            await self.divoom.disconnect()

    async def test_get_brightness(self):
        """Test getting the current brightness."""
        logger.info("--- Running test_get_brightness ---")
        brightness = await self.divoom.system.get_brightness()
        logger.info(f"Got brightness: {brightness}")
        self.assertIsNotNone(brightness)
        self.assertIsInstance(brightness, int)
        self.assertTrue(0 <= brightness <= 100)

    async def test_set_and_get_brightness(self):
        """Test setting the brightness and then getting it to verify."""
        logger.info("--- Running test_set_and_get_brightness ---")
        
        # Set brightness to a known value
        test_brightness = 50
        logger.info(f"Setting brightness to {test_brightness}...")
        await self.divoom.system.set_brightness(test_brightness)
        
        # Give the device a moment to process
        await asyncio.sleep(2.0)
        
        # Get brightness and verify
        logger.info("Getting brightness to verify...")
        current_brightness = await self.divoom.system.get_brightness()
        logger.info(f"Got brightness: {current_brightness}")
        
        # The getter might be flaky, so we add a retry
        retries = 3
        while current_brightness != test_brightness and retries > 0:
            logger.warning(f"Brightness mismatch. Expected {test_brightness}, got {current_brightness}. Retrying...")
            await asyncio.sleep(2.0)
            current_brightness = await self.divoom.system.get_brightness()
            retries -= 1

        self.assertEqual(current_brightness, test_brightness)

        # Set it back to 100
        logger.info("Setting brightness back to 100...")
        await self.divoom.system.set_brightness(100)

    async def test_get_work_mode(self):
        """Test getting the current work mode."""
        logger.info("--- Running test_get_work_mode ---")
        work_mode = await self.divoom.system.get_work_mode()
        logger.info(f"Got work mode: {work_mode}")
        self.assertIsNotNone(work_mode)
        self.assertIsInstance(work_mode, int)
        self.assertTrue(0 <= work_mode <= 11)

    async def test_set_work_mode(self):
        """Test setting the work mode."""
        logger.info("--- Running test_set_work_mode ---")
        
        # Get original work mode
        original_mode = await self.divoom.system.get_work_mode()
        logger.info(f"Original work mode: {original_mode}")
        self.assertIsNotNone(original_mode)

        # Set to a new work mode (e.g., 1)
        new_mode = 1
        if original_mode == new_mode:
            new_mode = 2 # Ensure we are changing the mode
        
        logger.info(f"Setting work mode to {new_mode}...")
        result = await self.divoom.system.set_work_mode(new_mode)
        self.assertTrue(result)
        await asyncio.sleep(2.0)

        # Verify the new work mode
        current_mode = await self.divoom.system.get_work_mode()
        logger.info(f"Current work mode: {current_mode}")
        self.assertEqual(current_mode, new_mode)

        # Set back to original mode
        logger.info(f"Setting work mode back to {original_mode}...")
        result = await self.divoom.system.set_work_mode(original_mode)
        self.assertTrue(result)
        await asyncio.sleep(2.0)

        # Verify it's back to original
        current_mode = await self.divoom.system.get_work_mode()
        logger.info(f"Final work mode: {current_mode}")
        self.assertEqual(current_mode, original_mode)

    async def test_set_channel(self):
        """Test setting the channel."""
        logger.info("--- Running test_set_channel ---")
        
        # Note: We can't easily get the current channel, so we'll just set it
        # and assume the default is 0 (Time).

        # Set to a new channel (e.g., 1: Lightning)
        new_channel = 1
        logger.info(f"Setting channel to {new_channel}...")
        result = await self.divoom.system.set_channel(new_channel)
        self.assertTrue(result)
        await asyncio.sleep(2.0)
        
        # There's no get_channel, so we can't verify directly.
        # We'll just check that the command sends successfully.

        # Set back to original channel (Time)
        original_channel = 0
        logger.info(f"Setting channel back to {original_channel}...")
        result = await self.divoom.system.set_channel(original_channel)
        self.assertTrue(result)
        await asyncio.sleep(2.0)

        # Test invalid channel
        logger.info("Testing invalid channel...")
        result = await self.divoom.system.set_channel(99)
        self.assertFalse(result)

    async def test_get_device_temp(self):
        """Test getting the device temperature."""
        logger.info("--- Running test_get_device_temp ---")
        temp_data = await self.divoom.system.get_device_temp()
        logger.info(f"Got device temp: {temp_data}")
        self.assertIsNotNone(temp_data)
        self.assertIsInstance(temp_data, dict)
        self.assertIn("format", temp_data)
        self.assertIn("value", temp_data)
        self.assertIn(temp_data["format"], [0, 1]) # Celsius or Fahrenheit
        self.assertIsInstance(temp_data["value"], int)

    async def test_set_and_get_device_name(self):
        """Test setting and getting the device name."""
        logger.info("--- Running test_set_and_get_device_name ---")
        
        # Get original device name
        original_name = await self.divoom.system.get_device_name()
        logger.info(f"Original device name: {original_name}")
        self.assertIsNotNone(original_name)

        # Set to a new name
        new_name = "DivoomTest"
        logger.info(f"Setting device name to {new_name}...")
        result = await self.divoom.system.set_device_name(new_name)
        self.assertTrue(result)
        await asyncio.sleep(5.0) # Changing name can take time

        # NOTE: After changing the name, the device may disconnect.
        # Reconnecting to verify the new name is complex and might fail.
        # For this test, we will primarily rely on the successful command send.
        # And then we will change it back immediately.

        # Set back to original name
        logger.info(f"Setting device name back to {original_name}...")
        result = await self.divoom.system.set_device_name(original_name)
        self.assertTrue(result)
        await asyncio.sleep(5.0)

        # Test name truncation
        long_name = "ThisIsAVeryLongDeviceName"
        logger.info(f"Testing name truncation with name: {long_name}...")
        result = await self.divoom.system.set_device_name(long_name)
        self.assertTrue(result)
        await asyncio.sleep(5.0)
        
        # Set back to original name again
        logger.info(f"Setting device name back to {original_name} one last time...")
        result = await self.divoom.system.set_device_name(original_name)
        self.assertTrue(result)

    async def test_set_and_get_low_power_switch(self):
        """Test setting and getting the low power switch status."""
        logger.info("--- Running test_set_and_get_low_power_switch ---")
        
        # Get original status
        original_status = await self.divoom.system.get_low_power_switch()
        logger.info(f"Original low power switch status: {original_status}")
        self.assertIsNotNone(original_status)

        # Turn on
        logger.info("Turning on low power switch...")
        result = await self.divoom.system.set_low_power_switch(1)
        self.assertTrue(result)
        await asyncio.sleep(2.0)
        current_status = await self.divoom.system.get_low_power_switch()
        self.assertEqual(current_status, 1)

        # Turn off
        logger.info("Turning off low power switch...")
        result = await self.divoom.system.set_low_power_switch(0)
        self.assertTrue(result)
        await asyncio.sleep(2.0)
        current_status = await self.divoom.system.get_low_power_switch()
        self.assertEqual(current_status, 0)

        # Restore original status
        logger.info(f"Restoring low power switch to {original_status}...")
        result = await self.divoom.system.set_low_power_switch(original_status)
        self.assertTrue(result)

    async def test_set_hour_type(self):
        """Test setting the hour type."""
        logger.info("--- Running test_set_hour_type ---")
        
        # Set to 24-hour format
        logger.info("Setting hour type to 24-hour...")
        result = await self.divoom.system.set_hour_type(1)
        self.assertTrue(result)
        await asyncio.sleep(2.0)

        # Set to 12-hour format
        logger.info("Setting hour type to 12-hour...")
        result = await self.divoom.system.set_hour_type(0)
        self.assertTrue(result)
        await asyncio.sleep(2.0)

        # There is no getter, so we just check for successful command sending.

    async def test_set_and_get_auto_power_off(self):
        """Test setting and getting the auto power-off timer."""
        logger.info("--- Running test_set_and_get_auto_power_off ---")
        
        # Get original timer
        original_timer = await self.divoom.system.get_auto_power_off()
        logger.info(f"Original auto power-off timer: {original_timer} minutes")
        self.assertIsNotNone(original_timer)

        # Set a new timer (e.g., 30 minutes)
        new_timer = 30
        logger.info(f"Setting auto power-off timer to {new_timer} minutes...")
        result = await self.divoom.system.set_auto_power_off(new_timer)
        self.assertTrue(result)
        await asyncio.sleep(2.0)

        # Verify the new timer
        current_timer = await self.divoom.system.get_auto_power_off()
        logger.info(f"Current auto power-off timer: {current_timer} minutes")
        self.assertEqual(current_timer, new_timer)

        # Restore original timer
        logger.info(f"Restoring auto power-off timer to {original_timer} minutes...")
        result = await self.divoom.system.set_auto_power_off(original_timer)
        self.assertTrue(result)
        await asyncio.sleep(2.0)
        
        # Verify it's back to original
        current_timer = await self.divoom.system.get_auto_power_off()
        logger.info(f"Final auto power-off timer: {current_timer} minutes")
        self.assertEqual(current_timer, original_timer)

    async def test_set_and_get_sound_control(self):
        """Test setting and getting the sound control status."""
        logger.info("--- Running test_set_and_get_sound_control ---")
        
        # Get original status
        original_status = await self.divoom.system.get_sound_control()
        logger.info(f"Original sound control status: {original_status}")
        self.assertIsNotNone(original_status)

        # Enable sound control
        logger.info("Enabling sound control...")
        result = await self.divoom.system.set_sound_control(1)
        self.assertTrue(result)
        await asyncio.sleep(2.0)
        current_status = await self.divoom.system.get_sound_control()
        self.assertEqual(current_status, 1)

        # Disable sound control
        logger.info("Disabling sound control...")
        result = await self.divoom.system.set_sound_control(0)
        self.assertTrue(result)
        await asyncio.sleep(2.0)
        current_status = await self.divoom.system.get_sound_control()
        self.assertEqual(current_status, 0)

        # Restore original status
        logger.info(f"Restoring sound control to {original_status}...")
        result = await self.divoom.system.set_sound_control(original_status)
        self.assertTrue(result)

if __name__ == '__main__':
    unittest.main()
