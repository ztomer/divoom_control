"""
sound.py — Audio and sound control commands for Divoom devices.

Extracted from device.py to enforce the 500 LOC architectural ceiling.
Covers: song display, power-on voice volume, ambient sound control,
auto power-off timer, and sleep light/color.
"""

from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    SONG_DISPLAY_OFF, SONG_DISPLAY_ON, SONG_DISPLAY_QUERY,
    POVVC_GET, POVVC_SET,
    SOUND_CONTROL_DISABLE, SOUND_CONTROL_ENABLE,
)


class SoundControl:
    """
    Provides audio and ambient sound controls for a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            divoom = Divoom(mac="XX:XX:XX:XX:XX:XX")
            try:
                await divoom.connect()
                await divoom.sound.set_sound_control(1)
                await divoom.sound.set_song_display_control(SONG_DISPLAY_ON)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        asyncio.run(main())
    """

    def __init__(self, divoom: CommandSender) -> None:
        self.communicator = divoom
        self.logger = divoom.logger

    # ── Song / Music Display ──────────────────────────────────────────────────

    async def set_song_display_control(self, control: int) -> bool:
        """
        Set the song name display switch (0x83).

        Args:
            control (int): SONG_DISPLAY_OFF (0), SONG_DISPLAY_ON (1),
                           or SONG_DISPLAY_QUERY (0xFF).

        Usage::

            await divoom.sound.set_song_display_control(SONG_DISPLAY_ON)
        """
        self.logger.info(f"Setting song display control to {control} (0x83)...")
        return await self.communicator.send_command(
            COMMANDS["set song dis ctrl"], [control]
        )

    # ── Power-On Voice Volume ─────────────────────────────────────────────────

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
        return []

    _povvc_handlers = {
        POVVC_SET: _handle_povvc_set,
        POVVC_GET: _handle_povvc_get,
    }

    async def set_power_on_voice_volume(self, control: int, **kwargs) -> bool:
        """
        Set or get the power-on voice volume (0xbb).

        Args:
            control (int): POVVC_SET (1) to set, POVVC_GET (0) to get.
            volume (int): 0-100 (only when control=POVVC_SET).

        Usage::

            await divoom.sound.set_power_on_voice_volume(POVVC_SET, volume=50)
        """
        self.logger.info(
            f"Setting power-on voice volume (0xbb) with control {control}...")
        args = [control]
        handler = self._povvc_handlers.get(control)
        if handler:
            extra = handler(self, kwargs)
            if extra is not None:
                args.extend(extra)
            else:
                return False
        else:
            self.logger.warning(
                f"Unknown control for set_power_on_voice_volume: {control}")
            return False
        return await self.communicator.send_command(
            COMMANDS["set poweron voice vol"], args
        )

    # ── Ambient Sound Control ─────────────────────────────────────────────────

    async def set_sound_control(self, enable: int) -> bool:
        """
        Control screen switch with ambient sound (0xa7).

        Args:
            enable (int): SOUND_CONTROL_ENABLE (1) or SOUND_CONTROL_DISABLE (0).

        Usage::

            await divoom.sound.set_sound_control(SOUND_CONTROL_ENABLE)
        """
        self.logger.info(f"Setting sound control to {enable} (0xa7)...")
        return await self.communicator.send_command(
            COMMANDS["set sound ctrl"], [enable]
        )

    async def get_sound_control(self) -> int | None:
        """
        Returns the sound control switch value from device (0xa8).

        Returns:
            int | None: SOUND_CONTROL_ENABLE (1) or SOUND_CONTROL_DISABLE (0),
                        or None if the command fails.

        Usage::

            status = await divoom.sound.get_sound_control()
        """
        self.logger.info("Getting sound control status (0xa8)...")
        response = await self.communicator.send_command_and_wait_for_response(
            COMMANDS["get sound ctrl"]
        )
        if response and len(response) >= 1:
            return response[0]
        return None

    # ── Auto Power-Off ────────────────────────────────────────────────────────

    async def set_auto_power_off(self, minutes: int) -> bool:
        """
        Set the auto power-off timer (0xab).

        Args:
            minutes (int): Duration in minutes (0 = disabled).

        Usage::

            await divoom.sound.set_auto_power_off(30)
        """
        self.logger.info(
            f"Setting auto power-off to {minutes} minutes (0xab)...")
        args = list(minutes.to_bytes(2, byteorder='little'))
        return await self.communicator.send_command(
            COMMANDS["set auto power off"], args
        )

    async def get_auto_power_off(self) -> int | None:
        """
        Get the current auto power-off timer (0xac).

        Returns:
            int | None: Time in minutes, or None if the command fails.

        Usage::

            minutes = await divoom.sound.get_auto_power_off()
        """
        self.logger.info("Getting auto power-off timer (0xac)...")
        response = await self.communicator.send_command_and_wait_for_response(
            COMMANDS["get auto power off"]
        )
        if response and len(response) >= 2:
            return int.from_bytes(response[0:2], byteorder='little')
        return None

    # ── Sleep Light/Color ─────────────────────────────────────────────────────

    async def set_sleep_color(self, r: int, g: int, b: int) -> bool:
        """
        Set the sleep mode LED color (BLE command 0xad).

        Args:
            r, g, b (int): RGB color components (0-255).

        Usage::

            await divoom.sound.set_sleep_color(0, 0, 32)
        """
        self.logger.info(f"Setting sleep color RGB({r},{g},{b}) (0xad)...")
        return await self.communicator.send_command(
            COMMANDS.get("set sleep color", 0xad), [r, g, b]
        )
