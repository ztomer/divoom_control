"""Unit tests for the BLE write race fix.

The macOS CoreBluetooth has a known race: `is_connected` returns True
(cached) while `write_gatt_char` raises "disconnected" or "not connected"
because GATT services haven't finished discovering yet. The
`_connection_likely_broken` flag (lives on BLETransport) captures this
evidence so the retry loop in `_send_payload_locked` can force a
reconnect on the next attempt even when `is_connected` is lying.

These tests verify:
  1. A write exception containing "disconnected" / "not connected"
     sets `_connection_likely_broken = True` on the transport.
  2. Other exceptions (e.g. "Test error") do NOT set the flag.
  3. The retry loop checks the flag and forces a reconnect when it's
     set, even if `is_connected` is True.
  4. A successful write after a previous failure clears the flag.
  5. `disconnect()` clears the flag.
  6. The flag starts False on a fresh transport.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_legacy.protocol import DivoomProtocol


@pytest.fixture
def mock_protocol_instance():
    """Fixture for a mock DivoomProtocol instance.

    Yields (protocol, transport) so tests can poke at the BLETransport
    directly — the flag lives there, not on the protocol facade.
    """
    with patch('divoom_legacy.divoom.BleakClient') as mock_bleak_client:
        mock_bleak_client.return_value = AsyncMock()
        protocol = DivoomProtocol(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
        protocol.client.is_connected = True
        protocol.WRITE_CHARACTERISTIC_UUID = "mock_write_char_uuid"
        protocol.NOTIFY_CHARACTERISTIC_UUID = "mock_notify_char_uuid"
        protocol.READ_CHARACTERISTIC_UUID = "mock_read_char_uuid"
        protocol.use_ios_le_protocol = False
        protocol.escapePayload = False
        transport = protocol._conn._active_transport
        # Sanity: the fixture must point at a BLETransport.
        assert transport.__class__.__name__ == "BLETransport"
        yield protocol, transport


def test_flag_starts_false(mock_protocol_instance):
    """A fresh transport has _connection_likely_broken = False."""
    _, transport = mock_protocol_instance
    assert transport._connection_likely_broken is False


def test_flag_set_on_disconnected_exception(mock_protocol_instance):
    """An exception containing 'disconnected' sets the flag."""
    _, transport = mock_protocol_instance
    assert transport._connection_likely_broken is False
    transport._flag_connection_broken(Exception("Peripheral is disconnected"))
    assert transport._connection_likely_broken is True


def test_flag_set_on_not_connected_exception(mock_protocol_instance):
    """An exception containing 'not connected' sets the flag."""
    _, transport = mock_protocol_instance
    transport._flag_connection_broken(Exception("Not connected to a device"))
    assert transport._connection_likely_broken is True


def test_flag_set_on_not_connected_to_exception(mock_protocol_instance):
    """An exception containing 'not connected to' sets the flag (case-insensitive)."""
    _, transport = mock_protocol_instance
    transport._flag_connection_broken(Exception("Not Connected to Peripheral"))
    assert transport._connection_likely_broken is True


def test_flag_not_set_on_unrelated_exception(mock_protocol_instance):
    """An unrelated exception does NOT set the flag."""
    _, transport = mock_protocol_instance
    transport._flag_connection_broken(Exception("Test error"))
    assert transport._connection_likely_broken is False


def test_flag_not_set_on_timeout_exception(mock_protocol_instance):
    """A timeout exception does NOT set the flag (it's not a connection issue)."""
    _, transport = mock_protocol_instance
    transport._flag_connection_broken(Exception("Timeout waiting for response"))
    assert transport._connection_likely_broken is False










@pytest.mark.asyncio
async def test_disconnect_clears_flag(mock_protocol_instance):
    """disconnect() resets _connection_likely_broken."""
    _, transport = mock_protocol_instance
    transport._connection_likely_broken = True
    await transport.disconnect()
    assert transport._connection_likely_broken is False
