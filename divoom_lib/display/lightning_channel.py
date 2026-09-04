# divoom_api/channels/lightning.py
from ..divoom import Divoom as DivoomBase
from ..models import LightningType
# color2HexString / number2HexString / boolean2HexString are module-level
# helpers in utils.converters, NOT methods on Divoom — calling them via
# self._divoom_instance.<helper> raised AttributeError at runtime (R53.43).
from ..utils.converters import number2HexString, color2HexString, boolean2HexString
from typing import Optional, Dict, Any

class LightningChannel:
    """
    This class is used to display the Lightning Channel on the Divoom Timebox Evo.
    """
    _PACKAGE_PREFIX = "4501"
    _PACKAGE_SUFFIX = "000000"

    def __init__(self, divoom_instance: DivoomBase, opts: Optional[Dict[str, Any]] = None):
        self._divoom_instance = divoom_instance
        self._opts = {
            "type": LightningType.PlainColor,
            "brightness": 100,
            "power": True,
            "color": "FFFFFF" # Default color
        }
        if opts:
            self._opts.update(opts)

    async def show(self):
        """
        Activates and displays the Lightning Channel with its current settings.
        """
        await self._update_message()

    async def _update_message(self):
        """
        Updates the message queue based on the parameters used.
        """
        color_hex = color2HexString(self._opts["color"])
        brightness_hex = number2HexString(self._opts["brightness"])
        type_hex = number2HexString(self._opts["type"])
        power_hex = boolean2HexString(self._opts["power"])

        # The Node.js version constructs a string like:
        # _PACKAGE_PREFIX + color2HexString(this._color) + brightness2HexString(this._opts.brightness) + number2HexString(this._opts.type) + boolean2HexString(this._opts.power) + this._PACKAGE_SUFFIX
        # This implies the command is part of the _PACKAGE_PREFIX (45), and the rest are arguments.
        
        command_code = int(self._PACKAGE_PREFIX[0:2], 16) # 0x45
        args_hex_string = self._PACKAGE_PREFIX[2:] + color_hex + brightness_hex + type_hex + power_hex + self._PACKAGE_SUFFIX
        
        # Convert the args_hex_string to a list of integers (bytes)
        args = [int(args_hex_string[i:i+2], 16) for i in range(0, len(args_hex_string), 2)]

        await self._divoom_instance.send_command(command_code, args)

    @property
    def type(self) -> int:
        return self._opts["type"]

    @type.setter
    def type(self, value: int):
        self._opts["type"] = value

    @property
    def color(self) -> str:
        return self._opts["color"]

    @color.setter
    def color(self, value: str):
        self._opts["color"] = value

    @property
    def power(self) -> bool:
        return self._opts["power"]

    @power.setter
    def power(self, value: bool):
        self._opts["power"] = value

    @property
    def brightness(self) -> int:
        return self._opts["brightness"]

    @brightness.setter
    def brightness(self, value: int):
        self._opts["brightness"] = value
