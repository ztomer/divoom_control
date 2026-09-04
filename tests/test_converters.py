import pytest
import logging
from divoom_lib.utils import converters

# Suppress logging output during tests for cleaner output
@pytest.fixture(autouse=True)
def no_logging(caplog):
    caplog.set_level(logging.CRITICAL)

def test_bool_to_byte():
    """Test bool_to_byte function."""
    assert converters.bool_to_byte(True) == 0x01
    assert converters.bool_to_byte(False) == 0x00
    assert converters.bool_to_byte(1) == 0x01
    assert converters.bool_to_byte(0) == 0x00
    assert converters.bool_to_byte(99) == 0x00 # Any non-1 truthy value should be 0x00
    assert converters.bool_to_byte("true") == 0x00 # Non-boolean/non-0/1 int should be 0x00

def test_to_int_if_str():
    """Test to_int_if_str function."""
    assert converters.to_int_if_str("123") == 123
    assert converters.to_int_if_str(456) == 456
    assert converters.to_int_if_str("-789") == -789
    with pytest.raises(ValueError):
        converters.to_int_if_str("abc")

def test_color_to_rgb_list_hex_string():
    """Test color_to_rgb_list with RRGGBB hex string."""
    assert converters.color_to_rgb_list("FF0000") == [255, 0, 0]
    assert converters.color_to_rgb_list("00FF00") == [0, 255, 0]
    assert converters.color_to_rgb_list("0000FF") == [0, 0, 255]
    assert converters.color_to_rgb_list("ffffff") == [255, 255, 255]
    assert converters.color_to_rgb_list("010203") == [1, 2, 3]

def test_color_to_rgb_list_rgb_tuple():
    """Test color_to_rgb_list with (R, G, B) tuple."""
    assert converters.color_to_rgb_list((255, 0, 0)) == [255, 0, 0]
    assert converters.color_to_rgb_list((0, 128, 255)) == [0, 128, 255]

def test_color_to_rgb_list_rgb_list():
    """Test color_to_rgb_list with [R, G, B] list."""
    assert converters.color_to_rgb_list([255, 0, 0]) == [255, 0, 0]
    assert converters.color_to_rgb_list([0, 128, 255]) == [0, 128, 255]

def test_color_to_rgb_list_out_of_range_rgb(caplog):
    """Test color_to_rgb_list with out-of-range RGB values."""
    with caplog.at_level(logging.WARNING):
        assert converters.color_to_rgb_list((256, 0, 0)) == [255, 255, 255]
        assert "Unsupported color input format: (256, 0, 0)" in caplog.text
        caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert converters.color_to_rgb_list([-1, 0, 0]) == [255, 255, 255]
        assert "Unsupported color input format: [-1, 0, 0]" in caplog.text

def test_color_to_rgb_list_invalid_input(caplog):
    """Test color_to_rgb_list with invalid input formats."""
    with caplog.at_level(logging.WARNING):
        assert converters.color_to_rgb_list("invalid") == [255, 255, 255]
        assert "Unsupported color input format" in caplog.text
        caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert converters.color_to_rgb_list(123456) == [255, 255, 255]
        assert "Unsupported color input format" in caplog.text
        caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert converters.color_to_rgb_list((255, 0)) == [255, 255, 255] # Wrong tuple length
        assert "Unsupported color input format" in caplog.text

def test_color2HexString_hex_string():
    """Test color2HexString with RRGGBB hex string."""
    assert converters.color2HexString("FF0000") == "FF0000"
    assert converters.color2HexString("00ff00") == "00ff00"

def test_color2HexString_rgb_tuple():
    """Test color2HexString with (R, G, B) tuple."""
    assert converters.color2HexString((255, 0, 0)) == "ff0000"
    assert converters.color2HexString((0, 128, 255)) == "0080ff"

def test_color2HexString_invalid_input(caplog):
    """Test color2HexString with invalid input formats."""
    with caplog.at_level(logging.WARNING):
        assert converters.color2HexString("red") == "FFFFFF"
        assert "Unsupported color input format" in caplog.text
        caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert converters.color2HexString(123456) == "FFFFFF"
        assert "Unsupported color input format" in caplog.text

def test_number2HexString():
    """Test number2HexString function."""
    assert converters.number2HexString(0) == "00"
    assert converters.number2HexString(10) == "0a"
    assert converters.number2HexString(255) == "ff"
    assert converters.number2HexString(16) == "10"
    with pytest.raises(ValueError, match="number2HexString works only with numbers between 0 and 255"):
        converters.number2HexString(-1)
    with pytest.raises(ValueError, match="number2HexString works only with numbers between 0 and 255"):
        converters.number2HexString(256)

def test_boolean2HexString():
    """Test boolean2HexString function."""
    assert converters.boolean2HexString(True) == "01"
    assert converters.boolean2HexString(False) == "00"

def test_parse_frequency_valid_int():
    """Test parse_frequency with valid integer input."""
    assert converters.parse_frequency(0) == [0x00, 0x00]
    assert converters.parse_frequency(1) == [0x01, 0x00]
    assert converters.parse_frequency(255) == [0xFF, 0x00]
    assert converters.parse_frequency(256) == [0x00, 0x01] # Little-endian
    assert converters.parse_frequency(512) == [0x00, 0x02]
    assert converters.parse_frequency(65535) == [0xFF, 0xFF] # Max 2-byte value

def test_parse_frequency_none():
    """Test parse_frequency with None input."""
    assert converters.parse_frequency(None) == [0x00, 0x00]

def test_parse_frequency_invalid_type(caplog):
    """Test parse_frequency with invalid type input."""
    with caplog.at_level(logging.WARNING):
        assert converters.parse_frequency("abc") == [0x00, 0x00]
        assert "Invalid frequency type: <class 'str'>. Expected int. Defaulting to 0." in caplog.text
        caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert converters.parse_frequency(1.5) == [0x00, 0x00]
        assert "Invalid frequency type: <class 'float'>. Expected int. Defaulting to 0." in caplog.text
