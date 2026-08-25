"""DivoomBase notification-handling coverage (split from test_base.py)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib import models as constants
from bleak.exc import BleakError
from tests.support.divoom_base_common import divoom_base_instance, mock_bleak_client  # noqa: F401


def test_convert_color(divoom_base_instance):
    """Test color conversion."""
    base = divoom_base_instance
    assert base.convert_color("#FF0000") == [255, 0, 0]
    assert base.convert_color((0, 255, 0)) == [0, 255, 0]
    assert base.convert_color([0, 0, 255]) == [0, 0, 255]
    assert base.convert_color("red") == [255, 0, 0]

@pytest.mark.asyncio
async def test_handle_ios_le_notification_expected_response(divoom_base_instance):
    """Test iOS LE notification handler with an expected response."""
    base = divoom_base_instance
    base.use_ios_le_protocol = True
    base._expected_response_command = 0x01 # Example command ID

    # Mock iOS LE data (new format):
    # header(4) + length(2) + packet_num(1) + cmd_id(1) + data + checksum(2) + end(1)
    cmd_id = 0x01
    packet_num = 0x00
    data_payload = [0x12, 0x34]

    # total wire = 4+2+1+1+len(data)+2+1; length_field = total - 7
    data_len_val = 1 + 1 + len(data_payload) + 2  # 6
    data_len_bytes = data_len_val.to_bytes(2, 'little')

    checksum_input = list(data_len_bytes) + [packet_num, cmd_id] + data_payload
    checksum_val = sum(checksum_input)
    checksum_bytes = checksum_val.to_bytes(2, 'little')

    mock_data = (
        bytearray(constants.IOS_LE_HEADER)
        + bytearray(data_len_bytes)
        + bytearray([packet_num, cmd_id])
        + bytearray(data_payload)
        + bytearray(checksum_bytes)
        + bytearray([constants.MESSAGE_END_BYTE])
    )

    result = base._handle_ios_le_notification(mock_data)
    assert result is True
    assert not base.notification_queue.empty()
    response = await base.notification_queue.get()
    assert response['command_id'] == cmd_id
    assert response['payload'] == bytearray(data_payload)
    assert base._expected_response_command is None

@pytest.mark.asyncio
async def test_handle_ios_le_notification_generic_ack(divoom_base_instance):
    """Test iOS LE notification handler with a generic ACK response."""
    base = divoom_base_instance
    base.use_ios_le_protocol = True
    base._expected_response_command = 0x45 # A command that expects a generic ACK

    # Mock generic ACK (0x33)
    cmd_id = 0x33
    packet_num = 0x00
    data_payload = [] # Generic ACK might have empty payload

    data_len_val = 1 + 1 + len(data_payload) + 2  # 4
    data_len_bytes = data_len_val.to_bytes(2, 'little')

    checksum_input = list(data_len_bytes) + [packet_num, cmd_id] + data_payload
    checksum_val = sum(checksum_input)
    checksum_bytes = checksum_val.to_bytes(2, 'little')

    mock_data = (
        bytearray(constants.IOS_LE_HEADER)
        + bytearray(data_len_bytes)
        + bytearray([packet_num, cmd_id])
        + bytearray(data_payload)
        + bytearray(checksum_bytes)
        + bytearray([constants.MESSAGE_END_BYTE])
    )

    # Temporarily add 0x45 to GENERIC_ACK_COMMANDS for this test
    original_generic_acks = constants.GENERIC_ACK_COMMANDS
    constants.GENERIC_ACK_COMMANDS = list(original_generic_acks) + [0x45]

    try:
        result = base._handle_ios_le_notification(mock_data)
        assert result is True
        assert not base.notification_queue.empty()
        response = await base.notification_queue.get()
        assert response['command_id'] == cmd_id
        assert response['payload'] == bytearray(data_payload)
        # Clearing the scalar on the generic ACK is load-bearing for the protocol
        # autoprobe (0x46 probe). R53.35 tried to keep it set (for a theoretical
        # two-frame iOS-LE read-back) but that mis-detected real Basic devices as
        # iOS-LE and broke ALL read-backs on hardware — reverted.
        assert base._expected_response_command is None
    finally:
        constants.GENERIC_ACK_COMMANDS = original_generic_acks # Restore original

@pytest.mark.asyncio
async def test_handle_ios_le_notification_unexpected_response(divoom_base_instance):
    """Test iOS LE notification handler with an unexpected response."""
    base = divoom_base_instance
    base.use_ios_le_protocol = True
    base._expected_response_command = 0x01 # Expecting 0x01

    # Mock iOS LE data for command 0x02 (unexpected)
    cmd_id = 0x02
    packet_num = 0x00
    data_payload = [0x56, 0x78]

    data_len_val = 1 + 1 + len(data_payload) + 2  # 6
    data_len_bytes = data_len_val.to_bytes(2, 'little')

    checksum_input = list(data_len_bytes) + [packet_num, cmd_id] + data_payload
    checksum_val = sum(checksum_input)
    checksum_bytes = checksum_val.to_bytes(2, 'little')

    mock_data = (
        bytearray(constants.IOS_LE_HEADER)
        + bytearray(data_len_bytes)
        + bytearray([packet_num, cmd_id])
        + bytearray(data_payload)
        + bytearray(checksum_bytes)
        + bytearray([constants.MESSAGE_END_BYTE])
    )

    result = base._handle_ios_le_notification(mock_data)
    assert result is False # Should return False for unexpected
    assert base.notification_queue.empty() # Should not put in queue
    assert base._expected_response_command == 0x01 # Should not clear expectation

@pytest.mark.asyncio
async def test_handle_basic_protocol_notification_single_message(divoom_base_instance):
    """Test basic protocol notification handler with a single valid message."""
    base = divoom_base_instance
    base.use_ios_le_protocol = False
    base._expected_response_command = 0x01

    # Mock basic protocol data: START (1), LEN (2), CMD (1), PAYLOAD (variable), CHECKSUM (2), END (1)
    # Example: 0x01 0x0500 (len 5) 0x01 (cmd) 0x1234 (payload) 0xXXYY (checksum) 0x02
    cmd_id = 0x01
    payload_data = [0x12, 0x34]
    
    # Length = Cmd (1) + Payload (2) + Checksum (2) = 5
    length_val = 1 + len(payload_data) + 2
    length_bytes = length_val.to_bytes(2, 'little')

    checksum_input = list(length_bytes) + [cmd_id] + payload_data
    checksum_val = sum(checksum_input)
    checksum_bytes = checksum_val.to_bytes(2, 'little')

    mock_data = bytearray([constants.MESSAGE_START_BYTE]) + bytearray(length_bytes) + bytearray([cmd_id]) + bytearray(payload_data) + bytearray(checksum_bytes) + bytearray([constants.MESSAGE_END_BYTE])

    result = base._handle_basic_protocol_notification(mock_data)
    assert result is True
    assert not base.notification_queue.empty()
    response = await base.notification_queue.get()
    assert response['command_id'] == cmd_id
    assert response['payload'] == bytearray(payload_data)
    # _expected_response_command is cleared by wait_for_response, not by handler

@pytest.mark.asyncio
async def test_handle_basic_protocol_notification_multiple_messages(divoom_base_instance):
    """Test basic protocol notification handler with multiple messages in one data chunk."""
    base = divoom_base_instance
    base.use_ios_le_protocol = False
    base._expected_response_command = 0x01

    # Message 1
    cmd_id_1 = 0x01
    payload_data_1 = [0x11, 0x22]
    length_val_1 = 1 + len(payload_data_1) + 2
    length_bytes_1 = length_val_1.to_bytes(2, 'little')
    checksum_input_1 = list(length_bytes_1) + [cmd_id_1] + payload_data_1
    checksum_val_1 = sum(checksum_input_1)
    checksum_bytes_1 = checksum_val_1.to_bytes(2, 'little')
    message_1 = bytearray([constants.MESSAGE_START_BYTE]) + bytearray(length_bytes_1) + bytearray([cmd_id_1]) + bytearray(payload_data_1) + bytearray(checksum_bytes_1) + bytearray([constants.MESSAGE_END_BYTE])

    # Message 2
    cmd_id_2 = 0x02
    payload_data_2 = [0x33, 0x44, 0x55]
    length_val_2 = 1 + len(payload_data_2) + 2
    length_bytes_2 = length_val_2.to_bytes(2, 'little')
    checksum_input_2 = list(length_bytes_2) + [cmd_id_2] + payload_data_2
    checksum_val_2 = sum(checksum_input_2)
    checksum_bytes_2 = checksum_val_2.to_bytes(2, 'little')
    message_2 = bytearray([constants.MESSAGE_START_BYTE]) + bytearray(length_bytes_2) + bytearray([cmd_id_2]) + bytearray(payload_data_2) + bytearray(checksum_bytes_2) + bytearray([constants.MESSAGE_END_BYTE])

    mock_data = message_1 + message_2

    result = base._handle_basic_protocol_notification(mock_data)
    assert result is True
    assert not base.notification_queue.empty()

    response1 = await base.notification_queue.get()
    assert response1['command_id'] == cmd_id_1
    assert response1['payload'] == bytearray(payload_data_1)

    response2 = await base.notification_queue.get()
    assert response2['command_id'] == cmd_id_2
    assert response2['payload'] == bytearray(payload_data_2)
    assert base.notification_queue.empty()

@pytest.mark.asyncio
async def test_handle_basic_protocol_notification_junk_data_then_message(divoom_base_instance):
    """Test basic protocol notification handler with junk data before a valid message."""
    base = divoom_base_instance
    base.use_ios_le_protocol = False
    base._expected_response_command = 0x01

    cmd_id = 0x01
    payload_data = [0x12, 0x34]
    length_val = 1 + len(payload_data) + 2
    length_bytes = length_val.to_bytes(2, 'little')
    checksum_input = list(length_bytes) + [cmd_id] + payload_data
    checksum_val = sum(checksum_input)
    checksum_bytes = checksum_val.to_bytes(2, 'little')
    message = bytearray([constants.MESSAGE_START_BYTE]) + bytearray(length_bytes) + bytearray([cmd_id]) + bytearray(payload_data) + bytearray(checksum_bytes) + bytearray([constants.MESSAGE_END_BYTE])

    junk_data = bytearray([0xFF, 0xEE, 0xDD])
    mock_data = junk_data + message

    result = base._handle_basic_protocol_notification(mock_data)
    assert result is True
    assert not base.notification_queue.empty()
    response = await base.notification_queue.get()
    assert response['command_id'] == cmd_id
    assert response['payload'] == bytearray(payload_data)

@pytest.mark.asyncio
async def test_handle_basic_protocol_notification_incomplete_message(divoom_base_instance):
    """Test basic protocol notification handler with an incomplete message."""
    base = divoom_base_instance
    base.use_ios_le_protocol = False
    base._expected_response_command = 0x01

    cmd_id = 0x01
    payload_data = [0x12, 0x34]
    length_val = 1 + len(payload_data) + 2
    length_bytes = length_val.to_bytes(2, 'little')
    checksum_input = list(length_bytes) + [cmd_id] + payload_data
    checksum_val = sum(checksum_input)
    checksum_bytes = checksum_val.to_bytes(2, 'little')
    
    # Missing end byte
    incomplete_message = bytearray([constants.MESSAGE_START_BYTE]) + bytearray(length_bytes) + bytearray([cmd_id]) + bytearray(payload_data) + bytearray(checksum_bytes)

    result = base._handle_basic_protocol_notification(incomplete_message)
    assert result is True # It processes what it can and leaves the rest in buffer
    assert base.notification_queue.empty()
    assert base.message_buf == incomplete_message # Should still be in buffer

@pytest.mark.asyncio
async def test_handle_basic_protocol_notification_checksum_mismatch(divoom_base_instance):
    """Test basic protocol notification handler with a checksum mismatch."""
    base = divoom_base_instance
    base.use_ios_le_protocol = False
    base._expected_response_command = 0x01

    cmd_id = 0x01
    payload_data = [0x12, 0x34]
    length_val = 1 + len(payload_data) + 2
    length_bytes = length_val.to_bytes(2, 'little')
    
    # Incorrect checksum
    incorrect_checksum_bytes = (0x0000).to_bytes(2, 'little') # Deliberately wrong

    mock_data = bytearray([constants.MESSAGE_START_BYTE]) + bytearray(length_bytes) + bytearray([cmd_id]) + bytearray(payload_data) + bytearray(incorrect_checksum_bytes) + bytearray([constants.MESSAGE_END_BYTE])

    result = base._handle_basic_protocol_notification(mock_data)
    assert result is True
    assert base.notification_queue.empty() # Should discard due to checksum mismatch
