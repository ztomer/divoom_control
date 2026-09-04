import pytest
from divoom_lib import models as constants

def test_commands_dictionary_integrity():
    """Test that the COMMANDS dictionary contains expected keys and integer values."""
    assert isinstance(constants.COMMANDS, dict)
    assert "set volume" in constants.COMMANDS
    assert constants.COMMANDS["set volume"] == 0x08
    assert "set light mode" in constants.COMMANDS
    assert constants.COMMANDS["set light mode"] == 0x45
    assert "get device name" in constants.COMMANDS
    assert constants.COMMANDS["get device name"] == 0x76
    # Add more critical commands to check

def test_payload_values():
    """Test specific payload constant values."""
    assert constants.PAYLOAD_START_BYTE_COLOR_MODE == 0x01
    assert constants.CHANNEL_ID_2 == 0x02
    assert constants.WORK_MODE_CHANNEL_9 == 0x09

def test_general_constants():
    """Test general utility constants."""
    assert constants.BOOLEAN_TRUE == 0x01
    assert constants.BOOLEAN_FALSE == 0x00
    assert constants.FIXED_STRING_BYTE == 0x00

def test_generic_ack_commands_list():
    """Test the GENERIC_ACK_COMMANDS list contains expected command IDs."""
    assert isinstance(constants.GENERIC_ACK_COMMANDS, list)
    assert constants.COMMANDS["set light mode"] in constants.GENERIC_ACK_COMMANDS
    assert constants.COMMANDS["set work mode"] in constants.GENERIC_ACK_COMMANDS

def test_ios_le_protocol_constants():
    """Test constants related to the iOS LE protocol."""
    assert constants.IOS_LE_MIN_DATA_LENGTH == 11
    assert constants.IOS_LE_HEADER == [0xFE, 0xEF, 0xAA, 0x55]
    assert constants.IOS_LE_COMMAND_IDENTIFIER == 7

def test_basic_protocol_constants():
    """Test constants related to the Basic Protocol."""
    assert constants.MESSAGE_START_BYTE == 0x01
    assert constants.MESSAGE_END_BYTE == 0x02
    assert constants.MESSAGE_CHECKSUM_LENGTH == 2

def test_escape_sequences():
    """Test escape byte and sequence constants."""
    assert constants.ESCAPE_BYTE_1 == 0x01
    assert constants.ESCAPE_SEQUENCE_1 == [0x03, 0x04]
    assert constants.ESCAPE_BYTE_2 == 0x02
    assert constants.ESCAPE_SEQUENCE_2 == [0x03, 0x05]
    assert constants.ESCAPE_BYTE_3 == 0x03
    assert constants.ESCAPE_SEQUENCE_3 == [0x03, 0x06]

def test_tool_constants():
    """Test tool-related constants."""
    assert constants.TOOL_TYPE_TIMER == 0
    assert constants.TOOL_TYPE_SCORE == 1
    assert constants.TOOL_TYPE_NOISE == 2
    assert constants.TOOL_TYPE_COUNTDOWN == 3

def test_system_channel_ids():
    """Test system channel ID constants."""
    assert constants.CHANNEL_ID_TIME == 0x00
    assert constants.CHANNEL_ID_LIGHTNING == 0x01
    assert constants.CHANNEL_ID_CLOUD == 0x02
    assert constants.CHANNEL_ID_VJ_EFFECTS == 0x03
    assert constants.CHANNEL_ID_VISUALIZATION == 0x04
    assert constants.CHANNEL_ID_ANIMATION == 0x05
    assert constants.CHANNEL_ID_SCOREBOARD == 0x06
    assert constants.CHANNEL_ID_MIN == 0x00
    assert constants.CHANNEL_ID_MAX == 0x06

def test_timebox_const_classes():
    """Test the nested classes within TIMEBOX_CONST."""
    assert constants.TIMEBOX_CONST["TimeType"].FullScreen == 0
    assert constants.TIMEBOX_CONST["LightningType"].PlainColor == 0
    assert constants.TIMEBOX_CONST["WeatherType"].Clear == 1
    assert constants.TIMEBOX_CONST["VJEffectType"].Sparkles == 0
