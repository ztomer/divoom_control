import pytest
import asyncio
import logging
import os
import sys

from bleak import BleakClient
from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("test_brightness")

DEVICE_NAME = "Timoo"
WRITE_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
NOTIFY_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
GET_LIGHT_MODE_COMMAND = bytes.fromhex("01030046490002")

# Test 1: Minimal Bleak Test
async def test_minimal_bleak_notifications():
    """A minimal test to verify that bleak can receive notifications within pytest."""
    received_notifications = []

    def notification_handler(sender: int, data: bytearray):
        logger.info(f"MINIMAL TEST NOTIFICATION RECEIVED from {sender}: {data.hex()}")
        received_notifications.append(data)

    ble_device, device_address = await discover_device(name_substring=DEVICE_NAME)
    assert ble_device is not None, f"Device '{DEVICE_NAME}' not found."
    
    async with BleakClient(device_address) as client:
        assert client.is_connected, "Failed to connect."
        logger.info("Minimal test connected successfully.")

        await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        await client.write_gatt_char(WRITE_CHAR_UUID, GET_LIGHT_MODE_COMMAND, response=True)
        
        logger.info("Minimal test waiting for notifications for 5 seconds...")
        await asyncio.sleep(5)

        assert len(received_notifications) > 0, "Minimal test failed: No notifications were received."

# Test 2: Divoom Class Test
@pytest.fixture
async def device():
    """Pytest fixture to discover and connect to a Divoom device."""
    ble_device, device_id = await discover_device(name_substring=DEVICE_NAME)
    assert ble_device is not None, "No Divoom device found."
    
    divoom = Divoom(mac=device_id, logger=logger)
    await divoom.connect()
    yield divoom
    await divoom.disconnect()

async def test_set_and_get_brightness(device: Divoom):
    """Tests getting the device brightness using the Divoom class."""
    logger.info("Divoom class test: Getting initial brightness...")
    initial_settings = await device.light.get_light_mode()
    assert initial_settings is not None, "Divoom class test failed to get light settings."
    logger.info(f"Divoom class test got settings: {initial_settings}")