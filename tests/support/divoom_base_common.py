"""Shared fixtures for the split DivoomBase test modules (ex test_base.py)."""
import logging
from unittest.mock import AsyncMock, patch

import pytest
from bleak import BleakClient

from divoom_lib.divoom import Divoom as DivoomBase

# Mock BleakClient for DivoomBase
@pytest.fixture
def mock_bleak_client():
    client = AsyncMock(spec=BleakClient)
    client.is_connected = False
    client.address = "AA:BB:CC:DD:EE:FF"

    async def mock_connect(*args, **kwargs):
        client.is_connected = True
        return None

    async def mock_disconnect(*args, **kwargs):
        client.is_connected = False
        return None

    client.connect.side_effect = mock_connect
    client.disconnect.side_effect = mock_disconnect
    return client

@pytest.fixture
def divoom_base_instance(mock_bleak_client):
    # Patch BleakClient during DivoomBase instantiation
    with patch('divoom_lib.divoom.BleakClient', return_value=mock_bleak_client):
        instance = DivoomBase(
            mac="AA:BB:CC:DD:EE:FF",
            logger=logging.getLogger(__name__),
            write_characteristic_uuid="write_uuid",
            notify_characteristic_uuid="notify_uuid",
            read_characteristic_uuid="read_uuid",
            client=mock_bleak_client # Pass the mocked client
        )
        yield instance
