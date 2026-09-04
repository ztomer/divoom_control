import logging
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    BOOT_GIF_OFF, BOOT_GIF_ON,
    LOW_POWER_SWITCH_OFF, LOW_POWER_SWITCH_ON,
    POVVC_GET, POVVC_SET,
    POCC_GET, POCC_SET, POCC_CHANNEL_MIN, POCC_CHANNEL_MAX
)
from divoom_lib.utils.converters import bool_to_byte

class DeviceSettings:
    """
    Handles system setting commands (power on settings, boot animation, power switch, timers)
    to keep Device class strictly <= 500 lines of code.
    """
    def __init__(self, divoom: CommandSender) -> None:
        self.communicator = divoom
        self.logger = divoom.logger

    async def set_boot_gif(self, on_off: int, total_length: int, gif_id: int, data: list) -> bool:
        """Set the boot animation (0x52)."""
        self.logger.info(f"Setting boot GIF (0x52)...")
        args = []
        args.append(bool_to_byte(on_off))
        args += total_length.to_bytes(2, byteorder='little')
        args += gif_id.to_bytes(1, byteorder='big')
        args.extend(data)
        return await self.communicator.send_command(COMMANDS["set boot gif"], args)

    async def set_low_power_switch(self, on_off: int) -> bool:
        """Set the low power mode switch (0xb2)."""
        self.logger.info(f"Setting low power switch to {on_off} (0xb2)...")
        args = [on_off]
        return await self.communicator.send_command(COMMANDS["set low power switch"], args)

    async def get_low_power_switch(self) -> int | None:
        """Obtain the low power mode switch status (0xb3)."""
        self.logger.info("Getting low power switch status (0xb3)...")
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get low power switch"])
        if response and len(response) >= 1:
            return response[0]  # 1: on, 0: off
        return None

    async def set_song_display_control(self, control: int) -> bool:
        """Set the song name display switch (0x83)."""
        self.logger.info(f"Setting song display control to {control} (0x83)...")
        args = [control]
        return await self.communicator.send_command(COMMANDS["set song dis ctrl"], args)

    def _handle_povvc_set(self, kwargs: dict) -> list | None:
        volume = kwargs.get("volume")
        if volume is not None:
            if not (0 <= volume <= 100):
                self.logger.error("Volume must be between 0 and 100.")
                return None
            return [volume]
        self.logger.error("Missing 'volume' for Set Power-on Voice Volume control.")
        return None

    def _handle_povvc_get(self, kwargs: dict) -> list | None:
        return [] # No additional data

    _povvc_handlers = {
        POVVC_SET: _handle_povvc_set,
        POVVC_GET: _handle_povvc_get,
    }

    async def set_power_on_voice_volume(self, control: int, **kwargs) -> bool:
        """Set or get the power-on voice volume (0xbb)."""
        self.logger.info(f"Setting power-on voice volume (0xbb) with control {control}...")
        args = [control]

        handler = self._povvc_handlers.get(control)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(f"Unknown control for set_power_on_voice_volume: {control}")
            return False
        return await self.communicator.send_command(COMMANDS["set poweron voice vol"], args)

    def _handle_pocc_set(self, kwargs: dict) -> list | None:
        channel_id = kwargs.get("channel_id")
        if channel_id is not None:
            if not (POCC_CHANNEL_MIN <= channel_id <= POCC_CHANNEL_MAX):
                self.logger.error(f"Channel ID must be between {POCC_CHANNEL_MIN} and {POCC_CHANNEL_MAX}.")
                return None
            return [channel_id]
        self.logger.error("Missing 'channel_id' for Set Power-on Channel control.")
        return None

    def _handle_pocc_get(self, kwargs: dict) -> list | None:
        return [] # No additional data

    _pocc_handlers = {
        POCC_SET: _handle_pocc_set,
        POCC_GET: _handle_pocc_get,
    }

    async def set_power_on_channel(self, control: int, **kwargs) -> bool:
        """Set or get the power-on channel (0x8a)."""
        self.logger.info(f"Setting power-on channel (0x8a) with control {control}...")
        args = [control]

        handler = self._pocc_handlers.get(control)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(f"Unknown control for set_power_on_channel: {control}")
            return False
        return await self.communicator.send_command(COMMANDS["set poweron channel"], args)

    async def set_auto_power_off(self, minutes: int) -> bool:
        """Set the auto power-off timer (0xab)."""
        self.logger.info(f"Setting auto power-off to {minutes} minutes (0xab)...")
        args = list(minutes.to_bytes(2, byteorder='little'))
        return await self.communicator.send_command(COMMANDS["set auto power off"], args)

    async def get_auto_power_off(self) -> int | None:
        """Get the current auto power-off timer (0xac)."""
        self.logger.info("Getting auto power-off timer (0xac)...")
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get auto power off"])
        if response and len(response) >= 2:
            return int.from_bytes(response[0:2], byteorder='little')
        return None

    async def set_sound_control(self, enable: int) -> bool:
        """Control screen switch with ambient sound (0xa7)."""
        self.logger.info(f"Setting sound control to {enable} (0xa7)...")
        args = [enable]
        return await self.communicator.send_command(COMMANDS["set sound ctrl"], args)

    async def get_sound_control(self) -> int | None:
        """Returns the sound control switch value from device (0xa8)."""
        self.logger.info("Getting sound control status (0xa8)...")
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get sound ctrl"])
        if response and len(response) >= 1:
            return response[0]  # 1: enabled, 0: disabled
        return None
