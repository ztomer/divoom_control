# divoom_api/channels/vjeffect.py
from ..divoom import Divoom as DivoomBase
from ..models import VJEffectType
# number2HexString is a module-level helper in utils.converters, NOT a method
# on Divoom — calling it via self._divoom_instance.number2HexString raised
# AttributeError at runtime (R53.43).
from ..utils.converters import number2HexString
from typing import Optional, Dict, Any

class VJEffectChannel:
    """
    This class is used to display the VJEffect Channel on the Divoom Timebox Evo.
    """
    _PACKAGE_PREFIX = "4503"

    def __init__(self, divoom_instance: DivoomBase, opts: Optional[Dict[str, Any]] = None):
        self._divoom_instance = divoom_instance
        self._opts = {
            "type": VJEffectType.Sparkles
        }
        if opts:
            self._opts.update(opts)

    async def show(self):
        """
        Activates and displays the VJ Effect Channel with its current settings.
        """
        await self._update_message()

    async def _update_message(self):
        """
        Updates the message queue based on the parameters used.
        """
        type_hex = number2HexString(self._opts["type"])

        # The Node.js version constructs a string like:
        # _PACKAGE_PREFIX + number2HexString(this._opts.type)
        # This implies the command is part of the _PACKAGE_PREFIX (45), and the rest are arguments.
        
        command_code = int(self._PACKAGE_PREFIX[0:2], 16) # 0x45
        args_hex_string = self._PACKAGE_PREFIX[2:] + type_hex
        
        # Convert the args_hex_string to a list of integers (bytes)
        args = [int(args_hex_string[i:i+2], 16) for i in range(0, len(args_hex_string), 2)]

        await self._divoom_instance.send_command(command_code, args)

    @property
    def type(self) -> int:
        return self._opts["type"]

    @type.setter
    def type(self, value: int):
        self._opts["type"] = value
