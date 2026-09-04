
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
logger = logging.getLogger("display_functions_test")

class TestDisplayFunctions(unittest.IsolatedAsyncioTestCase):

    divoom: Divoom = None
    
    async def asyncSetUp(self):
        """Discover and connect to the device before each test."""
        ble_device, _ = await discover_device(name_substring=DEVICE_NAME_SUBSTRING)
        if not ble_device:
            self.fail(f"No device found with name containing '{DEVICE_NAME_SUBSTRING}'.")
        
        self.divoom = Divoom(
            mac=ble_device.address, 
            logger=logger, 
            use_ios_le_protocol=False
        )
        await self.divoom.connect()
        
        self.divoom.WRITE_CHARACTERISTIC_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
        self.divoom.NOTIFY_CHARACTERISTIC_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
        self.divoom.escapePayload = False

    async def asyncTearDown(self):
        """Disconnect after each test."""
        if self.divoom and self.divoom.is_connected:
            await self.divoom.disconnect()

    async def test_show_light(self):
        """Test showing a solid color light."""
        logger.info("--- Running test_show_light ---")
        
        logger.info("Setting light to RED")
        result_red = await self.divoom.display.show_light(color="FF0000", brightness=50)
        self.assertTrue(result_red)
        await asyncio.sleep(2) # Pause for visual confirmation
        
        logger.info("Setting light to BLUE")
        result_blue = await self.divoom.display.show_light(color="0000FF", brightness=50)
        self.assertTrue(result_blue)
        await asyncio.sleep(2)

    async def test_show_clock(self):
        """Test showing the clock face."""
        logger.info("--- Running test_show_clock ---")
        
        logger.info("Showing default clock")
        result_default = await self.divoom.display.show_clock()
        self.assertTrue(result_default)
        await asyncio.sleep(2)
        
        logger.info("Showing clock with humidity, weather and date")
        result_weather = await self.divoom.display.show_clock(humidity=True, weather=True, date=True)
        self.assertTrue(result_weather)
        await asyncio.sleep(2)

    async def test_show_visualization(self):
        """Test showing a music visualization."""
        logger.info("--- Running test_show_visualization ---")
        
        # We don't know the valid numbers, so we test that sending 0 doesn't fail
        logger.info("Showing visualization #0")
        result = await self.divoom.display.show_visualization(number=0)
        self.assertTrue(result)
        await asyncio.sleep(2)

    async def test_show_effects(self):
        """Test showing a VJ effect."""
        logger.info("--- Running test_show_effects ---")
        
        # We don't know the valid numbers, so we test that sending 0 doesn't fail
        logger.info("Showing VJ effect #0")
        result = await self.divoom.display.show_effects(number=0)
        self.assertTrue(result)
        await asyncio.sleep(2)

if __name__ == '__main__':
    unittest.main()
