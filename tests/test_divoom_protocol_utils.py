
import asyncio
import logging
import unittest
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from divoom_lib.divoom import Divoom
from divoom_lib.divoom import Divoom as DivoomBase
from divoom_lib import models as constants
from divoom_lib.utils import cache as cache_util

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_divoom_protocol_utils")

class TestDivoomProtocolUtils(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up a mock Divoom instance for testing."""
        self.mock_ble_client = AsyncMock(spec=BleakClient)
        self.mock_ble_client.is_connected = True # Assume connected for most tests
        self.mock_ble_client.address = "AA:BB:CC:DD:EE:FF"
        self.mock_ble_client.write_gatt_char = AsyncMock(return_value=None) # Mock write_gatt_char

        self.mock_divoom_instance = Divoom(
            mac=self.mock_ble_client.address,
            logger=logger,
            client=self.mock_ble_client,
            write_characteristic_uuid="49535343-8841-43f4-a8d4-ecbe34729bb3",
            notify_characteristic_uuid="49535343-1e4d-4bd9-ba61-23c647249616",
            read_characteristic_uuid="49535343-1e4d-4bd9-ba61-23c647249616"
        )
        # Ensure internal mocks are set up
        self.mock_divoom_instance.send_command_and_wait_for_response = AsyncMock()
        self.mock_divoom_instance.send_command = AsyncMock(return_value=True)
        self.mock_divoom_instance.connect = AsyncMock()
        self.mock_divoom_instance.disconnect = AsyncMock()
        self.mock_divoom_instance._try_send_command_with_framing = AsyncMock()

        # Mock cache utility functions
        self.mock_load_device_cache = MagicMock(return_value={})
        self.mock_save_device_cache = MagicMock()
        patcher_load = patch('divoom_lib.utils.cache.load_device_cache', self.mock_load_device_cache)
        patcher_save = patch('divoom_lib.utils.cache.save_device_cache', self.mock_save_device_cache)
        self.addCleanup(patcher_load.stop)
        self.addCleanup(patcher_save.stop)
        patcher_load.start()
        patcher_save.start()

        self.cache_dir = "/tmp/divoom_cache"
        self.device_id = "test_device"

    async def test_set_canonical_light_spp_success(self):
        """Test set_canonical_light with successful SPP framing."""
        logger.info("--- Running test_set_canonical_light_spp_success ---")
        
        # Mock _try_send_command_with_framing to return a response for SPP
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            b"response_spp", # First call (SPP)
            None # Second call (iOS-LE) should not be reached
        ]

        result = await self.mock_divoom_instance.set_canonical_light(
            self.cache_dir, self.device_id, cache_util, rgb=[0xFF, 0x00, 0x00]
        )
        self.assertTrue(result)
        
        # Verify _try_send_command_with_framing was called for SPP
        self.mock_divoom_instance._try_send_command_with_framing.assert_called_once()
        call_args = self.mock_divoom_instance._try_send_command_with_framing.call_args
        self.assertEqual(call_args.args[0], constants.COMMANDS["set light mode"])
        self.assertEqual(call_args.kwargs['use_ios'], False)
        self.assertEqual(call_args.kwargs['escape'], self.mock_divoom_instance.escapePayload)

        # Verify cache was updated
        self.mock_save_device_cache.assert_called_once()
        saved_cache = self.mock_save_device_cache.call_args[0][2]
        self.assertEqual(saved_cache["last_successful_use_ios_le"], False)
        self.assertEqual(saved_cache["escapePayload"], self.mock_divoom_instance.escapePayload)

    async def test_set_canonical_light_ios_le_success(self):
        """Test set_canonical_light with successful iOS-LE framing after SPP failure."""
        logger.info("--- Running test_set_canonical_light_ios_le_success ---")
        
        # Mock _try_send_command_with_framing to fail SPP, then succeed iOS-LE
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            None, # First call (SPP)
            b"response_ios" # Second call (iOS-LE)
        ]

        result = await self.mock_divoom_instance.set_canonical_light(
            self.cache_dir, self.device_id, cache_util, rgb=[0x00, 0xFF, 0x00]
        )
        self.assertTrue(result)
        
        # Verify _try_send_command_with_framing was called twice
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 2)
        
        # Verify second call was for iOS-LE
        call_args = self.mock_divoom_instance._try_send_command_with_framing.call_args
        self.assertEqual(call_args.args[0], constants.COMMANDS["set light mode"])
        self.assertEqual(call_args.kwargs['use_ios'], True)
        self.assertEqual(call_args.kwargs['escape'], self.mock_divoom_instance.escapePayload)

        # Verify cache was updated for iOS-LE
        self.mock_save_device_cache.assert_called_once()
        saved_cache = self.mock_save_device_cache.call_args[0][2]
        self.assertEqual(saved_cache["last_successful_use_ios_le"], True)
        self.assertEqual(saved_cache["escapePayload"], self.mock_divoom_instance.escapePayload)

    async def test_set_canonical_light_no_response(self):
        """Test set_canonical_light when neither framing produces a response."""
        logger.info("--- Running test_set_canonical_light_no_response ---")
        
        # Mock _try_send_command_with_framing to return None for both
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [None, None]

        result = await self.mock_divoom_instance.set_canonical_light(
            self.cache_dir, self.device_id, cache_util, rgb=[0x00, 0x00, 0xFF]
        )
        self.assertFalse(result)
        
        # Verify _try_send_command_with_framing was called twice
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 2)
        # Verify cache was NOT updated
        self.mock_save_device_cache.assert_not_called()

    async def test_probe_write_characteristics_cached_payload_success(self):
        """Test probe_write_characteristics_and_try_channel_switch with cached payload success."""
        logger.info("--- Running test_probe_write_characteristics_cached_payload_success ---")
        
        mock_char_uuid = "1234-ABCD"
        mock_char = MagicMock(spec=BleakGATTCharacteristic)
        mock_char.uuid = mock_char_uuid
        write_chars = [mock_char]

        # Mock load_device_cache to return a cached payload
        self.mock_load_device_cache.return_value = {
            "last_successful_payload": ["01", "02", "03"],
            "last_successful_use_ios_le": False,
            "escapePayload": True
        }
        # Mock _try_send_command_with_framing to return a response for the cached payload
        self.mock_divoom_instance._try_send_command_with_framing.return_value = b"cached_response"

        result_uuid = await self.mock_divoom_instance.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, self.cache_dir, self.device_id, [], cache_util
        )
        self.assertEqual(result_uuid, mock_char_uuid)
        
        self.mock_divoom_instance._try_send_command_with_framing.assert_called_once()
        self.mock_save_device_cache.assert_called_once()

    async def test_probe_write_characteristics_diagnostic_payload_spp_success(self):
        """Test probe_write_characteristics_and_try_channel_switch with diagnostic payload SPP success."""
        logger.info("--- Running test_probe_write_characteristics_diagnostic_payload_spp_success ---")
        
        mock_char_uuid = "1234-ABCD"
        mock_char = MagicMock(spec=BleakGATTCharacteristic)
        mock_char.uuid = mock_char_uuid
        write_chars = [mock_char]

        # Mock load_device_cache to return empty (no cached payload)
        self.mock_load_device_cache.return_value = {}
        # Mock _try_send_command_with_framing to fail cached, then succeed diagnostic SPP
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            b"diagnostic_spp_response", # For _send_diagnostic_payload (SPP)
        ]

        result_uuid = await self.mock_divoom_instance.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, self.cache_dir, self.device_id, [], cache_util
        )
        self.assertEqual(result_uuid, mock_char_uuid)
        
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 1)
        self.mock_save_device_cache.assert_called_once()
        saved_cache = self.mock_save_device_cache.call_args[0][2]
        self.assertEqual(saved_cache["last_successful_use_ios_le"], False)

    async def test_probe_write_characteristics_diagnostic_payload_ios_le_success(self):
        """Test probe_write_characteristics_and_try_channel_switch with diagnostic payload iOS-LE success."""
        logger.info("--- Running test_probe_write_characteristics_diagnostic_payload_ios_le_success ---")
        
        mock_char_uuid = "1234-ABCD"
        mock_char = MagicMock(spec=BleakGATTCharacteristic)
        mock_char.uuid = mock_char_uuid
        write_chars = [mock_char]

        self.mock_load_device_cache.return_value = {}
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            None, # For _send_diagnostic_payload (SPP)
            b"diagnostic_ios_response" # For _send_diagnostic_payload (iOS-LE)
        ]

        result_uuid = await self.mock_divoom_instance.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, self.cache_dir, self.device_id, [], cache_util
        )
        self.assertEqual(result_uuid, mock_char_uuid)
        
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 2)
        self.mock_save_device_cache.assert_called_once()
        saved_cache = self.mock_save_device_cache.call_args[0][2]
        self.assertEqual(saved_cache["last_successful_use_ios_le"], True)

    async def test_probe_write_characteristics_fallback_channel_switch_spp_success(self):
        """Test probe_write_characteristics_and_try_channel_switch with fallback channel switch SPP success."""
        logger.info("--- Running test_probe_write_characteristics_fallback_channel_switch_spp_success ---")
        
        mock_char_uuid = "1234-ABCD"
        mock_char = MagicMock(spec=BleakGATTCharacteristic)
        mock_char.uuid = mock_char_uuid
        write_chars = [mock_char]

        self.mock_load_device_cache.return_value = {}
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            None, # For _send_diagnostic_payload (SPP)
            None, # For _send_diagnostic_payload (iOS-LE)
            b"fallback_spp_response", # For fallback channel switch (SPP)
        ]

        result_uuid = await self.mock_divoom_instance.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, self.cache_dir, self.device_id, [], cache_util
        )
        self.assertIsNone(result_uuid) # Fallback returns None
        
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 3)
        self.assertEqual(self.mock_divoom_instance.send_command.call_count, 2) # set work mode, set poweron channel

    async def test_probe_write_characteristics_fallback_channel_switch_ios_le_success(self):
        """Test probe_write_characteristics_and_try_channel_switch with fallback channel switch iOS-LE success."""
        logger.info("--- Running test_probe_write_characteristics_fallback_channel_switch_ios_le_success ---")
        
        mock_char_uuid = "1234-ABCD"
        mock_char = MagicMock(spec=BleakGATTCharacteristic)
        mock_char.uuid = mock_char_uuid
        write_chars = [mock_char]

        self.mock_load_device_cache.return_value = {}
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            None, # For _send_diagnostic_payload (SPP)
            None, # For _send_diagnostic_payload (iOS-LE)
            None, # For fallback channel switch (SPP)
            b"fallback_ios_response" # For fallback channel switch (iOS-LE)
        ]

        result_uuid = await self.mock_divoom_instance.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, self.cache_dir, self.device_id, [], cache_util
        )
        self.assertIsNone(result_uuid) # Fallback returns None
        
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 4)
        self.assertEqual(self.mock_divoom_instance.send_command.call_count, 2)

    async def test_probe_write_characteristics_no_success(self):
        """Test probe_write_characteristics_and_try_channel_switch when no characteristic responds."""
        logger.info("--- Running test_probe_write_characteristics_no_success ---")
        
        mock_char_uuid = "1234-ABCD"
        mock_char = MagicMock(spec=BleakGATTCharacteristic)
        mock_char.uuid = mock_char_uuid
        write_chars = [mock_char]

        self.mock_load_device_cache.return_value = {}
        self.mock_divoom_instance._try_send_command_with_framing.side_effect = [
            None, # For _send_diagnostic_payload (SPP)
            None, # For _send_diagnostic_payload (iOS-LE)
            None, # For fallback channel switch (SPP)
            None, # For fallback channel switch (iOS-LE)
        ]

        result_uuid = await self.mock_divoom_instance.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, self.cache_dir, self.device_id, [], cache_util
        )
        self.assertIsNone(result_uuid)
        
        self.assertEqual(self.mock_divoom_instance._try_send_command_with_framing.call_count, 4)
        self.assertEqual(self.mock_divoom_instance.send_command.call_count, 2)

if __name__ == '__main__':
    unittest.main()
