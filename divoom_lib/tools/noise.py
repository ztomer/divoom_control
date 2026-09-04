
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    TOOL_TYPE_NOISE,
    GTI_NOISE_STATUS,
    STI_CTRL_FLAG_NOISE_START, STI_CTRL_FLAG_NOISE_STOP
)

class Noise:
    """
    Provides functionality to control the noise tool of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.noise.set_noise(1) # Start noise meter
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    async def get_noise(self) -> dict | None:
        """
        Get information about the noise tool.
        
        Returns:
            dict | None: A dictionary containing noise tool information, or None if the command fails.
            
        Usage::
            
            noise = await divoom.noise.get_noise()
            if noise:
                print(f"Noise status: {noise['status']}")
        """
        self.logger.info("Getting noise info (0x71)...")
        
        command_id = COMMANDS["get tool info"]
        args = [TOOL_TYPE_NOISE]
        
        # Set the command we are waiting for and send it with the correct protocol
        self._divoom._expected_response_command = command_id
        async with self._divoom._framing_context(use_ios=self._divoom.use_ios_le_protocol, escape=False):
            await self._divoom.send_command(command_id, args)

        # Wait for the response using the default (Basic) protocol
        response = await self._divoom.wait_for_response(command_id)
        
        if response and len(response) >= 1:
            return {"status": response[GTI_NOISE_STATUS]}
        return None

    async def set_noise(self, ctrl_flag: int) -> bool:
        """
        Set information for the noise tool.
        
        Args:
            ctrl_flag (int): 1 to start, 0 to stop.
            
        Returns:
            bool: True if the command was sent successfully, False otherwise.
            
        Usage::
            
            # Start the noise meter
            await divoom.noise.set_noise(1)
        """
        self.logger.info(
            f"Setting noise info: ctrl_flag={ctrl_flag} (0x72)...")

        args = [TOOL_TYPE_NOISE, ctrl_flag]
        return await self._divoom.send_command(COMMANDS["set tool"], args)
