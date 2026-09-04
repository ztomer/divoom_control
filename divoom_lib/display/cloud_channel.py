# divoom_api/channels/cloud.py
from ..divoom import Divoom as DivoomBase
from typing import Optional, Dict, Any

class CloudChannel:
    """
    This class is used to display the Cloud Channel on the Divoom Timebox Evo.
    """
    _PACKAGE_PREFIX = "4502"

    def __init__(self, divoom_instance: DivoomBase):
        self._divoom_instance = divoom_instance

    async def show(self):
        """
        Activates and displays the Cloud Channel.
        """
        await self._update_message()

    async def _update_message(self):
        """
        Updates the message queue based on the parameters used.
        """
        command_code = int(self._PACKAGE_PREFIX[0:2], 16) # 0x45
        args = [int(self._PACKAGE_PREFIX[2:], 16)] # 0x02

        await self._divoom_instance.send_command(command_code, args)
