
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS
)

class Radio:
    """
    Provides functionality to control the FM radio of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.radio.set_radio_frequency(875) # 87.5 MHz
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        """
        Initializes the Radio controller.

        Args:
            divoom: The Divoom object to send commands to the device.
        """
        self._divoom = divoom
        self.logger = divoom.logger

    async def set_radio_frequency(self, frequency: int) -> bool:
        """
        Set the FM radio frequency.

        Args:
            frequency (int): The frequency to set, e.g., 875 for 87.5 MHz.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # Set FM radio to 87.5 MHz
            await divoom.radio.set_radio_frequency(875)
        """
        self.logger.info(f"Setting radio frequency to {frequency} (0x61)...")
        args = list(frequency.to_bytes(2, byteorder='little'))
        return await self._divoom.send_command(COMMANDS["set radio frequency"], args)
