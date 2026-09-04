
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    GSPN_NAME_LENGTH_START, GSPN_NAME_BYTES_START,
    GSML_MUSIC_ID_LENGTH, GSML_NAME_LENGTH_LENGTH,
    GV_VOLUME,
    GPS_STATUS,
    GSMLTN_TOTAL_NUM_START,
    GSMI_CURRENT_TIME_START, GSMI_TOTAL_TIME_START, GSMI_MUSIC_ID_START,
    GSMI_STATUS, GSMI_VOLUME, GSMI_PLAY_MODE,
)

class Music:
    """
    Provides functionality to control music playback from an SD card on a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                volume = await divoom.music.get_volume()
                if volume is not None:
                    print(f"Current volume: {volume}")
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        """
        Initializes the Music controller.

        Args:
            divoom: The Divoom object to send commands to the device.
        """
        self._divoom = divoom
        self.logger = divoom.logger

    async def get_sd_play_name(self):
        """
        Get the name of the currently playing music from the SD card.

        Returns:
            str | None: The name of the music, or None if the command fails.
        
        Usage::
            
            play_name = await divoom.music.get_sd_play_name()
            if play_name:
                print(f"Currently playing: {play_name}")
        """
        self.logger.info("Getting SD play name (0x06)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get sd play name"])
        if response and len(response) >= 2:
            name_len = int.from_bytes(response[GSPN_NAME_LENGTH_START:GSPN_NAME_LENGTH_START + 2], byteorder='little')
            if len(response) >= GSPN_NAME_BYTES_START + name_len:
                name_bytes = bytes(response[GSPN_NAME_BYTES_START:GSPN_NAME_BYTES_START + name_len])
                return name_bytes.decode('utf-8')
        return None

    async def get_sd_music_list(self, start_id: int, end_id: int):
        """
        Get a list of music tracks from the SD card.

        Args:
            start_id (int): The starting ID of the music list.
            end_id (int): The ending ID of the music list.

        Returns:
            list: A list of dictionaries, where each dictionary represents a music track
                  and contains 'id' and 'name' keys.
        
        Usage::
            
            music_list = await divoom.music.get_sd_music_list(0, 10)
            for music in music_list:
                print(f"ID: {music['id']}, Name: {music['name']}")
        """
        self.logger.info(
            f"Getting SD music list from {start_id} to {end_id} (0x07)...")
        args = []
        args += start_id.to_bytes(2, byteorder='little')
        args += end_id.to_bytes(2, byteorder='little')
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get sd music list"], args)

        music_list = []
        if response and len(response) >= 4:
            # Response format: Music id (2 bytes) + Name len (2 bytes) + Name (variable)
            offset = 0
            while offset < len(response):
                music_id = int.from_bytes(
                    response[offset:offset+GSML_MUSIC_ID_LENGTH], byteorder='little')
                offset += GSML_MUSIC_ID_LENGTH
                name_len = int.from_bytes(
                    response[offset:offset+GSML_NAME_LENGTH_LENGTH], byteorder='little')
                offset += GSML_NAME_LENGTH_LENGTH
                if offset + name_len <= len(response):
                    name = bytes(
                        response[offset:offset+name_len]).decode('utf-8')
                    music_list.append({"id": music_id, "name": name})
                    offset += name_len
                else:
                    self.logger.warning(
                        "Incomplete music list entry in response.")
                    break
        return music_list

    async def get_volume(self):
        """
        Get the current volume level.

        Returns:
            int | None: The volume level (0-15), or None if the command fails.
        
        Usage::
            
            volume = await divoom.music.get_volume()
            if volume is not None:
                print(f"Current volume: {volume}")
        """
        self.logger.info("Getting volume (0x09)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get volume"])
        if response and len(response) >= 1:
            return response[GV_VOLUME]  # 0-15
        return None

    async def set_volume(self, volume: int) -> bool:
        """
        Set the volume level.

        Args:
            volume (int): The volume level (0-15).

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            await divoom.music.set_volume(10)
        """
        self.logger.info(f"Setting volume to {volume} (0x08)...")
        args = [volume]
        return await self._divoom.send_command(COMMANDS["set volume"], args)

    async def get_play_status(self):
        """
        Get the current playback status.

        Returns:
            int | None: 0 for pause, 1 for play, or None if the command fails.
        
        Usage::
            
            play_status = await divoom.music.get_play_status()
            if play_status is not None:
                print(f"Playback status: {'Playing' if play_status else 'Paused'}")
        """
        self.logger.info("Getting play status (0x0b)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get play status"])
        if response and len(response) >= 1:
            return response[GPS_STATUS]  # 0: Pause, 1: Play
        return None

    async def set_play_status(self, status: int) -> bool:
        """
        Set the current playback status.

        Args:
            status (int): 0 for pause, 1 for play.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # Play music
            await divoom.music.set_play_status(1)
        """
        self.logger.info(f"Setting play status to {status} (0x0a)...")
        args = [status]
        return await self._divoom.send_command(COMMANDS["set playstate"], args)

    async def set_sd_play_music_id(self, music_id: int) -> bool:
        """
        Set the currently playing song by its ID.

        Args:
            music_id (int): The ID of the music to play.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            await divoom.music.set_sd_play_music_id(1)
        """
        self.logger.info(f"Setting SD play music ID to {music_id} (0x11)...")
        args = list(music_id.to_bytes(2, byteorder='little'))
        return await self._divoom.send_command(COMMANDS["set sd play music id"], args)

    async def set_sd_last_next(self, action: int):
        """
        Control playback to the previous or next track.

        Args:
            action (int): 0 for previous track, 1 for next track.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # Play next track
            await divoom.music.set_sd_last_next(1)
        """
        self.logger.info(
            f"Setting SD last/next track action: {action} (0x12)...")
        args = [action]
        return await self._divoom.send_command(COMMANDS["set sd last next"], args)

    async def send_sd_list_over(self):
        """
        Notify the device that the playlist has been fully sent.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            await divoom.music.send_sd_list_over()
        """
        self.logger.info("Sending SD list over notification (0x14)...")
        return await self._divoom.send_command(COMMANDS["send sd list over"])

    async def get_sd_music_list_total_num(self):
        """
        Get the total number of music tracks on the SD card.

        Returns:
            int | None: The total number of tracks, or None if the command fails.
        
        Usage::
            
            total_tracks = await divoom.music.get_sd_music_list_total_num()
            if total_tracks is not None:
                print(f"Total tracks on SD card: {total_tracks}")
        """
        self.logger.info("Getting SD music list total number (0x7d)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get sd music list total num"])
        if response and len(response) >= 2:
            return int.from_bytes(response[GSMLTN_TOTAL_NUM_START:GSMLTN_TOTAL_NUM_START + 2], byteorder='little')
        return None

    async def get_sd_music_info(self):
        """
        Get information about the currently playing music on the SD card.

        Returns:
            dict | None: A dictionary containing music information, or None if the command fails.
        
        Usage::
            
            music_info = await divoom.music.get_sd_music_info()
            if music_info:
                print(f"Music info: {music_info}")
        """
        self.logger.info("Getting SD music info (0xb4)...")
        response = await self._divoom.send_command_and_wait_for_response(COMMANDS["get sd music info"])
        if response and len(response) >= 9:
            # {uint16_t cur_time; uint16_t total_time; uint16_t music_id; uint8_t status; uint8_t vol; uint8_t play_mode;}
            cur_time = int.from_bytes(response[GSMI_CURRENT_TIME_START:GSMI_CURRENT_TIME_START + 2], byteorder='little')
            total_time = int.from_bytes(response[GSMI_TOTAL_TIME_START:GSMI_TOTAL_TIME_START + 2], byteorder='little')
            music_id = int.from_bytes(response[GSMI_MUSIC_ID_START:GSMI_MUSIC_ID_START + 2], byteorder='little')
            status = response[GSMI_STATUS]
            volume = response[GSMI_VOLUME]
            play_mode = response[GSMI_PLAY_MODE]
            return {
                "current_time": cur_time,
                "total_time": total_time,
                "music_id": music_id,
                "status": status,
                "volume": volume,
                "play_mode": play_mode,
            }
        return None

    async def set_sd_music_info(self, current_time: int, music_id: int, volume: int, status: int, play_mode: int):
        """
        Set the playback information for the SD card music.

        Args:
            current_time (int): The current playback time in seconds.
            music_id (int): The ID of the music.
            volume (int): The volume level (0-15).
            status (int): The playback status (0 for pause, 1 for play).
            play_mode (int): The playback mode.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # This is a low-level command.
            # await divoom.music.set_sd_music_info(current_time=60, music_id=1, volume=10, status=1, play_mode=1)
        """
        self.logger.info(f"Setting SD music info (0xb5)...")
        args = []
        args += current_time.to_bytes(2, byteorder='little')
        args += music_id.to_bytes(2, byteorder='little')
        args += volume.to_bytes(1, byteorder='big')
        args += status.to_bytes(1, byteorder='big')
        args += play_mode.to_bytes(1, byteorder='big')
        return await self._divoom.send_command(COMMANDS["set sd music info"], args)

    async def set_sd_music_position(self, position: int) -> bool:
        """
        Set the playback position of the SD card music.

        Args:
            position (int): The playback position in seconds.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            await divoom.music.set_sd_music_position(60)
        """
        self.logger.info(f"Setting SD music position to {position}s (0xb8)...")
        args = list(position.to_bytes(2, byteorder='little'))
        return await self._divoom.send_command(COMMANDS["set sd music position"], args)

    async def set_sd_music_play_mode(self, play_mode: int):
        """
        Set the playback mode for the SD card music.

        Args:
            play_mode (int): 1 for list loop, 2 for single loop, 3 for random play.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # Set to random play
            await divoom.music.set_sd_music_play_mode(3)
        """
        self.logger.info(
            f"Setting SD music play mode to {play_mode} (0xb9)...")
        args = [play_mode]
        return await self._divoom.send_command(COMMANDS["set sd music play mode"], args)

    async def app_need_get_music_list(self):
        """
        Request to get the music playlist from the device.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            await divoom.music.app_need_get_music_list()
        """
        self.logger.info("App needs to get music list (0x47)...")
        return await self._divoom.send_command(COMMANDS["app need get music list"])
