"""DivoomBase connection-lifecycle coverage (ex test_base.py; notification,
send and protocol-encoding coverage live in sibling modules)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib import models as constants
from bleak.exc import BleakError
from tests.support.divoom_base_common import divoom_base_instance, mock_bleak_client  # noqa: F401


async def test_divoom_base_init(divoom_base_instance, mock_bleak_client):
    """Test DivoomBase initialization."""
    base = divoom_base_instance
    assert base.mac == "AA:BB:CC:DD:EE:FF"
    assert base.device_name is None
    assert base.WRITE_CHARACTERISTIC_UUID == "write_uuid"
    assert base.NOTIFY_CHARACTERISTIC_UUID == "notify_uuid"
    assert base.READ_CHARACTERISTIC_UUID == "read_uuid"
    assert base.client == mock_bleak_client
    assert not base.use_ios_le_protocol
    assert isinstance(base.notification_queue, asyncio.Queue)
    assert base._expected_response_command is None
    assert base.message_buf == bytearray()

@pytest.mark.asyncio
async def test_is_connected_property(divoom_base_instance, mock_bleak_client):
    """Test the is_connected property."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = True
    assert base.is_connected is True
    mock_bleak_client.is_connected = False
    assert base.is_connected is False

@pytest.mark.asyncio
async def test_connect_success(divoom_base_instance, mock_bleak_client):
    """Test successful connection."""
    base = divoom_base_instance
    mock_bleak_client.connect.return_value = None
    mock_bleak_client.is_connected = False # Start as disconnected to trigger connect()
    
    await base.connect()
    mock_bleak_client.connect.assert_called_once()
    mock_bleak_client.start_notify.assert_called_once_with(base.NOTIFY_CHARACTERISTIC_UUID, base.notification_handler)
    assert base.is_connected

@pytest.mark.asyncio
async def test_connect_already_connected(divoom_base_instance, mock_bleak_client):
    """Test connect when already connected."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = True
    
    await base.connect()
    mock_bleak_client.connect.assert_not_called()
    mock_bleak_client.start_notify.assert_not_called()

@pytest.mark.asyncio
async def test_connect_no_mac_address(divoom_base_instance):
    """Test connect with no MAC address."""
    base = divoom_base_instance
    base.mac = None
    with pytest.raises(ValueError, match="No MAC address provided or discovered. Cannot connect."):
        await base.connect()

@pytest.mark.asyncio
async def test_connect_missing_uuids(divoom_base_instance):
    """Test connect with missing characteristic UUIDs."""
    base = divoom_base_instance
    base.WRITE_CHARACTERISTIC_UUID = None
    with pytest.raises(ValueError, match="Characteristic UUIDs not fully set. Cannot connect."):
        await base.connect()

@pytest.mark.asyncio
async def test_connect_bleak_error(divoom_base_instance, mock_bleak_client):
    """Test connect with BleakError."""
    base = divoom_base_instance
    mock_bleak_client.connect.side_effect = BleakError("Connection failed")
    with pytest.raises(ConnectionError, match="Failed to connect to AA:BB:CC:DD:EE:FF: Connection failed"):
        await base.connect()

@pytest.mark.asyncio
async def test_disconnect_success(divoom_base_instance, mock_bleak_client):
    """Test successful disconnection."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = True
    mock_bleak_client.disconnect.return_value = None
    
    await base.disconnect()
    mock_bleak_client.disconnect.assert_called_once()
    assert not base.is_connected

@pytest.mark.asyncio
async def test_disconnect_not_connected(divoom_base_instance, mock_bleak_client):
    """Test disconnect when not connected."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = False
    
    await base.disconnect()
    mock_bleak_client.disconnect.assert_not_called()
