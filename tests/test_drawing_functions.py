
import asyncio
import logging
import unittest
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image, ImageDraw
import io

from divoom_lib.display.display_animation import DisplayAnimation
from divoom_lib.divoom import Divoom as DivoomBase # Import DivoomBase for type hinting and mocking
from divoom_lib import models as constants

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_drawing_functions")

class TestDrawingFunctions(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up a mock Divoom instance for testing."""
        self.mock_divoom_instance = AsyncMock(spec=DivoomBase)
        self.mock_divoom_instance.logger = logger
        # _int2hexlittle IS a real Divoom method, so it's legitimately mocked here.
        self.mock_divoom_instance._int2hexlittle = MagicMock(side_effect=lambda x: f"{x & 0xFF:02x}{((x >> 8) & 0xFF):02x}")
        # R53.43: number2HexString is NOT a method on Divoom — it is a module-level
        # helper in utils.converters. Monkeypatching it onto the mock previously
        # MASKED the AttributeError bug. DisplayAnimation now imports the real
        # converter, so the mock must NOT provide it (re-adding it would re-mask
        # the regression). The _encode_image_data byte assertions below
        # (nb_colors byte == encoded_data[6]) exercise the real converter.

        self.display_animation = DisplayAnimation(self.mock_divoom_instance)

    def create_test_image(self, size=(16, 16), color=(255, 0, 0)) -> Image.Image:
        """Creates a simple static PIL Image for testing."""
        img = Image.new('RGB', size, color)
        return img

    def create_test_gif(self, size=(16, 16), num_frames=2) -> bytes:
        """Creates a simple animated GIF (bytes) for testing."""
        frames = []
        for i in range(num_frames):
            color = (255 if i % 2 == 0 else 0, 0, 255 if i % 2 != 0 else 0)
            img = Image.new('RGB', size, color)
            frames.append(img)
        
        gif_bytes = io.BytesIO()
        frames[0].save(gif_bytes, format='GIF', append_images=frames[1:], save_all=True, duration=100, loop=0)
        return gif_bytes.getvalue()

    async def test_read_static_image_file(self):
        """Test reading a static image from a file path."""
        logger.info("--- Running test_read_static_image_file ---")
        img = self.create_test_image()
        
        # Save to a temporary file
        temp_file_path = "temp_static_image.png"
        img.save(temp_file_path)

        try:
            frames_data = await self.display_animation.read(temp_file_path)
            self.assertIsInstance(frames_data, list)
            self.assertEqual(len(frames_data), 1) # Static image should produce one frame
            self.assertIsInstance(frames_data[0], list) # Frame data should be a list of bytes
            # Further assertions can be made on the content of frames_data[0] if the encoding is stable
            # For now, just check that it's not empty and has a reasonable length
            self.assertGreater(len(frames_data[0]), 0)
        finally:
            os.remove(temp_file_path)

    async def test_read_static_image_bytes(self):
        """Test reading a static image from bytes."""
        logger.info("--- Running test_read_static_image_bytes ---")
        img = self.create_test_image()
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes_value = img_bytes.getvalue()

        frames_data = await self.display_animation.read(img_bytes_value)
        self.assertIsInstance(frames_data, list)
        self.assertEqual(len(frames_data), 1)
        self.assertIsInstance(frames_data[0], list)
        self.assertGreater(len(frames_data[0]), 0)

    async def test_read_gif_animation_file(self):
        """Test reading a GIF animation from a file path."""
        logger.info("--- Running test_read_gif_animation_file ---")
        gif_bytes_value = self.create_test_gif(num_frames=3)
        
        temp_file_path = "temp_animation.gif"
        with open(temp_file_path, 'wb') as f:
            f.write(gif_bytes_value)

        try:
            frames_data = await self.display_animation.read(temp_file_path)
            self.assertIsInstance(frames_data, list)
            self.assertEqual(len(frames_data), 3) # 3 frames in the GIF
            for frame in frames_data:
                self.assertIsInstance(frame, list)
                self.assertGreater(len(frame), 0)
        finally:
            os.remove(temp_file_path)

    async def test_read_gif_animation_bytes(self):
        """Test reading a GIF animation from bytes."""
        logger.info("--- Running test_read_gif_animation_bytes ---")
        gif_bytes_value = self.create_test_gif(num_frames=2)

        frames_data = await self.display_animation.read(gif_bytes_value)
        self.assertIsInstance(frames_data, list)
        self.assertEqual(len(frames_data), 2)
        for frame in frames_data:
                self.assertIsInstance(frame, list)
                self.assertGreater(len(frame), 0)

    async def test_encode_image_data_static(self):
        """Test encoding static image data."""
        logger.info("--- Running test_encode_image_data_static ---")
        img = self.create_test_image(size=(16, 16), color=(255, 0, 0)) # Red image
        encoded_data = self.display_animation._encode_image_data(img, is_animated=False)
        
        self.assertIsInstance(encoded_data, list)
        self.assertGreater(len(encoded_data), 0)
        
        # Basic sanity check on the structure based on Node.js logic:
        # "aa" + sizeHex + "000000" + nbColorsHex + colorString + pixelString
        # The first byte should be 0xAA
        self.assertEqual(encoded_data[0], 0xAA)
        # The 4th byte should be 0x00 (part of "000000")
        self.assertEqual(encoded_data[3], 0x00)
        # The 5th byte should be 0x00 (part of "000000")
        self.assertEqual(encoded_data[4], 0x00)
        # The 6th byte should be 0x00 (part of "000000")
        self.assertEqual(encoded_data[5], 0x00)
        # The 7th byte should be nbColors (1 in this case for a solid color image)
        self.assertEqual(encoded_data[6], 1)
        # The next 3 bytes should be the color (R, G, B)
        self.assertEqual(encoded_data[7], 0xFF) # Red
        self.assertEqual(encoded_data[8], 0x00) # Green
        self.assertEqual(encoded_data[9], 0x00) # Blue

    async def test_encode_image_data_animated(self):
        """Test encoding animated image data."""
        logger.info("--- Running test_encode_image_data_animated ---")
        img = self.create_test_image(size=(16, 16), color=(0, 255, 0)) # Green image
        encoded_data = self.display_animation._encode_image_data(img, is_animated=True, frame_delay=200, frame_index=0)
        
        self.assertIsInstance(encoded_data, list)
        self.assertGreater(len(encoded_data), 0)

        # Basic sanity check on the structure based on Node.js logic:
        # "aa" + sizeHex + delayHex + (resetPalette ? "00" : "01") + nbColorsHex + colorString + pixelString
        # The first byte should be 0xAA
        self.assertEqual(encoded_data[0], 0xAA)
        # The 4th and 5th bytes should be delayHex (200ms = 0xC800 little endian)
        self.assertEqual(encoded_data[3], 0xC8)
        self.assertEqual(encoded_data[4], 0x00)
        # The 6th byte should be resetPalette (0x00)
        self.assertEqual(encoded_data[5], 0x00)
        # The 7th byte should be nbColors (1 in this case for a solid color image)
        self.assertEqual(encoded_data[6], 1)
        # The next 3 bytes should be the color (R, G, B)
        self.assertEqual(encoded_data[7], 0x00) # Red
        self.assertEqual(encoded_data[8], 0xFF) # Green
        self.assertEqual(encoded_data[9], 0x00) # Blue

if __name__ == '__main__':
    unittest.main()
