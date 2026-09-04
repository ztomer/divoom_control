from .device import Device
from .time import Time
from .bluetooth import Bluetooth
from ..sender_protocol import CommandSender

class System(Device):
    def __init__(self, divoom: CommandSender) -> None:
        super().__init__(divoom)
        self._time = Time(divoom)

    async def set_hour_type(self, hour_type: int) -> bool:
        return await self._time.set_hour_type(hour_type)

__all__ = ["System", "Device", "Time", "Bluetooth"]
