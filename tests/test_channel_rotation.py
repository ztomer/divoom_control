import os
import sys
import asyncio
import unittest
import logging
from bleak import BleakClient

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device, discover_characteristics, pick_char_uuid
from divoom_lib.models import CHANNEL_ID_TIME, CHANNEL_ID_LIGHTNING, CHANNEL_ID_CLOUD, CHANNEL_ID_VJ_EFFECTS, CHANNEL_ID_VISUALIZATION, CHANNEL_ID_ANIMATION, CHANNEL_ID_SCOREBOARD

# Configure logging for the test
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestChannelRotation(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        logger.info("Starting real device setup...")
        ble_device, device_id = await discover_device(name_substring="Timoo", address=None)

        self.assertIsNotNone(ble_device, "Could not discover Tivoom device.")
        
        # Connect to the device to discover characteristics
        client = BleakClient(ble_device.address)
        try:
            await client.connect()
            logger.info(f"Connected to {ble_device.address} for characteristic discovery.")
            write_chars, notify_chars, read_chars = await discover_characteristics(client)

            write_uuid = pick_char_uuid(None, write_chars)
            notify_uuid = pick_char_uuid(None, notify_chars)
            read_uuid = pick_char_uuid(None, read_chars)

            if not all([write_uuid, notify_uuid, read_uuid]):
                raise ValueError("Could not discover all required characteristic UUIDs.")

            logger.info(f"Discovered Write UUID: {write_uuid}")
            logger.info(f"Discovered Notify UUID: {notify_uuid}")
            logger.info(f"Discovered Read UUID: {read_uuid}")

            self.divoom = Divoom(
                mac=device_id,
                logger=logger,
                write_characteristic_uuid=write_uuid,
                notify_characteristic_uuid=notify_uuid,
                read_characteristic_uuid=read_uuid,
                client=client # Pass the already connected client
            )
            # No need to call await self.divoom.connect() here, as the client is already connected
            logger.info(f"Divoom object initialized with connected client for Tivoo device at {device_id}")
        except Exception as e:
            logger.error(f"Error during asyncSetUp: {e}")
            raise
        finally:
            # The client is now managed by the Divoom object, so no need to disconnect here
            pass

    async def asyncTearDown(self):
        if self.divoom and self.divoom.is_connected:
            await self.divoom.disconnect()
            logger.info("Disconnected from real Tivoom device.")

    async def test_channel_rotation(self):
        logger.info("Starting test_channel_rotation...")

        channels = [
            ("Time Channel", CHANNEL_ID_TIME),
            ("Lightning Channel", CHANNEL_ID_LIGHTNING),
            ("Cloud Channel", CHANNEL_ID_CLOUD),
            ("VJ Effects Channel", CHANNEL_ID_VJ_EFFECTS),
            ("Visualization Channel", CHANNEL_ID_VISUALIZATION),
            ("Animation Channel", CHANNEL_ID_ANIMATION),
            ("Scoreboard Channel", CHANNEL_ID_SCOREBOARD),
        ]

        for name, channel_id in channels:
            logger.info(f"Activating {name}...")
            await self.divoom.system.set_channel(channel_id)
            await asyncio.sleep(2)

        logger.info("Finished test_channel_rotation.")

if __name__ == '__main__':
    unittest.main()