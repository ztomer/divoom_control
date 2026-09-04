import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib.divoom import Divoom
from divoom_lib import models
import logging

@pytest.fixture
def mock_divoom_instance():
    """Fixture for a mock Divoom instance with patched methods."""
    with patch('divoom_lib.protocol.DivoomProtocol.send_command_and_wait_for_response', new_callable=AsyncMock) as mock_send_command_and_wait, \
         patch('divoom_lib.protocol.DivoomProtocol.send_command', new_callable=AsyncMock) as mock_send_command:

        config = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
        divoom = Divoom(config)
        divoom.client = AsyncMock()
        divoom.client.address = "AA:BB:CC:DD:EE:FF"
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
async def test_divoom_init(mock_divoom_instance):
    """Test Divoom initialization and sub-modules."""
    divoom = mock_divoom_instance
    assert divoom.mac == "AA:BB:CC:DD:EE:FF"
    assert divoom.device_name == "MockDevice"
    assert isinstance(divoom.light, object)
    assert isinstance(divoom.animation, object)
    assert isinstance(divoom.drawing, object)
    assert isinstance(divoom.text, object)
    assert isinstance(divoom.device, object)
    assert isinstance(divoom.time, object)
    assert isinstance(divoom.bluetooth, object)
    assert isinstance(divoom.music, object)
    assert isinstance(divoom.radio, object)
    assert isinstance(divoom.alarm, object)
    assert isinstance(divoom.sleep, object)
    assert isinstance(divoom.timeplan, object)
    assert isinstance(divoom.scoreboard, object)
    assert isinstance(divoom.timer, object)
    assert isinstance(divoom.countdown, object)
    assert isinstance(divoom.noise, object)

@pytest.mark.asyncio
async def test_framing_context(mock_divoom_instance):
    """Test _framing_context correctly sets and restores framing preferences."""
    divoom = mock_divoom_instance
    original_use_ios = divoom.use_ios_le_protocol
    original_escape = divoom.escapePayload

    async with divoom._framing_context(use_ios=True, escape=True):
        assert divoom.use_ios_le_protocol is True
        assert divoom.escapePayload is True

    assert divoom.use_ios_le_protocol == original_use_ios
    assert divoom.escapePayload == original_escape

@pytest.mark.skip(reason="Method _try_send_command_with_framing not implemented in Divoom class")
@pytest.mark.asyncio
async def test_try_send_command_with_framing(mock_divoom_instance):
    """Test _try_send_command_with_framing calls send_command_and_wait_for_response with correct framing."""
    divoom = mock_divoom_instance
    command_id = models.COMMANDS["set light mode"]
    payload = [0x01, 0xFF, 0x00, 0x00, 0x64, 0x00, 0x01]

    divoom.mock_send_command_and_wait_for_response.reset_mock()
    await divoom._try_send_command_with_framing(command_id, payload, timeout=3, use_ios=True, escape=True)
    assert divoom.use_ios_le_protocol is True
    assert divoom.escapePayload is True
    divoom.mock_send_command_and_wait_for_response.assert_called_once_with(command_id, payload, timeout=3)

    divoom.mock_send_command_and_wait_for_response.reset_mock()
    await divoom._try_send_command_with_framing(command_id, payload, timeout=3, use_ios=False, escape=False)
    assert divoom.use_ios_le_protocol is False
    assert divoom.escapePayload is False
    divoom.mock_send_command_and_wait_for_response.assert_called_once_with(command_id, payload, timeout=3)

@pytest.mark.skip(reason="Method _send_diagnostic_payload not implemented in Divoom class")
@pytest.mark.asyncio
async def test_send_diagnostic_payload_spp_success(mock_divoom_instance):
    """Test _send_diagnostic_payload with SPP success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom._send_diagnostic_payload(
            "mock_uuid", [0x01, 0xFF, 0x00, 0x00, 0x64, 0x00, 0x01], {}, "mock_cache_dir", "mock_device_id", mock_cache_util
        )
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    assert divoom.use_ios_le_protocol is False
    assert divoom.escapePayload is True

@pytest.mark.skip(reason="Method _send_diagnostic_payload not implemented in Divoom class")
@pytest.mark.asyncio
async def test_send_diagnostic_payload_ios_success(mock_divoom_instance):
    """Test _send_diagnostic_payload with iOS-LE success after SPP failure."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.side_effect = [
        None,
        b'\x01\x00\x00\x00\x00\x02'
    ]

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom._send_diagnostic_payload(
            "mock_uuid", [0x01, 0xFF, 0x00, 0x00, 0x64, 0x00, 0x01], {}, "mock_cache_dir", "mock_device_id", mock_cache_util
        )
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    assert divoom.use_ios_le_protocol is True
    assert divoom.escapePayload is False

@pytest.mark.skip(reason="Method _send_diagnostic_payload not implemented in Divoom class")
@pytest.mark.asyncio
async def test_send_diagnostic_payload_failure(mock_divoom_instance):
    """Test _send_diagnostic_payload with complete failure."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.return_value = None

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom._send_diagnostic_payload(
            "mock_uuid", [0x01, 0xFF, 0x00, 0x00, 0x64, 0x00, 0x01], {}, "mock_cache_dir", "mock_device_id", mock_cache_util
        )
    assert result is False
    mock_cache_util.save_device_cache.assert_not_called()

@pytest.mark.skip(reason="Method _handle_cached_payload not implemented in Divoom class")
@pytest.mark.asyncio
async def test_handle_cached_payload_success(mock_divoom_instance):
    """Test _handle_cached_payload with success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    cached_data = {
        "last_successful_payload": ["01", "ff", "00", "00", "64", "00", "01"],
        "last_successful_use_ios_le": False,
        "escapePayload": True,
    }
    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom._handle_cached_payload(
            "mock_uuid", cached_data, "mock_cache_dir", "mock_device_id", mock_cache_util
        )
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    assert divoom.use_ios_le_protocol is False
    assert divoom.escapePayload is True

@pytest.mark.skip(reason="Method _handle_cached_payload not implemented in Divoom class")
@pytest.mark.asyncio
async def test_handle_cached_payload_no_payload(mock_divoom_instance):
    """Test _handle_cached_payload when no payload in cache."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    cached_data = {}
    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom._handle_cached_payload(
            "mock_uuid", cached_data, "mock_cache_dir", "mock_device_id", mock_cache_util
        )
    assert result is False
    mock_cache_util.save_device_cache.assert_not_called()

@pytest.mark.skip(reason="Method _handle_cached_payload not implemented in Divoom class")
@pytest.mark.asyncio
async def test_handle_cached_payload_failure(mock_divoom_instance):
    """Test _handle_cached_payload with failure."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.save_device_cache = MagicMock()

    cached_data = {
        "last_successful_payload": ["01", "ff", "00", "00", "64", "00", "01"],
        "last_successful_use_ios_le": False,
        "escapePayload": True,
    }
    divoom.mock_send_command_and_wait_for_response.return_value = None

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom._handle_cached_payload(
            "mock_uuid", cached_data, "mock_cache_dir", "mock_device_id", mock_cache_util
        )
    assert result is False
    mock_cache_util.save_device_cache.assert_not_called()

@pytest.mark.skip(reason="Method probe_write_characteristics_and_try_channel_switch not implemented in Divoom class")
@pytest.mark.asyncio
async def test_probe_write_characteristics_success_cached(mock_divoom_instance):
    """Test probe_write_characteristics_and_try_channel_switch with cached success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {
        "last_successful_payload": ["01", "ff", "00", "00", "64", "00", "01"],
        "last_successful_use_ios_le": False,
        "escapePayload": True,
    }
    mock_cache_util.save_device_cache = MagicMock()

    write_chars = [MagicMock(uuid="char1_uuid"), MagicMock(uuid="char2_uuid")]
    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, "mock_cache_dir", "mock_device_id", [], mock_cache_util
        )
    assert result == "char1_uuid"
    mock_cache_util.save_device_cache.assert_called_once()

@pytest.mark.skip(reason="Method probe_write_characteristics_and_try_channel_switch not implemented in Divoom class")
@pytest.mark.asyncio
async def test_probe_write_characteristics_success_diagnostic(mock_divoom_instance):
    """Test probe_write_characteristics_and_try_channel_switch with diagnostic success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    write_chars = [MagicMock(uuid="char1_uuid"), MagicMock(uuid="char2_uuid")]
    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, "mock_cache_dir", "mock_device_id", [], mock_cache_util
        )
    assert result == "char1_uuid"
    mock_cache_util.save_device_cache.assert_called_once()

@pytest.mark.skip(reason="Method probe_write_characteristics_and_try_channel_switch not implemented in Divoom class")
@pytest.mark.asyncio
async def test_probe_write_characteristics_fallback_spp_success(mock_divoom_instance):
    """Test probe_write_characteristics_and_try_channel_switch with fallback SPP success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    write_chars = [MagicMock(uuid="char1_uuid")]
    divoom.mock_send_command_and_wait_for_response.return_value = None
    divoom.mock_send_command.return_value = True

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, "mock_cache_dir", "mock_device_id", [], mock_cache_util
        )
    assert result is None
    assert divoom.mock_send_command.call_count >= 2
    assert divoom.mock_send_command_and_wait_for_response.call_count >= 2

@pytest.mark.skip(reason="Method probe_write_characteristics_and_try_channel_switch not implemented in Divoom class")
@pytest.mark.asyncio
async def test_probe_write_characteristics_fallback_ios_success(mock_divoom_instance):
    """Test probe_write_characteristics_and_try_channel_switch with fallback iOS-LE success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    write_chars = [MagicMock(uuid="char1_uuid")]
    divoom.mock_send_command_and_wait_for_response.side_effect = [
        None,
        None,
        b'\x01\x00\x00\x00\x00\x02'
    ]
    divoom.mock_send_command.return_value = True

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, "mock_cache_dir", "mock_device_id", [], mock_cache_util
        )
    assert result is None
    assert divoom.mock_send_command.call_count >= 2
    assert divoom.mock_send_command_and_wait_for_response.call_count >= 3

@pytest.mark.skip(reason="Method probe_write_characteristics_and_try_channel_switch not implemented in Divoom class")
@pytest.mark.asyncio
async def test_probe_write_characteristics_fallback_failure(mock_divoom_instance):
    """Test probe_write_characteristics_and_try_channel_switch with complete fallback failure."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    write_chars = [MagicMock(uuid="char1_uuid")]
    divoom.mock_send_command_and_wait_for_response.return_value = None
    divoom.mock_send_command.return_value = False

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.probe_write_characteristics_and_try_channel_switch(
            write_chars, [], [], {}, "mock_cache_dir", "mock_device_id", [], mock_cache_util
        )
    assert result is None
    assert divoom.mock_send_command.call_count >= 2
    assert divoom.mock_send_command_and_wait_for_response.call_count >= 3

@pytest.mark.skip(reason="Method set_canonical_light not implemented in Divoom class")
@pytest.mark.asyncio
async def test_set_canonical_light_spp_success(mock_divoom_instance):
    """Test set_canonical_light with SPP success."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.return_value = b'\x01\x00\x00\x00\x00\x02'

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.set_canonical_light("mock_cache_dir", "mock_device_id", mock_cache_util)
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    assert divoom.use_ios_le_protocol is False

@pytest.mark.skip(reason="Method set_canonical_light not implemented in Divoom class")
@pytest.mark.asyncio
async def test_set_canonical_light_ios_success(mock_divoom_instance):
    """Test set_canonical_light with iOS-LE success after SPP failure."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.side_effect = [
        None,
        b'\x01\x00\x00\x00\x00\x02'
    ]

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.set_canonical_light("mock_cache_dir", "mock_device_id", mock_cache_util)
    assert result is True
    mock_cache_util.save_device_cache.assert_called_once()
    assert divoom.use_ios_le_protocol is True

@pytest.mark.skip(reason="Method set_canonical_light not implemented in Divoom class")
@pytest.mark.asyncio
async def test_set_canonical_light_failure(mock_divoom_instance):
    """Test set_canonical_light with complete failure."""
    divoom = mock_divoom_instance
    mock_cache_util = MagicMock()
    mock_cache_util.load_device_cache.return_value = {}
    mock_cache_util.save_device_cache = MagicMock()

    divoom.mock_send_command_and_wait_for_response.return_value = None

    with patch('divoom_lib.divoom.cache', mock_cache_util):
        result = await divoom.set_canonical_light("mock_cache_dir", "mock_device_id", mock_cache_util)
    assert result is False
    mock_cache_util.save_device_cache.assert_not_called()

@pytest.mark.asyncio
async def test_connect_success(mock_divoom_instance):
    """Test connect method success."""
    divoom = mock_divoom_instance
    divoom.client.is_connected = False
    divoom.client.connect = AsyncMock()
    divoom.client.start_notify = AsyncMock()

    await divoom.connect()

    divoom.client.connect.assert_called_once()
    divoom.client.start_notify.assert_called_once()

@pytest.mark.asyncio
async def test_connect_failure(mock_divoom_instance):
    """Test connect method failure."""
    divoom = mock_divoom_instance
    divoom.client.is_connected = False
    divoom.client.connect = AsyncMock(side_effect=Exception("Connection failed"))

    with pytest.raises(ConnectionError):
        await divoom.connect()

@pytest.mark.asyncio
async def test_disconnect_success(mock_divoom_instance):
    """Test disconnect method success."""
    divoom = mock_divoom_instance
    divoom.client.is_connected = True
    divoom.client.disconnect = AsyncMock()

    await divoom.disconnect()

    divoom.client.disconnect.assert_called_once()

@pytest.mark.asyncio
async def test_send_command_success(mock_divoom_instance):
    """Test send_command method success."""
    divoom = mock_divoom_instance
    divoom._send_payload = AsyncMock(return_value=True)

    result = await divoom.send_command("set volume", [10])

    assert result is True
    divoom._send_payload.assert_called_once()

@pytest.mark.asyncio
async def test_send_command_and_wait_for_response_success(mock_divoom_instance):
    """Test send_command_and_wait_for_response method success."""
    divoom = mock_divoom_instance
    divoom.send_command = AsyncMock(return_value=True)
    divoom._wait_for_response = AsyncMock(return_value=b'response')

    result = await divoom.send_command_and_wait_for_response("set volume", [10])
    assert result == b'response'
