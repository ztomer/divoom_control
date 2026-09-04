
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    TOOL_TYPE_TIMER,
    GTI_TIMER_STATUS,
    STI_CTRL_FLAG_TIMER_PAUSED, STI_CTRL_FLAG_TIMER_STARTED, STI_CTRL_FLAG_TIMER_RESET,
    STI_CTRL_FLAG_TIMER_ENTERING_STOPWATCH
)

class Timer:
    """
    Provides functionality to control the timer tool of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.timer.set_timer(1) # Start timer
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    async def get_timer(self) -> dict | None:
        """
        Get information about the timer tool.
        
        Returns:
            dict | None: A dictionary containing timer information, or None if the command fails.
            
        Usage::
            
            timer = await divoom.timer.get_timer()
            if timer:
                print(f"Timer status: {timer['status']}")
        """
        self.logger.info("Getting timer info (0x71)...")
        
        command_id = COMMANDS["get tool info"]
        args = [TOOL_TYPE_TIMER]
        
        # Set the command we are waiting for and send it with the correct protocol
        self._divoom._expected_response_command = command_id
        async with self._divoom._framing_context(use_ios=self._divoom.use_ios_le_protocol, escape=False):
            await self._divoom.send_command(command_id, args)

        # Wait for the response using the default (Basic) protocol
        response = await self._divoom.wait_for_response(command_id)
        
        if response and len(response) >= 1:
            return {"status": response[GTI_TIMER_STATUS]}
        return None

    async def set_timer(self, ctrl_flag: int) -> bool:
        """
        Set information for the timer tool.
        
        Args:
            ctrl_flag (int): 0 to pause, 1 to start, 2 to reset.
            
        Returns:
            bool: True if the command was sent successfully, False otherwise.
            
        Usage::
            
            # Start the timer
            await divoom.timer.set_timer(1)
        """
        self.logger.info(
            f"Setting timer info: ctrl_flag={ctrl_flag} (0x72)...")

        args = [TOOL_TYPE_TIMER, ctrl_flag]
        return await self._divoom.send_command(COMMANDS["set tool"], args)
