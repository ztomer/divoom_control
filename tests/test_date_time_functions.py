
import asyncio
import logging
import unittest
import os
import sys
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from divoom_lib.system.date_time import DateTimeCommand
from divoom_lib.divoom import Divoom as DivoomBase # Import DivoomBase for type hinting and mocking
from divoom_lib import models as constants

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_date_time_functions")

class TestDateTimeFunctions(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up a mock Divoom instance for testing."""
        self.mock_divoom_instance = AsyncMock(spec=DivoomBase)
        self.mock_divoom_instance.logger = logger
        # NB: do NOT monkeypatch number2HexString onto the mock. It is NOT a
        # method on Divoom (it's a module-level helper in utils.converters), and
        # mocking it here masked the AttributeError that made "Sync Time" silently
        # fail in production. With the real fix, DateTimeCommand calls the module
        # function directly, so the spec'd mock needs only send_command.
        self.mock_divoom_instance.send_command = AsyncMock(return_value=True)

        # Instantiate DateTimeCommand without triggering _update_message in __init__
        self.date_time_command = DateTimeCommand(self.mock_divoom_instance)

    async def test_update_message_sends_correct_command(self):
        """Test that _update_message constructs and sends the correct date/time command."""
        logger.info("--- Running test_update_message_sends_correct_command ---")
        
        # Set a specific date and time for predictable testing
        test_datetime = datetime.datetime(2025, 11, 15, 10, 30, 45)
        self.date_time_command.date = test_datetime
        
        # Explicitly trigger the update
        await self.date_time_command.update_date_time()
        
        self.mock_divoom_instance.send_command.assert_called_once()

        # Expected command ID is 0x18
        expected_command_id = 0x18
        self.assertEqual(self.mock_divoom_instance.send_command.call_args[0][0], expected_command_id)

        # And the actual encoded payload: year_lsb(25), year_msb(20), month(11),
        # day(15), hour(10), minute(30), second(45), trailing 00. This pins the
        # real number2HexString encoding (the masked test never checked it).
        self.assertEqual(
            self.mock_divoom_instance.send_command.call_args[0][1],
            [0x19, 0x14, 0x0b, 0x0f, 0x0a, 0x1e, 0x2d, 0x00],
        )

        # Expected args: year_lsb, year_msb, month, day, hour, minute, second, 0x00
        # 2025 -> 25 (0x19), 20 (0x14)
        # 11 -> 0x0B
        # 15 -> 0x0F
        # 10 -> 0x0A
        # 30 -> 0x1E
        # 45 -> 0x2D
        expected_args = [0x19, 0x14, 0x0B, 0x0F, 0x0A, 0x1E, 0x2D, 0x00]
        self.assertEqual(self.mock_divoom_instance.send_command.call_args[0][1], expected_args)

    async def test_date_setter_updates_internal_state(self):
        """Test that setting the date property updates the internal state."""
        logger.info("--- Running test_date_setter_updates_internal_state ---")
        
        new_datetime = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.date_time_command.date = new_datetime
        
        self.assertEqual(self.date_time_command.date, new_datetime)
        
        # Ensure send_command was NOT called automatically by the setter
        self.mock_divoom_instance.send_command.assert_not_called()

    async def test_update_date_time_with_default_date(self):
        """Test update_date_time when initialized with default date (current time)."""
        logger.info("--- Running test_update_date_time_with_default_date ---")
        
        # Reset mock for this test
        self.mock_divoom_instance.send_command.reset_mock()
        
        # Instantiate with default date (current time)
        date_time_command_default = DateTimeCommand(self.mock_divoom_instance)
        
        # Explicitly trigger the update
        await date_time_command_default.update_date_time()
        
        self.mock_divoom_instance.send_command.assert_called_once()
        
        # Verify command ID
        self.assertEqual(self.mock_divoom_instance.send_command.call_args[0][0], 0x18)
        
        # Verify args structure (values will be current time, so just check length and type)
        args = self.mock_divoom_instance.send_command.call_args[0][1]
        self.assertIsInstance(args, list)
        self.assertEqual(len(args), 8) # 7 date/time bytes + 1 padding byte

if __name__ == '__main__':
    unittest.main()
