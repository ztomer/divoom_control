
import datetime
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    ALARM_COUNT, GAT_ALARM_INFO_LENGTH,
    GAT_STATUS, GAT_HOUR, GAT_MINUTE, GAT_WEEK, GAT_MODE, GAT_TRIGGER_MODE,
    GAT_FM_FREQ_START, GAT_VOLUME,
    MEMORIAL_COUNT, GMT_MEMORIAL_INFO_LENGTH,
    GMT_DIALY_ID, GMT_ON_OFF, GMT_MONTH, GMT_DAY, GMT_HOUR, GMT_MINUTE,
    GMT_HAVE_FLAG, GMT_TITLE_NAME_START, GMT_TITLE_NAME_END
)
from divoom_lib.utils.converters import bool_to_byte

class Alarm:
    """
    Provides functionality to control the alarms of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                alarms = await divoom.alarm.get_alarm_time()
                if alarms:
                    print(f"Alarms: {alarms}")
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger
    async def get_alarm_time(self):
        """
        Get alarm time (0x42).
        
        Returns:
            list | None: A list of alarm dictionaries, or None if the command fails.
            
        Usage::
            
            alarms = await divoom.alarm.get_alarm_time()
            if alarms:
                for alarm in alarms:
                    print(f"Alarm: {alarm}")
        """
        self.logger.info("Getting alarm time (0x42)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get alarm time"])
        if not response:
            return None
        # APK-verified record layout (u1/b.a()): 10 bytes per alarm, byte 0 is
        # the alarm index. Old-mode devices report 3 alarms, new-mode 10 —
        # parse whatever full records are present.
        count = min(ALARM_COUNT, len(response) // GAT_ALARM_INFO_LENGTH)
        if count == 0:
            return None
        alarms = []
        for i in range(count):
            alarm_data = response[i*GAT_ALARM_INFO_LENGTH:(i+1)*GAT_ALARM_INFO_LENGTH]
            alarms.append({
                "status": alarm_data[GAT_STATUS],
                "hour": alarm_data[GAT_HOUR],
                "minute": alarm_data[GAT_MINUTE],
                "week": alarm_data[GAT_WEEK],
                "mode": alarm_data[GAT_MODE],
                "trigger_mode": alarm_data[GAT_TRIGGER_MODE],
                "fm_freq": int.from_bytes(alarm_data[GAT_FM_FREQ_START:GAT_FM_FREQ_START + 2], byteorder='little'),
                "volume": alarm_data[GAT_VOLUME],
            })
        return alarms

    async def _set_animation_gif(self, command_key: str, index: int, total_length: int, gif_id: int, data: list) -> bool:
        """Helper method to set animation GIF for alarm or memorial."""
        self.logger.info(
            f"Setting animation GIF for {command_key} with index {index} (0x{COMMANDS[command_key]:02x})...")
        args = []
        args += index.to_bytes(1, byteorder='big')
        args += total_length.to_bytes(2, byteorder='little')
        args += gif_id.to_bytes(1, byteorder='big')
        args.extend(data)
        return await self._divoom.send_command(COMMANDS[command_key], args)

    async def set_alarm(self, alarm_index: int, status: int, hour: int, minute: int, week: int, mode: int, trigger_mode: int, fm_freq: int = 0, volume: int = 0) -> bool:
        """
        Set the extended alarm time information in the device (0x43).
        
        Args:
            alarm_index (int): Which alarm to set, starting from 0.
            status (int): 1 (alarm on), 0 (alarm off).
            hour (int): Hour to set for the alarm.
            minute (int): Minute to set for the alarm.
            week (int): Bits 0 to 6 represent Sunday to Saturday, respectively. Set to 1 if the alarm should repeat on that day.
            mode (int): Alarm mode (ALARM_MUSIC=0, and others: 1, 2, 3, 4).
            trigger_mode (int): Alarm trigger mode (ALARM_TRIGGER_MUSIC=1, ALARM_TRIGGER_GIF=4).
            fm_freq (int): If trigger_mode is ALARM_TRIGGER_MUSIC, these 2 bytes represent the frequency point.
            volume (int): Volume level for the alarm, ranging from 0 to 100.
            
        Usage::
            
            # Set alarm 0 to 8:30 AM on weekdays
            await divoom.alarm.set_alarm(0, 1, 8, 30, 0b0111110, 0, 1)
        """
        self.logger.info(f"Setting alarm {alarm_index} (0x43)...")
        args = []
        args.append(alarm_index)
        args.append(status)
        args.append(hour)
        args.append(minute)
        args.append(week)
        args.append(mode)
        args.append(trigger_mode)
        args += fm_freq.to_bytes(2, byteorder='little')
        args.append(volume)
        return await self._divoom.send_command(COMMANDS["set alarm"], args)

    async def set_alarm_gif(self, alarm_index: int, total_length: int, gif_id: int, data: list) -> bool:
        """
        Set the alarm animation for a specific alarm (0x51).
        
        Usage::
            
            # This is a low-level command. Consider using a higher-level library for GIF processing.
            # await divoom.alarm.set_alarm_gif(alarm_index=0, total_length=100, gif_id=1, data=[...])
        """
        return await self._set_animation_gif("set alarm gif", alarm_index, total_length, gif_id, data)

    async def get_memorial_time(self):
        """
        Get memorial time (0x53).
        
        Returns:
            list | None: A list of memorial dictionaries, or None if the command fails.
            
        Usage::
            
            memorials = await divoom.alarm.get_memorial_time()
            if memorials:
                for memorial in memorials:
                    print(f"Memorial: {memorial}")
        """
        self.logger.info("Getting memorial time (0x53)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get memorial time"])
        if response and len(response) >= MEMORIAL_COUNT * GMT_MEMORIAL_INFO_LENGTH:  # 10 records, each 39 bytes
            memorials = []
            for i in range(MEMORIAL_COUNT):
                memorial_data = response[i*GMT_MEMORIAL_INFO_LENGTH:(i+1)*GMT_MEMORIAL_INFO_LENGTH]
                if len(memorial_data) == GMT_MEMORIAL_INFO_LENGTH:
                    memorials.append({
                        "dialy_id": memorial_data[GMT_DIALY_ID],
                        "on_off": memorial_data[GMT_ON_OFF],
                        "month": memorial_data[GMT_MONTH],
                        "day": memorial_data[GMT_DAY],
                        "hour": memorial_data[GMT_HOUR],
                        "minute": memorial_data[GMT_MINUTE],
                        "have_flag": memorial_data[GMT_HAVE_FLAG],
                        # errors='replace': a title cut mid-multibyte at the 32-byte
                        # field boundary (or any non-UTF-8 device byte) otherwise
                        # raised UnicodeDecodeError and aborted ALL memorials, unlike
                        # the deliberately-tolerant get_alarm_time parser.
                        "title_name": bytes(memorial_data[GMT_TITLE_NAME_START:GMT_TITLE_NAME_END]).decode('utf-8', errors='replace').strip('\x00')
                    })
            return memorials
        return None

    async def set_memorial_time(self, dialy_id: int, on_off: int, month: int, day: int, hour: int, minute: int, have_flag: int, title_name: str) -> bool:
        """
        Set memorial time (0x54).
        
        Usage::
            
            # Set a memorial for New Year's Day
            await divoom.alarm.set_memorial_time(0, 1, 1, 1, 0, 0, 1, "New Year's Day")
        """
        self.logger.info(f"Setting memorial time for id {dialy_id} (0x54)...")
        args = []
        args.append(dialy_id)
        args.append(on_off)
        args.append(month)
        args.append(day)
        args.append(hour)
        args.append(minute)
        args.append(have_flag)
        
        title_bytes = title_name.encode('utf-8')
        if len(title_bytes) > 32:
            self.logger.warning("Title name too long, truncating to 32 bytes.")
            title_bytes = title_bytes[:32]
        
        args.extend(list(title_bytes))
        
        # Pad with null bytes to 32 bytes
        args.extend([0] * (32 - len(title_bytes)))

        return await self._divoom.send_command(COMMANDS["set memorial"], args)

    async def set_memorial_gif(self, memorial_index: int, total_length: int, gif_id: int, data: list) -> bool:
        """
        Set the memorial animation for a specific memorial (0x55).
        
        Usage::
            
            # This is a low-level command. Consider using a higher-level library for GIF processing.
            # await divoom.alarm.set_memorial_gif(memorial_index=0, total_length=100, gif_id=1, data=[...])
        """
        return await self._set_animation_gif("set memorial gif", memorial_index, total_length, gif_id, data)

    async def set_alarm_listen(self, on_off: int, mode: int, volume: int) -> bool:
        """
        Enable or disable the alarm audition feature (0xa5).
        
        Usage::
            
            # Enable alarm audition
            await divoom.alarm.set_alarm_listen(1, 0, 50)
        """
        self.logger.info(
            f"Setting alarm listen: on_off={on_off}, mode={mode}, volume={volume} (0xa5)...")
        args = []
        args.append(bool_to_byte(on_off))
        args += mode.to_bytes(1, byteorder='big')
        args += volume.to_bytes(1, byteorder='big')
        return await self._divoom.send_command(COMMANDS["set alarm listen"], args)

    async def set_alarm_volume(self, volume: int) -> bool:
        """
        Set the volume level for the alarm audition feature (0xa6).
        
        Usage::
            
            await divoom.alarm.set_alarm_volume(50)
        """
        self.logger.info(f"Setting alarm volume to {volume} (0xa6)...")
        args = [volume]
        return await self._divoom.send_command(COMMANDS["set alarm vol"], args)

    async def set_alarm_volume_control(self, control: int, index: int):
        """
        Control the voice alarm feature (0x82).
        
        Usage::
            
            # This is a low-level command.
            # await divoom.alarm.set_alarm_volume_control(1, 0)
        """
        self.logger.info(
            f"Setting alarm volume control: control={control}, index={index} (0x82)...")
        args = []
        args += control.to_bytes(1, byteorder='big')
        args += index.to_bytes(1, byteorder='big')
        return await self._divoom.send_command(COMMANDS["set alarm vol ctrl"], args)
