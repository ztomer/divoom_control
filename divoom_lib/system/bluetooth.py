
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    BT_PASSWORD_CANCEL, BT_PASSWORD_SET, BT_PASSWORD_GET_STATUS
)

class Bluetooth:
    """
    Provides functionality to control the bluetooth settings of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.bluetooth.set_bluetooth_password(2) # Get status
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender) -> None:
        self._divoom = divoom
        self.logger = divoom.logger

    def _handle_bt_password_set(self, kwargs: dict) -> list | None:
        password = kwargs.get("password")
        if password:
            if len(password) != 4 or not password.isdigit():
                self.logger.error("Password must be a 4-digit string.")
                return None
            return [int(digit) for digit in password]
        self.logger.error("Missing 'password' for Set Bluetooth Password control.")
        return None

    def _handle_bt_password_cancel_or_get_status(self, kwargs: dict) -> list | None:
        return [] # No additional data

    _bt_password_handlers = {
        BT_PASSWORD_SET: _handle_bt_password_set,
        BT_PASSWORD_CANCEL: _handle_bt_password_cancel_or_get_status,
        BT_PASSWORD_GET_STATUS: _handle_bt_password_cancel_or_get_status,
    }

    async def set_bluetooth_password(self, control: int, **kwargs) -> bool:
        """
        Set the password for user's Bluetooth connection (0x27).
        
        Args:
            control (int): 1 to set, 0 to cancel, 2 to get status.
            password (str): 4-digit password (only for control=1).
            
        Usage::
            
            # Set bluetooth password to 1234
            await divoom.bluetooth.set_bluetooth_password(1, password="1234")
        """
        self.logger.info(
            f"Setting Bluetooth password (0x27) with control {control}...")
        args = [control]

        handler = self._bt_password_handlers.get(control)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(
                f"Unknown control for set_bluetooth_password: {control}")
            return False
        return await self._divoom.send_command(COMMANDS["set blue password"], args)
