# divoom_api/drawing/text.py — migrated to display/display_text.py
from ..sender_protocol import CommandSender
# number2HexString / color2HexString are module-level helpers in
# utils.converters, NOT methods on Divoom — calling them via
# self._divoom_instance.<helper> raised AttributeError at runtime
# (R53.43, same bug the weather/date_time shims already document/fixed).
from ..utils.converters import number2HexString, color2HexString
from typing import Optional, Dict, Any, List, Callable
import asyncio
import math

class DisplayText:
    """
    This class is used to display text on the Divoom Timebox Evo.
    """
    _PACKAGE_INIT_MESSAGE = "6e01"
    _PALETTE_HEADER = "6c00000704aa070446000000"

    def __init__(self, divoom_instance: CommandSender, opts: Optional[Dict[str, Any]] = None):
        self._divoom_instance = divoom_instance
        self._anim_frame = 0
        self._opts = {
            "text": "node-divoom-timebox-evo",
            "paletteFn": self.PALETTE_TEXT_ON_BACKGROUND,
            "animFn": self.ANIM_STATIC_BACKGROUND
        }
        if opts:
            self._opts.update(opts)

    async def update_display(self):
        await self._update_message()

    def PALETTE_TEXT_ON_BACKGROUND(self, text_color: str = "FFFFFF", background_color: str = "000000") -> List[str]:
        back = color2HexString(background_color)
        front = color2HexString(text_color)
        palette = [back] * 256
        for i in range(127, 256):
            palette[i] = front
        return palette

    def PALETTE_BLACK_ON_CMY_RAINBOW(self) -> List[str]:
        palette: List[str] = []
        r, g, b = 255, 0, 255
        for i in range(0, 254, 2):
            palette.append(
                number2HexString(r) +
                number2HexString(g) +
                number2HexString(b)
            )
            if i < 85:
                b = max(0, b - 6)
                g = min(255, g + 6)
            elif i < 170:
                b = min(255, b + 6)
                r = max(0, r - 6)
            else:
                r = min(255, r + 6)
                g = max(0, g - 6)
        for i in range(len(palette), 256):
            palette.append("000000")
        return palette

    def PALETTE_BLACK_ON_RAINBOW(self) -> List[str]:
        palette: List[str] = []
        size = 127

        def sin_to_hex(i: int, phase: float) -> str:
            sin_val = math.sin(math.pi / size * 2 * i + phase)
            int_val = math.floor(sin_val * 127) + 128
            return number2HexString(int_val)

        for i in range(size):
            red = sin_to_hex(i, 0 * math.pi * 2 / 3)
            blue = sin_to_hex(i, 1 * math.pi * 2 / 3)
            green = sin_to_hex(i, 2 * math.pi * 2 / 3)
            palette.append(red + green + blue)

        for i in range(len(palette), 256):
            palette.append("000000")
        return palette

    def ANIM_STATIC_BACKGROUND(self, frame: Optional[int] = None) -> List[int]:
        return [0] * 256

    def ANIM_UNI_GRADIANT_BACKGROUND(self, frame: int) -> List[int]:
        return [frame % 127] * 256

    def ANIM_HORIZONTAL_GRADIANT_BACKGROUND(self, frame: int) -> List[int]:
        pixel_array = []
        for y in range(16):
            for x in range(16):
                pixel_array.append((x + frame) % 127)
        return pixel_array

    def ANIM_VERTICAL_GRADIANT_BACKGROUND(self, frame: int) -> List[int]:
        pixel_array = []
        for y in range(16):
            for x in range(16):
                pixel_array.append((y + frame) % 127)
        return pixel_array

    def _encode_text(self, text: str) -> List[int]:
        encoded_bytes = [0x86, 0x01]
        encoded_bytes.append(len(text))
        for char in text:
            hex_str = self._divoom_instance._int2hexlittle(ord(char))
            encoded_bytes.extend([int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)])
        return encoded_bytes

    async def _update_message(self):
        if not callable(self._opts["animFn"]) or not callable(self._opts["paletteFn"]):
            raise ValueError('paletteFn and animFn need to be functions')

        self._anim_frame = 0

        command_code_init = int(self._PACKAGE_INIT_MESSAGE[0:2], 16)
        args_init = [int(self._PACKAGE_INIT_MESSAGE[2:], 16)]
        await self._divoom_instance.send_command(command_code_init, args_init)

        encoded_text_bytes = self._encode_text(self._opts["text"])
        await self._divoom_instance.send_command(encoded_text_bytes[0], encoded_text_bytes[1:])

        palette_hex_list = self.color_palette
        pixels = self._opts["animFn"](self._anim_frame)
        if len(pixels) != 256:
            raise ValueError('The animFn should always generate a 256 pixel array')

        pixels_hex_string = "".join([number2HexString(p) for p in pixels])

        command_code_palette = int(self._PALETTE_HEADER[0:2], 16)
        args_hex_string_palette = self._PALETTE_HEADER[2:] + "".join(palette_hex_list) + pixels_hex_string
        args_palette = [int(args_hex_string_palette[i:i+2], 16) for i in range(0, len(args_hex_string_palette), 2)]
        await self._divoom_instance.send_command(command_code_palette, args_palette)

        await self.get_next_animation_frame()

    async def get_next_animation_frame(self):
        pixel_array: List[int] = self._opts["animFn"](self._anim_frame)
        if len(pixel_array) != 256:
            raise ValueError('The animFn should always generate a 256 pixel array')

        pixel_string = ""
        for pixel in pixel_array:
            pixel_string += number2HexString(pixel)

        command_code_anim = 0x6c
        anim_frame_hex = self._divoom_instance._int2hexlittle(self._anim_frame)
        args_hex_string_anim = anim_frame_hex + "0701aa070143000100" + pixel_string
        args_anim = [int(args_hex_string_anim[i:i+2], 16) for i in range(0, len(args_hex_string_anim), 2)]

        await self._divoom_instance.send_command(command_code_anim, args_anim)
        self._anim_frame = (self._anim_frame + 1) % 65536

    @property
    def palette_fn(self) -> Callable:
        return self._opts["paletteFn"]

    @palette_fn.setter
    def palette_fn(self, value: Callable):
        if not callable(value):
            raise ValueError('paletteFn is not a function')
        self._opts["paletteFn"] = value

    @property
    def color_palette(self) -> List[str]:
        palette = self.palette_fn()
        if len(palette) != 256:
            raise ValueError('The paletteFn should always generate 256 colors')
        result: List[str] = []
        for color in palette:
            result.append(color2HexString(color))
        return result

    @property
    def anim_fn(self) -> Callable:
        return self._opts["animFn"]

    @anim_fn.setter
    def anim_fn(self, value: Callable):
        if not callable(value):
            raise ValueError('animFn is not a function')
        self._opts["animFn"] = value

    @property
    def pixels(self) -> List[int]:
        return self.anim_fn(self._anim_frame)

    @property
    def frame(self) -> int:
        return self._anim_frame

    @property
    def text(self) -> str:
        return self._opts["text"]

    @text.setter
    def text(self, value: str):
        self._opts["text"] = value
