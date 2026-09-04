
import asyncio
import logging
import unittest
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from divoom_lib.system.temp_weather import TempWeatherCommand
from divoom_lib.divoom import Divoom as DivoomBase # Import DivoomBase for type hinting and mocking
from divoom_lib.models import WeatherType, COMMANDS

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_temp_weather_functions")

class TestTempWeatherFunctions(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up a mock Divoom instance for testing."""
        self.mock_divoom_instance = AsyncMock(spec=DivoomBase)
        self.mock_divoom_instance.logger = logger
        # R53.43: the old TempWeatherCommand called self._divoom_instance.number2HexString
        # (an AttributeError — it's a utils.converters helper, not a Divoom method). The
        # shim now delegates to Weather, which encodes the temperature with pure math and
        # never touches that helper, so monkeypatching it onto the mock is dead/misleading.
        # Removed; the assertions below pin the real encoded bytes via send_command.
        self.mock_divoom_instance.send_command = AsyncMock(return_value=True) # Mock send_command

        # Instantiate TempWeatherCommand without triggering _update_message in __init__
        self.temp_weather_command = TempWeatherCommand(self.mock_divoom_instance)

    async def test_update_message_sends_correct_command_positive_temp(self):
        """Test that _update_message constructs and sends the correct command for positive temperature."""
        logger.info("--- Running test_update_message_sends_correct_command_positive_temp ---")
        
        self.temp_weather_command.temperature = 25
        self.temp_weather_command.weather = WeatherType.Clear
        
        await self.temp_weather_command.update_temp_weather()
        
        self.mock_divoom_instance.send_command.assert_called_once_with(
            COMMANDS["set temp"], # 0x5F
            [0x19, WeatherType.Clear] # 25 (0x19), WeatherType.Clear (1)
        )

    async def test_update_message_sends_correct_command_zero_temp(self):
        """Test that _update_message constructs and sends the correct command for zero temperature."""
        logger.info("--- Running test_update_message_sends_correct_command_zero_temp ---")
        
        self.mock_divoom_instance.send_command.reset_mock()
        self.temp_weather_command.temperature = 0
        self.temp_weather_command.weather = WeatherType.CloudySky
        
        await self.temp_weather_command.update_temp_weather()
        
        self.mock_divoom_instance.send_command.assert_called_once_with(
            COMMANDS["set temp"], # 0x5F
            [0x00, WeatherType.CloudySky] # 0 (0x00), WeatherType.CloudySky (3)
        )

    async def test_update_message_sends_correct_command_negative_temp(self):
        """Test that _update_message constructs and sends the correct command for negative temperature."""
        logger.info("--- Running test_update_message_sends_correct_command_negative_temp ---")
        
        self.mock_divoom_instance.send_command.reset_mock()
        self.temp_weather_command.temperature = -10
        self.temp_weather_command.weather = WeatherType.Rain
        
        await self.temp_weather_command.update_temp_weather()
        
        # -10 + 256 = 246 (0xF6)
        self.mock_divoom_instance.send_command.assert_called_once_with(
            COMMANDS["set temp"], # 0x5F
            [0xF6, WeatherType.Rain] # 246 (0xF6), WeatherType.Rain (6)
        )

    async def test_temperature_setter_updates_internal_state(self):
        """Test that setting the temperature property updates the internal state."""
        logger.info("--- Running test_temperature_setter_updates_internal_state ---")
        
        self.temp_weather_command.temperature = 100
        self.assertEqual(self.temp_weather_command.temperature, 100)
        self.mock_divoom_instance.send_command.assert_not_called() # Ensure no auto-send

    async def test_weather_setter_updates_internal_state(self):
        """Test that setting the weather property updates the internal state."""
        logger.info("--- Running test_weather_setter_updates_internal_state ---")
        
        self.temp_weather_command.weather = WeatherType.Snow
        self.assertEqual(self.temp_weather_command.weather, WeatherType.Snow)
        self.mock_divoom_instance.send_command.assert_not_called() # Ensure no auto-send

    async def test_update_message_value_error_low_temp(self):
        """Test that _update_message raises ValueError for temperature below -127."""
        logger.info("--- Running test_update_message_value_error_low_temp ---")
        
        self.temp_weather_command.temperature = -128
        with self.assertRaises(ValueError):
            await self.temp_weather_command.update_temp_weather()

    async def test_update_message_value_error_high_temp(self):
        """Test that _update_message raises ValueError for temperature above 128."""
        logger.info("--- Running test_update_message_value_error_high_temp ---")
        
        self.temp_weather_command.temperature = 129
        with self.assertRaises(ValueError):
            await self.temp_weather_command.update_temp_weather()

if __name__ == '__main__':
    unittest.main()
