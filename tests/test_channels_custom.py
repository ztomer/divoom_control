import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.display.custom_channel import CustomChannel
from divoom_lib.divoom import Divoom as DivoomBase # Import DivoomBase for type hinting

@pytest.fixture
def mock_divoom_instance():
    """Fixture for a mock DivoomBase instance."""
    mock = AsyncMock(spec=DivoomBase)
    mock.send_command = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_custom_channel_init(mock_divoom_instance):
    """Test CustomChannel initialization."""
    channel = CustomChannel(mock_divoom_instance)
    
    # To properly test init without the RuntimeWarning, we need an event loop
    # and ensure _update_message is called.
    # For now, we'll test the attributes set.
    channel = CustomChannel(mock_divoom_instance)
    assert channel._divoom_instance == mock_divoom_instance
    assert channel._PACKAGE_HEADER == "4505"

@pytest.mark.asyncio
async def test_custom_channel_show(mock_divoom_instance):
    """Test the show method calls _update_message."""
    channel = CustomChannel(mock_divoom_instance)
    
    # Reset mock to clear calls from __init__
    mock_divoom_instance.send_command.reset_mock()

    await channel.show()
    mock_divoom_instance.send_command.assert_called_once_with(0x45, [0x05])

@pytest.mark.asyncio
async def test_custom_channel_update_message(mock_divoom_instance):
    """Test _update_message sends the correct command."""
    channel = CustomChannel(mock_divoom_instance)
    
    # Reset mock to clear calls from __init__
    mock_divoom_instance.send_command.reset_mock()

    await channel._update_message()
    mock_divoom_instance.send_command.assert_called_once_with(0x45, [0x05])
