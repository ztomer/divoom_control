# divoom_api/utils/converters.py
import logging

logger = logging.getLogger(__name__)

def bool_to_byte(value: bool | int) -> int:
    """Converts a boolean or 0/1 integer to 0x01 or 0x00."""
    if value is True or value == 1:
        return 0x01
    return 0x00

def to_int_if_str(value: str | int) -> int:
    """Converts a value to an integer if it's a string."""
    if isinstance(value, str):
        return int(value)
    return value

def color_to_rgb_list(color_input) -> list:
    """
    Converts a color input (e.g., "RRGGBB" or "#RRGGBB" hex string, named color, or (R, G, B) tuple/list)
    to a list of three integers [R, G, B].
    """
    if isinstance(color_input, str):
        color_str = color_input.strip()
        if color_str.startswith('#'):
            color_str = color_str[1:]
        
        named_colors = {
            "red": [255, 0, 0],
            "green": [0, 255, 0],
            "blue": [0, 0, 255],
            "white": [255, 255, 255],
            "black": [0, 0, 0],
            "yellow": [255, 255, 0],
            "cyan": [0, 255, 255],
            "magenta": [255, 0, 255],
        }
        if color_str.lower() in named_colors:
            return named_colors[color_str.lower()]
            
        if len(color_str) == 6 and all(c in '0123456789abcdefABCDEF' for c in color_str):
            r = int(color_str[0:2], 16)
            g = int(color_str[2:4], 16)
            b = int(color_str[4:6], 16)
            return [r, g, b]
    elif isinstance(color_input, (tuple, list)) and len(color_input) == 3:
        if all(0 <= c <= 255 for c in color_input):
            return list(color_input)
            
    logger.warning(f"Unsupported color input format: {color_input}. Defaulting to [255, 255, 255].")
    return [255, 255, 255]

def color2HexString(color_input) -> str:
    """
    Converts a color input (e.g., "RRGGBB", hex, or named color) to an
    hexadecimal string representation (RRGGBB).
    This function would typically use a color parsing library if more complex
    inputs are expected. For now, it assumes a valid hex string input.
    """
    # For simplicity, assuming color_input is already a 6-digit hex string "RRGGBB"
    # or can be directly converted. If more robust parsing is needed (e.g., named colors,
    # RGB tuples), a library like 'webcolors' or custom logic would be integrated.
    if isinstance(color_input, str) and len(color_input) == 6 and all(c in '0123456789abcdefABCDEF' for c in color_input):
        return color_input
    elif isinstance(color_input, tuple) and len(color_input) == 3: # (R, G, B) tuple
        return f"{color_input[0]:02x}{color_input[1]:02x}{color_input[2]:02x}"
    # Add more robust color parsing here if necessary
    logger.warning(f"Unsupported color input format: {color_input}. Defaulting to 'FFFFFF'.")
    return "FFFFFF"

def number2HexString(byte_value: int) -> str:
    """
    Converts an integer (0-255) to its two-character hexadecimal string representation.
    """
    if not 0 <= byte_value <= 255:
        raise ValueError("number2HexString works only with numbers between 0 and 255")
    return f"{int(byte_value):02x}"

def boolean2HexString(boolean_value: bool) -> str:
    """
    Convert a boolean to "01" (true) or "00" (false) hexadecimal string.
    """
    return "01" if boolean_value else "00"

def parse_frequency(frequency: int | None) -> list[int]:
    """
    Parses a frequency value into a 2-byte list (little-endian).
    If frequency is None, returns [0x00, 0x00].
    """
    if frequency is None:
        return [0x00, 0x00]
    if not isinstance(frequency, int):
        logger.warning(f"Invalid frequency type: {type(frequency)}. Expected int. Defaulting to 0.")
        frequency = 0
    return list(frequency.to_bytes(2, byteorder='little'))