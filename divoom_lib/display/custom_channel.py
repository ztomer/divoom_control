# divoom_api/channels/custom.py
from ..divoom import Divoom as DivoomBase
from typing import Optional, Dict, Any

class CustomChannel:
    """
    This class is used to display the Custom Channel on the Divoom Timebox Evo.
    """
    _PACKAGE_HEADER = "4505"

    def __init__(self, divoom_instance: DivoomBase):
        self._divoom_instance = divoom_instance

    async def show(self):
        """
        Activates and displays the Custom Channel.
        """
        await self._update_message()

    async def _update_message(self):
        """
        Updates the message queue based on the parameters used.
        """
        command_code = int(self._PACKAGE_HEADER[0:2], 16) # 0x45
        args = [int(self._PACKAGE_HEADER[2:], 16)] # 0x05

        await self._divoom_instance.send_command(command_code, args)
