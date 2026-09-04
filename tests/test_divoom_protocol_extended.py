import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib.divoom import Divoom
from divoom_lib.display import Display, Light
from divoom_lib.system import System
from divoom_lib.media.music import Music
from divoom_lib.scheduling.alarm import Alarm
from divoom_lib.tool import Tool
from divoom_lib.scheduling.sleep import Sleep
from divoom_lib.game import Game
from divoom_lib.scheduling.timeplan import Timeplan
from bleak.exc import BleakError
import logging

@pytest.fixture
def mock_divoom_instance():
    """Fixture for a mock Divoom instance with patched methods."""
    with patch('divoom_lib.divoom.Divoom.send_command_and_wait_for_response', new_callable=AsyncMock) as mock_send_command_and_wait, \
         patch('divoom_lib.divoom.Divoom.send_command', new_callable=AsyncMock) as mock_send_command:
        
        divoom = Divoom(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
        divoom.client = AsyncMock()
        divoom.client.is_connected = True
        divoom.WRITE_CHARACTERISTIC_UUID = "mock_write_char_uuid"
        divoom.NOTIFY_CHARACTERISTIC_UUID = "mock_notify_char_uuid"
        divoom.use_ios_le_protocol = False
        divoom.escapePayload = False

        divoom.mock_send_command_and_wait_for_response = mock_send_command_and_wait
        divoom.mock_send_command = mock_send_command

        divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'
        divoom.mock_send_command.return_value = True

        yield divoom

@pytest.mark.asyncio
async def test_divoom_init_detailed(mock_divoom_instance):
    """Test Divoom initialization for correct types and default values."""
    divoom = Divoom(mac="AA:BB:CC:DD:EE:FF")
    assert isinstance(divoom.display, Display)
    assert isinstance(divoom.system, System)
    assert isinstance(divoom.light, Light)
    assert isinstance(divoom.music, Music)
    assert isinstance(divoom.alarm, Alarm)
    assert isinstance(divoom.tool, Tool)
    assert isinstance(divoom.sleep, Sleep)
    assert isinstance(divoom.game, Game)
    assert isinstance(divoom.timeplan, Timeplan)
    
    assert divoom.WRITE_CHARACTERISTIC_UUID == "49535343-8841-43f4-a8d4-ecbe34729bb3"
    assert divoom.NOTIFY_CHARACTERISTIC_UUID == "49535343-1e4d-4bd9-ba61-23c647249616"
    assert divoom.READ_CHARACTERISTIC_UUID == "49535343-1e4d-4bd9-ba61-23c647249616"
    assert divoom.SPP_CHARACTERISTIC_UUID == "49535343-6daa-4d02-abf6-19569aca69fe"
    assert divoom.escapePayload is False
    assert divoom.use_ios_le_protocol is None
    assert divoom.device_name is None

@pytest.mark.asyncio
async def test_send_diagnostic_payload_with_existing_cache(mock_divoom_instance):
    """Test _send_diagnostic_payload with a non-empty device_cache."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()
    
    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    existing_cache = {"some_key": "some_value"}
    result = await divoom._send_diagnostic_payload(
        "mock_uuid", [0x01, 0xFF, 0x00, 0x00, 0x64, 0x00, 0x01], existing_cache, "mock_cache_dir", "mock_device_id", mock_cache_util
    )
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    saved_cache = mock_cache_util.save_device_cache.call_args[0][2]
    assert saved_cache['some_key'] == 'some_value'
    assert 'last_successful_payload' in saved_cache

@pytest.mark.asyncio
async def test_handle_cached_payload_ios_success(mock_divoom_instance):
    """Test _handle_cached_payload for the case where last_successful_use_ios_le is True."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    cached_data = {
        "last_successful_payload": ["01", "00", "ff", "00", "64", "00", "01"],
        "last_successful_use_ios_le": True,
        "escapePayload": False,
    }
    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    result = await divoom._handle_cached_payload(
        "mock_uuid", cached_data, "mock_cache_dir", "mock_device_id", mock_cache_util
    )
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    assert divoom.use_ios_le_protocol is True
    assert divoom.escapePayload is False

@pytest.mark.asyncio
async def test_handle_cached_payload_invalid_payload(mock_divoom_instance):
    """Test the try-except block in _handle_cached_payload with an invalid hex string in the cache."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    cached_data = {"last_successful_payload": ["01", "zz", "00", "00", "64", "00", "01"]}

    result = await divoom._handle_cached_payload(
        "mock_uuid", cached_data, "mock_cache_dir", "mock_device_id", mock_cache_util
    )
    assert result is False
    divoom.mock_send_command_and_wait_for_response.assert_not_called()
    mock_cache_util.save_device_cache.assert_not_called()

@pytest.mark.asyncio
async def test_probe_write_characteristics_no_chars(mock_divoom_instance):
    """Test probe_write_characteristics_and_try_channel_switch with an empty write_chars list."""
    divoom = mock_divoom_instance
    result = await divoom.probe_write_characteristics_and_try_channel_switch(
        [], [], [], {}, "mock_cache_dir", "mock_device_id", [], None
    )
    assert result is None

@pytest.mark.asyncio
async def test_probe_write_characteristics_fallback_exception(mock_divoom_instance):
    """Test the try-except block in the fallback channel switch sequence."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    write_chars = [MagicMock(uuid="char1_uuid")]
    divoom.mock_send_command_and_wait_for_response.return_value = None # All probes fail
    divoom.mock_send_command.side_effect = BleakError("Test Exception")

    result = await divoom.probe_write_characteristics_and_try_channel_switch(
        write_chars, [], [], {}, "mock_cache_dir", "mock_device_id", [], mock_cache_util
    )
    assert result is None
    assert divoom.mock_send_command.call_count > 0

@pytest.mark.asyncio
async def test_set_canonical_light_with_custom_rgb(mock_divoom_instance):
    """Test set_canonical_light with a custom rgb value."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'
    custom_rgb = [10, 20, 30]

    result = await divoom.set_canonical_light("mock_cache_dir", "mock_device_id", mock_cache_util, rgb=custom_rgb)
    
    assert result is True
    divoom.mock_send_command_and_wait_for_response.assert_called_once()
    call_args = divoom.mock_send_command_and_wait_for_response.call_args[0]
    assert call_args[1][1:4] == custom_rgb
    mock_cache_util.save_device_cache.assert_called_once()

@pytest.mark.asyncio
async def test_set_canonical_light_cache_os_error(mock_divoom_instance):
    """Test the try-except OSError block in set_canonical_light."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache.side_effect = OSError("Test OS Error")

    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    result = await divoom.set_canonical_light("mock_cache_dir", "mock_device_id", mock_cache_util)
    
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()

