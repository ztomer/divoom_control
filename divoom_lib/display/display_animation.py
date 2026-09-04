# divoom_api/drawing/drawing.py — migrated to display/display_animation.py
from ..sender_protocol import CommandSender
# number2HexString is a module-level helper in utils.converters, NOT a method
# on Divoom — calling it via self._divoom_instance.number2HexString raised
# AttributeError at runtime (R53.43). _int2hexlittle below IS a real Divoom
# method, so it stays on self._divoom_instance.
from ..utils.converters import number2HexString
from typing import Optional, Dict, Any, List, Union
import asyncio
import math
from PIL import Image, ImageSequence
import io

class DisplayAnimation:
    """
    This class is used to display static images and animations on the Divoom Timebox Evo.
    """
    def __init__(self, divoom_instance: CommandSender):
        self._divoom_instance = divoom_instance

    async def read(self, input_data: Union[str, bytes]) -> List[List[int]]:
        """
        Reads an image and returns a list of Divoom-formatted frames.
        It works with GIF, JPEG, PNG, and BMP.
        """
        if isinstance(input_data, str):
            with open(input_data, 'rb') as f:
                buffer = f.read()
        elif isinstance(input_data, bytes):
            buffer = input_data
        else:
            raise ValueError("Input must be a file path (str) or bytes.")

        image = Image.open(io.BytesIO(buffer))

        if hasattr(image, 'is_animated') and image.is_animated:
            return await self._display_animation_from_gif(image)
        else:
            return await self._display_image(image)

    async def _display_image(self, image: Image.Image) -> List[List[int]]:
        resized_image = image.resize((16, 16), Image.NEAREST)
        return [self._encode_image_data(resized_image, is_animated=False)]

    async def _display_animation_from_gif(self, image: Image.Image) -> List[List[int]]:
        frames_data = []
        for i, frame in enumerate(ImageSequence.Iterator(image)):
            resized_frame = frame.resize((16, 16), Image.NEAREST)
            duration = frame.info.get('duration', 100)
            frames_data.append(self._encode_image_data(resized_frame, is_animated=True, frame_delay=duration, frame_index=i))
        return frames_data

    def _encode_image_data(self, image: Image.Image, is_animated: bool, frame_delay: int = 0, frame_index: int = 0) -> List[int]:
        image = image.convert("RGB")

        colors_array = []
        pixel_indices = []
        color_to_index = {}

        for y in range(image.height):
            for x in range(image.width):
                r, g, b = image.getpixel((x, y))
                color_hex = f"{r:02x}{g:02x}{b:02x}"

                if color_hex not in color_to_index:
                    color_to_index[color_hex] = len(colors_array)
                    colors_array.append(color_hex)
                pixel_indices.append(color_to_index[color_hex])

        nb_colors = len(colors_array)
        if nb_colors > 256:
            raise ValueError(f"Too many colors ({nb_colors}) in image. Max 256 supported.")

        if nb_colors <= 1:
            bits_per_pixel = 1
        else:
            bits_per_pixel = math.ceil(math.log2(nb_colors))

        pixel_binary_string = ""
        for pixel_idx in pixel_indices:
            pixel_binary_string += bin(pixel_idx)[2:].zfill(bits_per_pixel)

        while len(pixel_binary_string) % 8 != 0:
            pixel_binary_string += "0"

        pixel_hex_string = ""
        for i in range(0, len(pixel_binary_string), 8):
            byte_str = pixel_binary_string[i:i+8]
            pixel_hex_string += f"{int(byte_str, 2):02x}"

        if is_animated:
            delay_hex = self._divoom_instance._int2hexlittle(frame_delay)
            reset_palette = "00"
            nb_colors_hex = number2HexString(nb_colors)
            color_string = "".join(colors_array)

            string_without_header = delay_hex + reset_palette + nb_colors_hex + color_string + pixel_hex_string
            size_value = (len(string_without_header) // 2) + 6
            size_hex = self._divoom_instance._int2hexlittle(size_value)

            full_payload_hex = "aa" + size_hex + string_without_header

            return [int(full_payload_hex[i:i+2], 16) for i in range(0, len(full_payload_hex), 2)]

        else:
            nb_colors_hex = number2HexString(nb_colors)
            color_string = "".join(colors_array)

            string_without_header = nb_colors_hex + color_string + pixel_hex_string
            size_value = (len(string_without_header) // 2) + 6
            size_hex = self._divoom_instance._int2hexlittle(size_value)

            full_payload_hex = "aa" + size_hex + "000000" + string_without_header

            return [int(full_payload_hex[i:i+2], 16) for i in range(0, len(full_payload_hex), 2)]
