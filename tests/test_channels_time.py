import pytest
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.display.time_channel import TimeChannel
from divoom_lib.divoom import Divoom as DivoomBase
from divoom_lib.models import TimeDisplayType

@pytest.fixture
def mock_divoom_instance():
    """Fixture for a mock DivoomBase instance.

    R53.43: previously this monkeypatched ``color2HexString`` onto the mock,
    which MASKED a real bug — TimeChannel called it as
    ``self._divoom_instance.color2HexString`` but it is a module-level helper
    in ``utils.converters``, not a method on Divoom. The test passed falsely.
    The channel now imports the real converter, so the mock must NOT provide it
    (re-adding it would re-mask the AttributeError regression). Note the real
    ``color2HexString`` only accepts a clean 6-digit hex string (no ``#``),
    unlike the old mock which stripped the ``#``.
    """
    mock = AsyncMock(spec=DivoomBase)
    mock.send_command = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_time_channel_init_defaults(mock_divoom_instance):
    """Test TimeChannel initialization with default options."""
    channel = TimeChannel(mock_divoom_instance)
    
    assert channel._divoom_instance == mock_divoom_instance
    assert channel._opts["type"] == TimeDisplayType.FullScreen
    assert channel._opts["showTime"] is True
    assert channel._opts["showWeather"] is False
    assert channel._opts["showTemp"] is False
    assert channel._opts["showCalendar"] is False
    assert channel._opts["color"] == "FFFFFF"

@pytest.mark.asyncio
async def test_time_channel_init_custom_opts(mock_divoom_instance):
    """Test TimeChannel initialization with custom options."""
    custom_opts = {
        "type": TimeDisplayType.Rainbow,
        "showTime": False,
        "showWeather": True,
        "showTemp": True,
        "showCalendar": True,
        "color": "00FF00"
    }
    channel = TimeChannel(mock_divoom_instance, opts=custom_opts)
    
    assert channel._opts["type"] == TimeDisplayType.Rainbow
    assert channel._opts["showTime"] is False
    assert channel._opts["showWeather"] is True
    assert channel._opts["showTemp"] is True
    assert channel._opts["showCalendar"] is True
    assert channel._opts["color"] == "00FF00"

@pytest.mark.asyncio
async def test_time_channel_show(mock_divoom_instance):
    """Test the show method calls _update_message."""
    channel = TimeChannel(mock_divoom_instance)

    await channel.show()
    mock_divoom_instance.send_command.assert_called_once()

@pytest.mark.asyncio
async def test_time_channel_update_message(mock_divoom_instance):
    """Test _update_message sends the correct command with converted arguments."""
    channel = TimeChannel(mock_divoom_instance, opts={
        "type": TimeDisplayType.WithBox,
        "showTime": True,
        "showWeather": False,
        "showTemp": True,
        "showCalendar": False,
        "color": "FF00FF"
    })

    await channel._update_message()

    # _PACKAGE_PREFIX = "450001" -> command_code = 0x45, first two args = 0x00, 0x01
    # type = TimeDisplayType.WithBox (2)
    # showTime = True -> 1
    # showWeather = False -> 0
    # showTemp = True -> 1
    # showCalendar = False -> 0
    # color = "FF00FF" -> real color2HexString -> "FF00FF" -> bytes [0xFF, 0x00, 0xFF]
    # Expected args: [0x00, 0x01, 0x02, 0x01, 0x00, 0x01, 0x00, 0xFF, 0x00, 0xFF]
    # Asserting the real encoded bytes is the teeth: revert the channel to
    # self._divoom_instance.color2HexString and this raises AttributeError.
    expected_args = [0x00, 0x01, TimeDisplayType.WithBox, 1, 0, 1, 0, 0xFF, 0x00, 0xFF]
    mock_divoom_instance.send_command.assert_called_once_with(0x45, expected_args)

@pytest.mark.asyncio
async def test_time_channel_type_setter(mock_divoom_instance):
    """Test the type setter updates option."""
    channel = TimeChannel(mock_divoom_instance)

    channel.type = TimeDisplayType.AnalogRound
    assert channel._opts["type"] == TimeDisplayType.AnalogRound

@pytest.mark.asyncio
async def test_time_channel_color_setter(mock_divoom_instance):
    """Test the color setter updates option."""
    channel = TimeChannel(mock_divoom_instance)

    channel.color = "000000"
    assert channel._opts["color"] == "000000"

@pytest.mark.asyncio
async def test_time_channel_show_time_setter(mock_divoom_instance):
    """Test the show_time setter updates option."""
    channel = TimeChannel(mock_divoom_instance)

    channel.show_time = False
    assert channel._opts["showTime"] is False

@pytest.mark.asyncio
async def test_time_channel_show_weather_setter(mock_divoom_instance):
    """Test the show_weather setter updates option."""
    channel = TimeChannel(mock_divoom_instance)

    channel.show_weather = True
    assert channel._opts["showWeather"] is True

@pytest.mark.asyncio
async def test_time_channel_show_temp_setter(mock_divoom_instance):
    """Test the show_temp setter updates option."""
    channel = TimeChannel(mock_divoom_instance)

    channel.show_temp = True
    assert channel._opts["showTemp"] is True

@pytest.mark.asyncio
async def test_time_channel_show_calendar_setter(mock_divoom_instance):
    """Test the show_calendar setter updates option."""
    channel = TimeChannel(mock_divoom_instance)

    channel.show_calendar = True
    assert channel._opts["showCalendar"] is True
