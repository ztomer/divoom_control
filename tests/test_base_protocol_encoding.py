"""DivoomBase protocol-encoding helper coverage (split from test_base.py)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib import models as constants
from bleak.exc import BleakError
from tests.support.divoom_base_common import divoom_base_instance, mock_bleak_client  # noqa: F401


def test_int2hexlittle(divoom_base_instance):
    """Test _int2hexlittle conversion."""
    base = divoom_base_instance
    assert base._int2hexlittle(0x1234) == "3412"
    assert base._int2hexlittle(0x0001) == "0100"
    assert base._int2hexlittle(0xFFFF) == "ffff"

def test_escape_payload(divoom_base_instance):
    """Test _escape_payload function."""
    base = divoom_base_instance
    payload = [0x01, 0x02, 0x03, 0x11, 0x13, 0x14, 0x04]
    expected_escaped = [0x03, 0x04, 0x03, 0x05, 0x03, 0x06, 0x11, 0x13, 0x14, 0x04]
    assert base._escape_payload(payload) == expected_escaped

    payload_with_all_escapes = [0x01, 0x02, 0x03, constants.ESCAPE_BYTE_1, constants.ESCAPE_BYTE_2, constants.ESCAPE_BYTE_3, 0x04]
    expected_all_escaped = [0x03, 0x04, 0x03, 0x05, 0x03, 0x06] + constants.ESCAPE_SEQUENCE_1 + constants.ESCAPE_SEQUENCE_2 + constants.ESCAPE_SEQUENCE_3 + [0x04]
    assert base._escape_payload(payload_with_all_escapes) == expected_all_escaped

def test_getCRC(divoom_base_instance):
    """Test _getCRC checksum calculation."""
    base = divoom_base_instance
    assert base._getCRC([0x01, 0x02, 0x03]) == "0600"
    assert base._getCRC([0xFF, 0xFF]) == "fe01" # 0x1FE -> 0xFE01 (little endian)
    assert base._getCRC([0x00]) == "0000"

def test_make_message_basic_protocol(divoom_base_instance):
    """Test _make_message for basic protocol."""
    base = divoom_base_instance
    base.escapePayload = False
    payload_bytes = [0x01, 0x12, 0x34]
    # Length = Cmd (1) + Payload (3) + Checksum (2) = 6 -> wait, len is 5!
    # Expected: 0x01 0x0500 0x011234 0x4c00 0x02
    expected_hex = "0105000112344c0002"
    assert base._make_message(payload_bytes).hex() == expected_hex

def test_make_message_basic_protocol_escaped(divoom_base_instance):
    """Test _make_message for basic protocol with escaping."""
    base = divoom_base_instance
    base.escapePayload = True
    payload_bytes = [0x01, 0x04, 0x02]
    # Escaped payload: [0x03, 0x04, 0x04, 0x03, 0x05]
    # Expected: 0x01 0x0700 0x0304040305 0x1a00 0x02
    expected_hex = "01070003040403051a0002"
    assert base._make_message(payload_bytes).hex() == expected_hex

def test_make_message_ios_le(divoom_base_instance):
    """Test _make_message_ios_le for iOS LE protocol."""
    base = divoom_base_instance
    payload_bytes = [0x01, 0x12, 0x34] # Cmd ID 0x01, Data 0x12, 0x34
    packet_number = 0x00000000
    expected_hex = "feefaa550600000112344d0002"
    assert base._make_message_ios_le(payload_bytes, packet_number).hex() == expected_hex
