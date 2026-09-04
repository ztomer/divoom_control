
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    TOOL_TYPE_COUNTDOWN,
    GTI_COUNTDOWN_STATUS, GTI_COUNTDOWN_MINUTES, GTI_COUNTDOWN_SECONDS,
    STI_CTRL_FLAG_COUNTDOWN_START, STI_CTRL_FLAG_COUNTDOWN_CANCEL
)

class Countdown:
    """
    Provides functionality to control the countdown tool of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.countdown.set_countdown(1, 5, 0) # Start 5 minute countdown
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    async def get_countdown(self) -> dict | None:
        """
        Get information about the countdown tool.
        
        Returns:
            dict | None: A dictionary containing countdown information, or None if the command fails.
            
        Usage::
            
            countdown = await divoom.countdown.get_countdown()
            if countdown:
                print(f"Countdown: {countdown}")
        """
        self.logger.info("Getting countdown info (0x71)...")
        
        command_id = COMMANDS["get tool info"]
        args = [TOOL_TYPE_COUNTDOWN]
        
        # Set the command we are waiting for and send it with the correct protocol
        self._divoom._expected_response_command = command_id
        async with self._divoom._framing_context(use_ios=self._divoom.use_ios_le_protocol, escape=False):
            await self._divoom.send_command(command_id, args)

        # Wait for the response using the default (Basic) protocol
        response = await self._divoom.wait_for_response(command_id)
        
        if response and len(response) >= 3:
            return {
                "status": response[GTI_COUNTDOWN_STATUS],
                "minutes": response[GTI_COUNTDOWN_MINUTES],
                "seconds": response[GTI_COUNTDOWN_SECONDS],
            }
        return None

    async def set_countdown(self, ctrl_flag: int, minutes: int, seconds: int) -> bool:
        """
        Set information for the countdown tool.
        
        Args:
            ctrl_flag (int): 1 to start, 0 to cancel.
            minutes (int): The number of minutes for the countdown.
            seconds (int): The number of seconds for the countdown.
            
        Returns:
            bool: True if the command was sent successfully, False otherwise.
            
        Usage::
            
            # Start a 5 minute countdown
            await divoom.countdown.set_countdown(1, 5, 0)
        """
        self.logger.info(
            f"Setting countdown info: ctrl_flag={ctrl_flag}, minutes={minutes}, seconds={seconds} (0x72)...")

        args = [TOOL_TYPE_COUNTDOWN, ctrl_flag, minutes, seconds]
        return await self._divoom.send_command(COMMANDS["set tool"], args)
