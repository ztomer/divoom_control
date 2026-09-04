# divoom_api/channels/time.py
from ..divoom import Divoom as DivoomBase
from ..models import TimeDisplayType
# color2HexString is a module-level helper in utils.converters, NOT a method
# on Divoom — calling it via self._divoom_instance.color2HexString raised
# AttributeError at runtime (R53.43).
from ..utils.converters import color2HexString
from typing import Optional, Dict, Any

class TimeChannel:
    """
    This class is used to display the Time Channel on the Divoom Timebox Evo.
    """
    _PACKAGE_PREFIX = "450001"

    def __init__(self, divoom_instance: DivoomBase, opts: Optional[Dict[str, Any]] = None):
        self._divoom_instance = divoom_instance
        self._opts = {
            "type": TimeDisplayType.FullScreen,
            "showTime": True,
            "showWeather": False,
            "showTemp": False,
            "showCalendar": False,
            "color": "FFFFFF" # Default color
        }
        if opts:
            self._opts.update(opts)

    async def show(self):
        """
        Activates and displays the Time Channel with its current settings.
        """
        await self._update_message()

    async def _update_message(self):
        """
        Updates the message queue based on the parameters used.
        """
        color_hex = color2HexString(self._opts["color"])

        command_code = int(self._PACKAGE_PREFIX[0:2], 16) # 0x45
        args = [
            int(self._PACKAGE_PREFIX[2:4], 16), # 00
            int(self._PACKAGE_PREFIX[4:6], 16), # 01
            self._opts["type"],
            1 if self._opts["showTime"] else 0,
            1 if self._opts["showWeather"] else 0,
            1 if self._opts["showTemp"] else 0,
            1 if self._opts["showCalendar"] else 0,
        ]
        args.extend(bytes.fromhex(color_hex))

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
    def show_time(self) -> bool:
        return self._opts["showTime"]

    @show_time.setter
    def show_time(self, value: bool):
        self._opts["showTime"] = value

    @property
    def show_weather(self) -> bool:
        return self._opts["showWeather"]

    @show_weather.setter
    def show_weather(self, value: bool):
        self._opts["showWeather"] = value

    @property
    def show_temp(self) -> bool:
        return self._opts["showTemp"]

    @show_temp.setter
    def show_temp(self, value: bool):
        self._opts["showTemp"] = value

    @property
    def show_calendar(self) -> bool:
        return self._opts["showCalendar"]

    @show_calendar.setter
    def show_calendar(self, value: bool):
        self._opts["showCalendar"] = value
