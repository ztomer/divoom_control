
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    STMI_STATUS, STMI_HOUR, STMI_MINUTE, STMI_WEEK, STMI_MODE, STMI_TRIGGER_MODE,
    STMI_FM_FREQ_START, STMI_FM_FREQ_LENGTH, STMI_VOLUME, STMI_TYPE,
    STMI_ANIMATION_ID, STMI_ANIMATION_SPEED, STMI_ANIMATION_DIRECTION,
    STMI_ANIMATION_FRAME_COUNT, STMI_ANIMATION_FRAME_DELAY, STMI_ANIMATION_FRAME_DATA_START,
    STMI_TYPE_0, STMI_TYPE_1,
    STMC_STATUS, STMC_INDEX
)

class Timeplan:
    """
    Provides functionality to control the time plans of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                # This is a low-level command.
                # await divoom.timeplan.set_time_manage_info(...)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """

    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    async def set_time_manage_info(self, status: int, hour: int, minute: int, week: int, mode: int, trigger_mode: int, fm_freq: int, volume: int, type: int, animation_id: int = None, animation_speed: int = None, animation_direction: int = None, animation_frame_count: int = None, animation_frame_delay: int = None, animation_frame_data: list = None) -> bool:
        """
        Set the time management information (0x56).
        
        Usage::
            
            # This is a low-level command.
            # await divoom.timeplan.set_time_manage_info(...)
        """
        self.logger.info(f"Setting time manage info (0x56)...")
        args = []

        args.append(status)
        args.append(hour)
        args.append(minute)
        args.append(week)
        args.append(mode)
        args.append(trigger_mode)
        
        args.extend(fm_freq.to_bytes(STMI_FM_FREQ_LENGTH, byteorder='little'))

        args.append(volume)
        args.append(type)

        if type == STMI_TYPE_0:
            # Type 0: Animation
            if animation_id is not None:
                args.append(animation_id)
            else:
                args.append(0) # Default if not provided
            if animation_speed is not None:
                args.append(animation_speed)
            else:
                args.append(0) # Default if not provided
            if animation_direction is not None:
                args.append(animation_direction)
            else:
                args.append(0) # Default if not provided
            if animation_frame_count is not None:
                args.append(animation_frame_count)
            else:
                args.append(0) # Default if not provided
            if animation_frame_delay is not None:
                args.append(animation_frame_delay)
            else:
                args.append(0) # Default if not provided
            if animation_frame_data is not None:
                args.extend(animation_frame_data)
        elif type == STMI_TYPE_1:
            # Type 1: Other settings (no animation data)
            pass
        else:
            self.logger.warning(f"Unknown type for set_time_manage_info: {type}")
            return False

        return await self._divoom.send_command(COMMANDS["set time manage info"], args)

    async def set_time_manage_ctrl(self, status: int, index: int):
        """
        Control the time management function (0x57).
        
        Usage::
            
            # This is a low-level command.
            # await divoom.timeplan.set_time_manage_ctrl(1, 0)
        """
        self.logger.info(
            f"Setting time manage control: status={status}, index={index} (0x57)...")
        args = []
        args += status.to_bytes(1, byteorder='big')
        args += index.to_bytes(1, byteorder='big')
        return await self._divoom.send_command(COMMANDS["set time manage ctrl"], args)
