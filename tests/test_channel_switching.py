import unittest
import asyncio
import logging
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_channel_switching")

class TestChannelSwitching(unittest.TestCase):

    def test_switch_channel_to_lightning(self):
        """
        Tests switching the Divoom device to the 'lightning' channel.
        This test passes if the command is sent without any exceptions.
        """
        async def run_test():
            divoom = None
            try:
                # Discover the device
                ble_device, device_id = await discover_device(name_substring="Timoo")
                self.assertIsNotNone(ble_device, "No Divoom device found.")
                
                logger.info(f"Found device: {device_id}")

                # Initialize Divoom controller
                divoom = Divoom(mac=device_id, logger=logger)
                await divoom.connect()
                logger.info(f"Successfully connected to {divoom.mac}!")

                # Send the command to switch to the lightning channel
                logger.info("Sending command to switch to 'lightning' channel...")
                await divoom.display.show_light(color="0000FF", brightness=50)
                logger.info("Command sent successfully.")

            except Exception as e:
                self.fail(f"Test failed with an exception: {e}")
            finally:
                if divoom and divoom.is_connected:
                    await divoom.disconnect()
                    logger.info("Disconnected from Divoom device.")

        # Run the async test
        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
