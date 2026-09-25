import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from divoom_legacy.protocol import DivoomProtocol
from divoom_lib import models
import logging

@pytest.fixture
def mock_protocol_instance():
    """Fixture for a mock DivoomProtocol instance."""
    with patch('divoom_legacy.divoom.BleakClient') as mock_bleak_client:
        mock_bleak_client.return_value = AsyncMock()
        protocol = DivoomProtocol(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
        protocol.client.is_connected = True
        protocol.WRITE_CHARACTERISTIC_UUID = "mock_write_char_uuid"
        protocol.NOTIFY_CHARACTERISTIC_UUID = "mock_notify_char_uuid"
        protocol.READ_CHARACTERISTIC_UUID = "mock_read_char_uuid"
        protocol.use_ios_le_protocol = False
        protocol.escapePayload = False
        yield protocol

@pytest.mark.asyncio
async def test_protocol_init(mock_protocol_instance):
    """Test DivoomProtocol initialization."""
    protocol = mock_protocol_instance
    assert protocol.mac == "AA:BB:CC:DD:EE:FF"
    assert protocol.device_name == "MockDevice"
    assert protocol.use_ios_le_protocol is False
    assert protocol.escapePayload is False
    assert protocol.notification_queue.empty()
    assert protocol._expected_response_command is None
    assert protocol.message_buf == bytearray()






@pytest.mark.asyncio
async def test_notification_handler_basic(mock_protocol_instance):
    """Test notification_handler for basic protocol."""
    protocol = mock_protocol_instance
    protocol.use_ios_le_protocol = False
    # 01 07 00 04 46 55 01 00 a7 00 02
    data = bytearray.fromhex("0107000446550100a70002")
    protocol.notification_handler(12, data)
    assert not protocol.notification_queue.empty()
    response = await protocol.notification_queue.get()
    assert response['command_id'] == 0x46
    assert response['payload'] == bytearray.fromhex("0100")

@pytest.mark.asyncio
async def test_notification_handler_ios_le(mock_protocol_instance):
    """Test notification_handler for iOS LE protocol."""
    protocol = mock_protocol_instance
    protocol.use_ios_le_protocol = True
    protocol._expected_response_command = 0x46
    # Wire format: feefaa55 (header) + 0600 (len=6) + 00 (packet num) + 46 (cmd) + 0100 (data) + 4d00 (crc) + 02 (end)
    data = bytearray.fromhex("feefaa550600004601004d0002")
    protocol.notification_handler(12, data)
    assert not protocol.notification_queue.empty()
    response = await protocol.notification_queue.get()
    assert response['command_id'] == 0x46
    assert response['payload'] == bytearray.fromhex("0100")

@pytest.mark.asyncio
async def test_wait_for_response(mock_protocol_instance):
    """Test wait_for_response."""
    protocol = mock_protocol_instance
    protocol.notification_queue.put_nowait({'command_id': 0x46, 'payload': b'test'})
    response = await protocol.wait_for_response(0x46, timeout=1)
    assert response == b'test'

@pytest.mark.asyncio
async def test_wait_for_response_timeout(mock_protocol_instance):
    """Test wait_for_response timeout."""
    protocol = mock_protocol_instance
    response = await protocol.wait_for_response(0x46, timeout=0.1)
    assert response is None

@pytest.mark.asyncio
async def test_send_command(mock_protocol_instance):
    """Test send_command."""
    protocol = mock_protocol_instance
    with patch.object(protocol, '_send_payload', new_callable=AsyncMock) as mock_send_payload:
        await protocol.send_command("set volume", [10])
        mock_send_payload.assert_called_once_with([models.COMMANDS["set volume"], 10], write_with_response=False)



@pytest.mark.asyncio
async def test_connect(mock_protocol_instance):
    """Test connect method."""
    protocol = mock_protocol_instance
    protocol.client.is_connected = False
    await protocol.connect()
    protocol.client.connect.assert_called_once()
    protocol.client.start_notify.assert_called_once()
    args, _ = protocol.client.start_notify.call_args
    assert args[0] == "mock_notify_char_uuid"
    assert args[1] == ANY

@pytest.mark.asyncio
async def test_disconnect(mock_protocol_instance):
    """Test disconnect method."""
    protocol = mock_protocol_instance
    await protocol.disconnect()
    protocol.client.disconnect.assert_called_once()

@pytest.mark.asyncio
async def test_send_command_and_wait_for_response(mock_protocol_instance):
    """Test send_command_and_wait_for_response."""
    protocol = mock_protocol_instance
    with patch.object(protocol, 'send_command', new_callable=AsyncMock) as mock_send_command, \
         patch.object(protocol, '_wait_for_response', new_callable=AsyncMock) as mock_wait_for_response:
        mock_wait_for_response.return_value = b'test'
        response = await protocol.send_command_and_wait_for_response("set volume", [10])
        mock_send_command.assert_called_once_with("set volume", [10], write_with_response=True)
        mock_wait_for_response.assert_called_once_with(models.COMMANDS["set volume"], 10)
        assert response == b'test'


@pytest.mark.asyncio
async def test_framing_context(mock_protocol_instance):
    """Test _framing_context correctly sets and restores framing preferences."""
    protocol = mock_protocol_instance
    original_use_ios = protocol.use_ios_le_protocol
    original_escape = protocol.escapePayload

    async with protocol._framing_context(use_ios=True, escape=True):
        assert protocol.use_ios_le_protocol is True
        assert protocol.escapePayload is True

    assert protocol.use_ios_le_protocol == original_use_ios
    assert protocol.escapePayload == original_escape

@pytest.mark.asyncio
async def test_handle_ios_le_notification_invalid(mock_protocol_instance):
    """Test _handle_ios_le_notification with invalid data."""
    protocol = mock_protocol_instance
    protocol.use_ios_le_protocol = True

    # Too short
    assert protocol._handle_ios_le_notification(bytes.fromhex("feefaa55")) is False

    # Wrong header
    assert protocol._handle_ios_le_notification(bytes.fromhex("000000000e00460000000001005901")) is False

@pytest.mark.asyncio
async def test_handle_basic_protocol_notification_invalid(mock_protocol_instance):
    """Test _handle_basic_protocol_notification with invalid data."""
    protocol = mock_protocol_instance
    protocol.use_ios_le_protocol = False

    # Buffer too short
    assert protocol._handle_basic_protocol_notification(bytearray.fromhex("0108")) is True # Returns True (buffering)

    protocol.message_buf.clear()

    # Missing start byte (ensure no 01 in data)
    assert protocol._handle_basic_protocol_notification(bytearray.fromhex("0008000446550000a80002")) is False

    # Checksum mismatch
    # 0107000446550300a80002 -> checksum should be a900 (169), but is a800
    assert protocol._handle_basic_protocol_notification(bytearray.fromhex("0107000446550300a80002")) is True # Returns True because it consumed data (even if checksum failed)
    assert protocol.notification_queue.empty()

