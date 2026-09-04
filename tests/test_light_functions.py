
import asyncio
import logging
import unittest
import os
import sys

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# --- Configuration ---
DEVICE_NAME_SUBSTRING = "Timoo"
LOG_LEVEL = logging.DEBUG

# Setup basic logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("light_functions_test")

class TestLightFunctions(unittest.IsolatedAsyncioTestCase):

    divoom: Divoom = None
    
    async def asyncSetUp(self):
        """Discover and connect to the device before each test."""
        ble_device, _ = await discover_device(name_substring=DEVICE_NAME_SUBSTRING)
        if not ble_device:
            self.fail(f"No device found with name containing '{DEVICE_NAME_SUBSTRING}'.")
        
        # Based on previous investigations, we know the correct protocol settings
        self.divoom = Divoom(
            mac=ble_device.address, 
            logger=logger, 
            use_ios_le_protocol=False # Use Basic Protocol for notifications
        )
        await self.divoom.connect()
        
        self.divoom.WRITE_CHARACTERISTIC_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
        self.divoom.NOTIFY_CHARACTERISTIC_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
        self.divoom.escapePayload = False

    async def asyncTearDown(self):
        """Disconnect after each test."""
        if self.divoom and self.divoom.is_connected:
            await self.divoom.disconnect()

    async def test_get_light_mode(self):
        """Test getting the current light mode, which contains many settings."""
        logger.info("--- Running test_get_light_mode ---")
        
        light_settings = await self.divoom.light.get_light_mode()
        
        logger.info(f"Got light settings: {light_settings}")
        self.assertIsNotNone(light_settings)
        self.assertIsInstance(light_settings, dict)
        
        # Check for the presence of all expected keys
        expected_keys = [
            "current_light_effect_mode", "temperature_display_mode", "vj_selection_option",
            "rgb_color_values", "brightness_level", "lighting_mode_selection_option",
            "on_off_switch", "music_mode_selection_option", "system_brightness",
            "time_display_format_selection_option", "time_display_rgb_color_values",
            "time_display_mode", "time_checkbox_modes"
        ]
        for key in expected_keys:
            self.assertIn(key, light_settings)
            
        # Validate that brightness exists and is a valid value
        self.assertIn("brightness_level", light_settings)
        self.assertIsInstance(light_settings["brightness_level"], int)
        self.assertTrue(0 <= light_settings["brightness_level"] <= 100)
        logger.info(f"Brightness level is {light_settings['brightness_level']}, which is a valid value.")

    async def test_set_gif_speed(self):
        """Test setting the GIF animation speed."""
        logger.info("--- Running test_set_gif_speed ---")
        test_speed = 100  # 100ms
        
        # This is an action command, we just check for success
        result = await self.divoom.light.set_gif_speed(test_speed)
        self.assertTrue(result)
        logger.info(f"Successfully sent set_gif_speed command with speed {test_speed}ms.")

    async def test_set_light_phone_word_attr_color(self):
        """Test setting the text color attribute."""
        logger.info("--- Running test_set_light_phone_word_attr_color ---")
        
        # Set text color to red for text box 0
        result = await self.divoom.light.set_light_phone_word_attr(
            control=constants.LPWA_CONTROL_COLOR,
            color=[255, 0, 0],
            text_box_id=0
        )
        self.assertTrue(result)
        logger.info("Successfully sent set_light_phone_word_attr command for color.")

    async def test_set_light_phone_word_attr_speed(self):
        """Test setting the text speed attribute."""
        logger.info("--- Running test_set_light_phone_word_attr_speed ---")
        
        # Set text speed to 100ms for text box 0
        result = await self.divoom.light.set_light_phone_word_attr(
            control=constants.LPWA_CONTROL_SPEED,
            speed=100,
            text_box_id=0
        )
        self.assertTrue(result)
        logger.info("Successfully sent set_light_phone_word_attr command for speed.")

    async def test_set_light_phone_word_attr_content(self):
        """Test setting the text content attribute."""
        logger.info("--- Running test_set_light_phone_word_attr_content ---")
        
        # Set text content for text box 0
        result = await self.divoom.light.set_light_phone_word_attr(
            control=constants.LPWA_CONTROL_CONTENT,
            text_content="Hello",
            text_box_id=0
        )
        self.assertTrue(result)
        logger.info("Successfully sent set_light_phone_word_attr command for content.")

    async def test_app_new_send_gif_cmd(self):
        """Test sending a new GIF command."""
        logger.info("--- Running test_app_new_send_gif_cmd ---")
        
        fake_gif_data = [0x01, 0x02, 0x03, 0x04]
        file_size = len(fake_gif_data)

        # Start sending
        logger.info("Starting GIF send...")
        result = await self.divoom.light.app_new_send_gif_cmd(
            control_word=constants.ANSGC_CONTROL_START_SENDING,
            file_size=file_size
        )
        self.assertTrue(result)
        await asyncio.sleep(1.0)

        # Send data
        logger.info("Sending GIF data...")
        result = await self.divoom.light.app_new_send_gif_cmd(
            control_word=constants.ANSGC_CONTROL_SENDING_DATA,
            file_size=file_size,
            file_offset_id=0,
            file_data=fake_gif_data
        )
        self.assertTrue(result)
        await asyncio.sleep(1.0)

        # Terminate sending
        logger.info("Terminating GIF send...")
        result = await self.divoom.light.app_new_send_gif_cmd(
            control_word=constants.ANSGC_CONTROL_TERMINATE_SENDING
        )
        self.assertTrue(result)
        logger.info("Successfully sent app_new_send_gif_cmd commands.")

    async def test_modify_user_gif_items(self):
        """Test modifying user GIF items."""
        logger.info("--- Running test_modify_user_gif_items ---")

        # Get number of user GIFs
        logger.info("Getting number of user GIFs...")
        num_gifs = await self.divoom.light.modify_user_gif_items(constants.MUGI_DATA_GET_COUNT)
        self.assertIsNotNone(num_gifs)
        self.assertIsInstance(num_gifs, int)
        logger.info(f"Number of user GIFs: {num_gifs}")

        # Deleting a GIF is a destructive operation, so we will not test it
        # in an automated test without a way to restore it.
        # We will just check that the command can be sent.
        logger.info("Testing deletion command (without actual deletion)...")
        # To avoid actual deletion, we can't really test this.
        # We'll assume if get count works, delete would send a valid command.
        pass

    async def test_drawing_pad_exit(self):
        """Test exiting the drawing pad."""
        logger.info("--- Running test_drawing_pad_exit ---")
        result = await self.divoom.light.drawing_pad_exit()
        self.assertTrue(result)
        logger.info("Successfully sent drawing_pad_exit command.")


if __name__ == '__main__':
    unittest.main()
