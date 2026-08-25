"""DivoomBase send/wait-for-response coverage (split from test_base.py)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib import models as constants
from bleak.exc import BleakError
from tests.support.divoom_base_common import divoom_base_instance, mock_bleak_client  # noqa: F401


@pytest.mark.asyncio
async def test_wait_for_response_success(divoom_base_instance):
    """Test wait_for_response with a successful match."""
    base = divoom_base_instance
    expected_cmd = 0x01
    expected_payload = b'\x11\x22\x33'
    
    base._expected_response_command = expected_cmd
    await base.notification_queue.put({'command_id': expected_cmd, 'payload': expected_payload})

    response = await base.wait_for_response(expected_cmd, timeout=1)
    assert response == expected_payload
    assert base._expected_response_command is None

@pytest.mark.asyncio
async def test_wait_for_response_generic_ack_then_success(divoom_base_instance):
    """Test wait_for_response with a generic ACK followed by a successful match."""
    base = divoom_base_instance
    expected_cmd = 0x45 # A command that expects a generic ACK
    expected_payload = b'\x11\x22\x33'
    
    base._expected_response_command = expected_cmd
    
    # Temporarily add 0x45 to GENERIC_ACK_COMMANDS for this test
    original_generic_acks = constants.GENERIC_ACK_COMMANDS
    constants.GENERIC_ACK_COMMANDS = list(original_generic_acks) + [0x45]

    try:
        await base.notification_queue.put({'command_id': 0x33, 'payload': b''}) # Generic ACK
        await base.notification_queue.put({'command_id': expected_cmd, 'payload': expected_payload}) # Actual response

        response = await base.wait_for_response(expected_cmd, timeout=1)
        assert response == expected_payload
        assert base._expected_response_command is None
    finally:
        constants.GENERIC_ACK_COMMANDS = original_generic_acks

@pytest.mark.asyncio
async def test_wait_for_response_timeout(divoom_base_instance):
    """Test wait_for_response with a timeout."""
    base = divoom_base_instance
    base._expected_response_command = 0x01
    response = await base.wait_for_response(0x01, timeout=0.1)
    assert response is None
    assert base._expected_response_command == 0x01 # Should not clear on timeout

@pytest.mark.asyncio
async def test_send_command_and_wait_for_response_success(divoom_base_instance, mock_bleak_client):
    """Test send_command_and_wait_for_response with success."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = True
    expected_payload = b'\x11\x22\x33'
    
    # Mock send_command to put a response in the queue
    async def mock_send_command(command, args, write_with_response):
        await base.notification_queue.put({'command_id': command, 'payload': expected_payload})
        return True
    base.send_command = AsyncMock(side_effect=mock_send_command)

    response = await base.send_command_and_wait_for_response(0x01, [], timeout=1)
    assert response == expected_payload
    base.send_command.assert_called_once_with(0x01, [], write_with_response=True)
    assert base._expected_response_command is None

@pytest.mark.asyncio
async def test_send_command_and_wait_for_response_not_connected(divoom_base_instance, mock_bleak_client):
    """Test send_command_and_wait_for_response when not connected."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = False
    response = await base.send_command_and_wait_for_response(0x01, [], timeout=1)
    assert response is None
    assert base._expected_response_command is None

@pytest.mark.asyncio
async def test_send_command_success(divoom_base_instance, mock_bleak_client):
    """Test send_command success."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = True
    base._send_basic_protocol_payload = AsyncMock(return_value=True) # Mock the actual sending

    result = await base.send_command(0x01, [0x12, 0x34])
    assert result is True
    base._send_basic_protocol_payload.assert_called_once()

@pytest.mark.asyncio
async def test_send_command_with_string_command(divoom_base_instance, mock_bleak_client):
    """Test send_command with a string command name."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = True
    base._send_basic_protocol_payload = AsyncMock(return_value=True)

    result = await base.send_command("set light mode", [0x12, 0x34])
    assert result is True
    base._send_basic_protocol_payload.assert_called_once()

@pytest.mark.asyncio
async def test_send_payload_ios_le_success(divoom_base_instance, mock_bleak_client):
    """Test send_payload with iOS LE protocol success."""
    base = divoom_base_instance
    base.use_ios_le_protocol = True
    mock_bleak_client.is_connected = True
    base._send_ios_le_payload = AsyncMock(return_value=True)

    result = await base.send_payload([0x01, 0x12, 0x34])
    assert result is True
    base._send_ios_le_payload.assert_called_once()

@pytest.mark.asyncio
async def test_send_payload_basic_protocol_success(divoom_base_instance, mock_bleak_client):
    """Test send_payload with Basic Protocol success."""
    base = divoom_base_instance
    base.use_ios_le_protocol = False
    mock_bleak_client.is_connected = True
    base._send_basic_protocol_payload = AsyncMock(return_value=True)

    result = await base.send_payload([0x01, 0x12, 0x34])
    assert result is True
    base._send_basic_protocol_payload.assert_called_once()

@pytest.mark.asyncio
async def test_send_payload_reconnect_success(divoom_base_instance, mock_bleak_client):
    """Test send_payload with initial disconnection and successful reconnection."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = False # Initially disconnected
    base.connect = AsyncMock(return_value=None)
    base._send_basic_protocol_payload = AsyncMock(return_value=True)

    result = await base.send_payload([0x01, 0x12, 0x34])
    assert result is True
    base.connect.assert_called_once()
    base._send_basic_protocol_payload.assert_called_once()

@pytest.mark.asyncio
async def test_send_payload_reconnect_failure(divoom_base_instance, mock_bleak_client):
    """Test send_payload with initial disconnection and failed reconnection."""
    base = divoom_base_instance
    mock_bleak_client.is_connected = False # Initially disconnected
    base.connect = AsyncMock(side_effect=ConnectionError("Failed to connect"))
    base._send_basic_protocol_payload = AsyncMock(return_value=True)

    result = await base.send_payload([0x01, 0x12, 0x34], max_retries=1)
    assert result is False
    base.connect.assert_called_once()
    base._send_basic_protocol_payload.assert_not_called()
