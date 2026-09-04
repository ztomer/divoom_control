# divoom_api/channels/scoreboard.py
from ..divoom import Divoom as DivoomBase
from typing import Optional, Dict, Any

class ScoreBoardChannel:
    """
    This class is used to display the Scoreboard Channel on the Divoom Timebox Evo.
    """
    _PACKAGE_PREFIX = "450600"

    def __init__(self, divoom_instance: DivoomBase, opts: Optional[Dict[str, Any]] = None):
        self._divoom_instance = divoom_instance
        self._opts = {
            "red": 0,
            "blue": 0
        }
        if opts:
            self._opts.update(opts)

    async def show(self):
        """
        Activates and displays the Scoreboard Channel with its current settings.
        """
        await self._update_message()

    async def _update_message(self):
        """
        Updates the message queue based on the parameters used.
        """
        red_score_hex = self._divoom_instance._int2hexlittle(self._opts["red"])
        blue_score_hex = self._divoom_instance._int2hexlittle(self._opts["blue"])

        # The Node.js version constructs a string like:
        # _PACKAGE_PREFIX + int2hexlittle(this._opts.red) + int2hexlittle(this._opts.blue)
        # This implies the command is part of the _PACKAGE_PREFIX (45), and the rest are arguments.
        
        command_code = int(self._PACKAGE_PREFIX[0:2], 16) # 0x45
        args_hex_string = self._PACKAGE_PREFIX[2:] + red_score_hex + blue_score_hex
        
        # Convert the args_hex_string to a list of integers (bytes)
        args = [int(args_hex_string[i:i+2], 16) for i in range(0, len(args_hex_string), 2)]

        await self._divoom_instance.send_command(command_code, args)

    @property
    def red(self) -> int:
        return self._opts["red"]

    @red.setter
    def red(self, value: int):
        self._opts["red"] = max(0, min(999, value))

    @property
    def blue(self) -> int:
        return self._opts["blue"]

    @blue.setter
    def blue(self, value: int):
        self._opts["blue"] = max(0, min(999, value))
