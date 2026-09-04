import unittest
import asyncio
import logging
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_game_functions")

class TestGameFunctions(unittest.IsolatedAsyncioTestCase):

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

    async def test_show_game(self):
        logger.info("--- Running test_show_game ---")
        # Assuming game ID 1 exists and can be shown
        self.assertTrue(await self.divoom.game.show_game(1), "Failed to show game 1.")
        await asyncio.sleep(2) # Wait for game to display
        self.assertTrue(await self.divoom.game.show_game(0), "Failed to hide game.")
        logger.info("Successfully showed and hid game.")

    async def test_send_gamecontrol(self):
        logger.info("--- Running test_send_gamecontrol ---")
        # First, show a game that accepts controls (e.g., game ID 1)
        self.assertTrue(await self.divoom.game.show_game(1), "Failed to show game for control test.")
        await asyncio.sleep(2)

        # Send various control commands
        self.assertTrue(await self.divoom.game.send_gamecontrol('go'), "Failed to send 'go' command.")
        await asyncio.sleep(1)
        self.assertTrue(await self.divoom.game.send_gamecontrol('up'), "Failed to send 'up' command.")
        await asyncio.sleep(1)
        self.assertTrue(await self.divoom.game.send_gamecontrol('down'), "Failed to send 'down' command.")
        await asyncio.sleep(1)
        self.assertTrue(await self.divoom.game.send_gamecontrol('left'), "Failed to send 'left' command.")
        await asyncio.sleep(1)
        self.assertTrue(await self.divoom.game.send_gamecontrol('right'), "Failed to send 'right' command.")
        await asyncio.sleep(1)
        logger.info("Successfully sent game control commands.")

        # Hide the game after testing controls
        self.assertTrue(await self.divoom.game.show_game(0), "Failed to hide game after control test.")

if __name__ == '__main__':
    unittest.main()
