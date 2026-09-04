import pytest
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.display.lightning_channel import LightningChannel
from divoom_lib.divoom import Divoom as DivoomBase
from divoom_lib.models import LightningType

@pytest.fixture
def mock_divoom_instance():
    """Fixture for a mock DivoomBase instance.

    R53.43: previously this monkeypatched ``color2HexString`` /
    ``number2HexString`` / ``boolean2HexString`` onto the mock, which MASKED a
    real bug — LightningChannel called them as
    ``self._divoom_instance.<helper>`` but they are module-level helpers in
    ``utils.converters``, not methods on Divoom. The test passed falsely. The
    channel now imports the real converters, so the mock must NOT provide them
    (re-adding any would re-mask the AttributeError regression). Note the real
    ``color2HexString`` only accepts a clean 6-digit hex string (no ``#``),
    unlike the old mock which stripped the ``#``.
    """
    mock = AsyncMock(spec=DivoomBase)
    mock.send_command = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_lightning_channel_init_defaults(mock_divoom_instance):
    """Test LightningChannel initialization with default options."""
    channel = LightningChannel(mock_divoom_instance)
    
    assert channel._divoom_instance == mock_divoom_instance
    assert channel._opts["type"] == LightningType.PlainColor
    assert channel._opts["brightness"] == 100
    assert channel._opts["power"] is True
    assert channel._opts["color"] == "FFFFFF"

@pytest.mark.asyncio
async def test_lightning_channel_init_custom_opts(mock_divoom_instance):
    """Test LightningChannel initialization with custom options."""
    custom_opts = {
        "type": LightningType.Love,
        "brightness": 50,
        "power": False,
        "color": "00FF00"
    }
    channel = LightningChannel(mock_divoom_instance, opts=custom_opts)
    
    assert channel._opts["type"] == LightningType.Love
    assert channel._opts["brightness"] == 50
    assert channel._opts["power"] is False
    assert channel._opts["color"] == "00FF00"

@pytest.mark.asyncio
async def test_lightning_channel_show(mock_divoom_instance):
    """Test the show method calls _update_message."""
    channel = LightningChannel(mock_divoom_instance)

    await channel.show()
    mock_divoom_instance.send_command.assert_called_once()

@pytest.mark.asyncio
async def test_lightning_channel_update_message(mock_divoom_instance):
    """Test _update_message sends the correct command with converted arguments."""
    channel = LightningChannel(mock_divoom_instance, opts={"color": "FF0000", "brightness": 75, "type": LightningType.Plants, "power": True})

    await channel._update_message()

    # Expected arguments based on _PACKAGE_PREFIX, color, brightness, type, power, _PACKAGE_SUFFIX
    # _PACKAGE_PREFIX = "4501" -> command_code = 0x45, first arg = 0x01
    # color = "FF0000" -> real color2HexString -> "FF0000"
    # brightness = 75 -> real number2HexString -> "4b"
    # type = LightningType.Plants (2) -> real number2HexString -> "02"
    # power = True -> real boolean2HexString -> "01"
    # _PACKAGE_SUFFIX = "000000"
    # Combined hex string: "01FF00004b0201000000"
    # List of bytes: [0x01, 0xFF, 0x00, 0x00, 0x4B, 0x02, 0x01, 0x00, 0x00, 0x00]
    # Asserting the real encoded bytes is the teeth: revert any call site to
    # self._divoom_instance.<helper> and this raises AttributeError.
    expected_args = [0x01, 0xFF, 0x00, 0x00, 0x4B, 0x02, 0x01, 0x00, 0x00, 0x00]
    mock_divoom_instance.send_command.assert_called_once_with(0x45, expected_args)

@pytest.mark.asyncio
async def test_lightning_channel_type_setter(mock_divoom_instance):
    """Test the type setter updates option."""
    channel = LightningChannel(mock_divoom_instance)

    channel.type = LightningType.Sleeping
    assert channel._opts["type"] == LightningType.Sleeping

@pytest.mark.asyncio
async def test_lightning_channel_color_setter(mock_divoom_instance):
    """Test the color setter updates option."""
    channel = LightningChannel(mock_divoom_instance)

    channel.color = "0000FF"
    assert channel._opts["color"] == "0000FF"

@pytest.mark.asyncio
async def test_lightning_channel_power_setter(mock_divoom_instance):
    """Test the power setter updates option."""
    channel = LightningChannel(mock_divoom_instance)

    channel.power = False
    assert channel._opts["power"] is False

@pytest.mark.asyncio
async def test_lightning_channel_brightness_setter(mock_divoom_instance):
    """Test the brightness setter updates option."""
    channel = LightningChannel(mock_divoom_instance)

    channel.brightness = 25
    assert channel._opts["brightness"] == 25
