
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    HOUR_TYPE_12, HOUR_TYPE_24, HOUR_TYPE_QUERY
)

class Time:
    """
    Provides functionality to control the time settings of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.time.set_hour_type(1) # 24-hour format
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender) -> None:
        self._divoom = divoom
        self.logger = divoom.logger

    async def set_hour_type(self, hour_type: int) -> bool:
        """
        Set the hour format (0x2c).
        
        Args:
            hour_type (int): 0 for 12-hour, 1 for 24-hour, 0xFF to query.
            
        Usage::
            
            # Set to 24-hour format
            await divoom.time.set_hour_type(1)
        """
        self.logger.info(f"Setting hour type to {hour_type} (0x2c)...")
        args = [hour_type]
        return await self._divoom.send_command(COMMANDS["set time type"], args)
