from divoom_legacy.system.device import Device
from divoom_legacy.system.time import Time
from divoom_legacy.system.bluetooth import Bluetooth
from divoom_legacy.sender_protocol import CommandSender

class System(Device):
    def __init__(self, divoom: CommandSender) -> None:
        super().__init__(divoom)
        self._time = Time(divoom)

    async def set_hour_type(self, hour_type: int) -> bool:
        return await self._time.set_hour_type(hour_type)

__all__ = ["System", "Device", "Time", "Bluetooth"]
