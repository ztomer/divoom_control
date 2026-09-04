
import asyncio
import logging
import unittest
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device
from divoom_lib import models as constants

# --- Configuration ---
DEVICE_NAME_SUBSTRING = "Timoo"
LOG_LEVEL = logging.INFO

# Setup basic logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("tool_timer_functions_test")

class TestToolTimerFunctions(unittest.IsolatedAsyncioTestCase):

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

    async def test_get_timer_info(self):
        """Test getting the timer tool info."""
        logger.info("--- Running test_get_timer_info ---")
        
        # Switch to a channel where the timer tool is accessible (e.g., the clock)
        logger.info("Switching to Time channel to access timer tool...")
        await self.divoom.system.set_channel(constants.CHANNEL_ID_TIME)
        await asyncio.sleep(2) # Give device time to switch

        logger.info("Getting timer state...")
        timer_state = await self.divoom.tool.get_tool_info(constants.TOOL_TYPE_TIMER)
        
        self.assertIsNotNone(timer_state, "Expected timer state to be returned, but got None (timeout?)")
        self.assertIn("status", timer_state, "Expected 'status' key in timer state response.")
        logger.info(f"Timer state reported: {timer_state}")

    async def test_set_timer_start_pause_reset(self):
        """Test starting, pausing, and resetting the timer tool."""
        logger.info("--- Running test_set_timer_start_pause_reset ---")

        # Switch to a channel where the timer tool is accessible (e.g., the clock)
        logger.info("Switching to Time channel to access timer tool...")
        await self.divoom.system.set_channel(constants.CHANNEL_ID_TIME)
        await asyncio.sleep(2) # Give device time to switch

        # 1. Start the timer
        logger.info("Starting timer...")
        result_start = await self.divoom.tool.set_tool_info(
            constants.TOOL_TYPE_TIMER,
            ctrl_flag=constants.STI_CTRL_FLAG_TIMER_STARTED
        )
        self.assertTrue(result_start, "Failed to start timer.")
        await asyncio.sleep(2)

        # 2. Pause the timer
        logger.info("Pausing timer...")
        result_pause = await self.divoom.tool.set_tool_info(
            constants.TOOL_TYPE_TIMER,
            ctrl_flag=constants.STI_CTRL_FLAG_TIMER_PAUSED
        )
        self.assertTrue(result_pause, "Failed to pause timer.")
        await asyncio.sleep(2)

        # 3. Reset the timer
        logger.info("Resetting timer...")
        result_reset = await self.divoom.tool.set_tool_info(
            constants.TOOL_TYPE_TIMER,
            ctrl_flag=constants.STI_CTRL_FLAG_TIMER_RESET
        )
        self.assertTrue(result_reset, "Failed to reset timer.")
        await asyncio.sleep(2)

        # Optional: Attempt to get the final state, but don't fail if it's None
        final_timer_state = await self.divoom.tool.get_tool_info(constants.TOOL_TYPE_TIMER)
        logger.info(f"Final timer state reported: {final_timer_state}")
        # We can add an assertion here if we expect a specific state after reset,
        # but for now, just logging it to observe device behavior.

if __name__ == '__main__':
    unittest.main()
