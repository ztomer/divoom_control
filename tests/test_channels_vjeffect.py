import pytest
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.display.vjeffect_channel import VJEffectChannel
from divoom_lib.divoom import Divoom as DivoomBase
from divoom_lib.models import VJEffectType

@pytest.fixture
def mock_divoom_instance():
    """Fixture for a mock DivoomBase instance.

    R53.43: previously this monkeypatched ``number2HexString`` onto the mock,
    which MASKED a real bug — VJEffectChannel called it as
    ``self._divoom_instance.number2HexString`` but it is a module-level helper
    in ``utils.converters``, not a method on Divoom. The test passed falsely.
    The channel now imports the real converter, so the mock must NOT provide it
    (re-adding it would re-mask the AttributeError regression).
    """
    mock = AsyncMock(spec=DivoomBase)
    mock.send_command = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_vjeffect_channel_init_defaults(mock_divoom_instance):
    """Test VJEffectChannel initialization with default options."""
    channel = VJEffectChannel(mock_divoom_instance)
    
    assert channel._divoom_instance == mock_divoom_instance
    assert channel._opts["type"] == VJEffectType.Sparkles

@pytest.mark.asyncio
async def test_vjeffect_channel_init_custom_opts(mock_divoom_instance):
    """Test VJEffectChannel initialization with custom options."""
    custom_opts = {
        "type": VJEffectType.Lava
    }
    channel = VJEffectChannel(mock_divoom_instance, opts=custom_opts)
    
    assert channel._opts["type"] == VJEffectType.Lava

@pytest.mark.asyncio
async def test_vjeffect_channel_show(mock_divoom_instance):
    """Test the show method calls _update_message."""
    channel = VJEffectChannel(mock_divoom_instance)

    await channel.show()
    mock_divoom_instance.send_command.assert_called_once()

@pytest.mark.asyncio
async def test_vjeffect_channel_update_message(mock_divoom_instance):
    """Test _update_message sends the correct command with converted arguments."""
    channel = VJEffectChannel(mock_divoom_instance, opts={"type": VJEffectType.RainbowSwirl})

    await channel._update_message()

    # _PACKAGE_PREFIX = "4503" -> command_code = 0x45, first arg = 0x03
    # type = VJEffectType.RainbowSwirl (4) -> "04"
    # Combined hex string: "0304"
    # List of bytes: [0x03, 0x04]
    expected_args = [0x03, 0x04]
    # Asserting the real encoded bytes (produced by the real number2HexString)
    # is the teeth: revert the channel to self._divoom_instance.number2HexString
    # and this call raises AttributeError instead of reaching send_command.
    mock_divoom_instance.send_command.assert_called_once_with(0x45, expected_args)

@pytest.mark.asyncio
async def test_vjeffect_channel_type_setter(mock_divoom_instance):
    """Test the type setter updates option."""
    channel = VJEffectChannel(mock_divoom_instance)

    channel.type = VJEffectType.Fire
    assert channel._opts["type"] == VJEffectType.Fire
