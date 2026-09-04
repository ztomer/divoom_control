
import json

from divoom_lib.sender_protocol import CommandSender

# SPP_JSON: a general-purpose JSON-over-BLE/SPP channel the Divoom app uses
# for a handful of commands (AidSleep, Vision/Add, Lyric config, …) instead
# of the app's usual binary-opcode protocol. Confirmed via the decompiled
# APK (bluetooth/q.java `B()` -> bluetooth/s.java `c(SppProc$CMD_TYPE.
# SPP_JSON, jsonBytes)`) to use the EXACT SAME frame this project's
# framing.py already implements — start byte 0x01, 2-byte LE length,
# command id, payload, 2-byte LE checksum, end byte 0x02 (escaped the same
# way for OldMode devices) — just with command id 1 (SPP_JSON) instead of a
# named binary opcode, and a JSON string as the payload instead of packed
# bytes. So no new wire-protocol code is needed: `send_command(1, ...)`
# already goes through the identical framing path as every other command.
#
# STILL OPEN: the wire ENCODING is confirmed from source (byte-for-byte
# match against this project's own framing.py), but the semantic behavior
# (does the device actually start playback / add the track) has not been
# confirmed on real hardware yet. Verify with a real device before
# depending on this for anything user-facing.
SPP_JSON_COMMAND_ID = 1


class AidSleep:
    """
    Play/manage tracks from Divoom's cloud-hosted AidSleep sound library
    (natural sounds / white noise / music) — distinct from the device's
    built-in sleep-scene timer (see ``divoom_lib.scheduling.sleep.Sleep``).

    Browsing the library (``AidSleep/GetAllList``/``GetMyList``) is a plain
    cloud HTTP call — see ``divoom_lib.cloud.CloudClient.get_aid_sleep_list``.
    Once a ``SleepId`` is known, playback needs no cloud auth: these methods
    send a small JSON command directly to the device over BLE/SPP.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            divoom = Divoom(mac="XX:XX:XX:XX:XX:XX")
            try:
                await divoom.connect()
                await divoom.aid_sleep.play(sleep_id=123, sleep_type=1)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """

    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    async def _send_json_command(self, command: str, fields: dict) -> bool:
        body = {"Command": command, **fields}
        payload = json.dumps(body).encode("utf-8")
        self.logger.info(f"Sending SPP_JSON command {command}: {fields}")
        return await self._divoom.send_command(SPP_JSON_COMMAND_ID, list(payload))

    async def play(self, sleep_id: int, sleep_type: int) -> bool:
        """
        Start playback of an AidSleep track on the device.

        Args:
            sleep_id: The track's ``SleepId`` (from
                ``CloudClient.get_aid_sleep_list``).
            sleep_type: 0=Natural Sound, 1=White Noise, 2=Music.

        Usage::

            await divoom.aid_sleep.play(sleep_id=123, sleep_type=1)
        """
        return await self._send_json_command(
            "AidSleep/Play", {"SleepId": sleep_id, "Type": sleep_type})

    async def exit(self) -> bool:
        """Stop AidSleep playback and exit the mode."""
        return await self._send_json_command("AidSleep/Exit", {})

    async def add(self, sleep_id: int, sleep_type: int, name: str,
                   file_id: str, language: str = "", audio_type: int = 0,
                   video_type: int = 0) -> bool:
        """Add a track to the device's on-device AidSleep library."""
        return await self._send_json_command("AidSleep/Add", {
            "SleepId": sleep_id, "Type": sleep_type, "Name": name,
            "FileId": file_id, "Language": language,
            "AudioType": audio_type, "VideoType": video_type,
        })

    async def delete(self, sleep_id: int, sleep_type: int) -> bool:
        """Remove a track from the device's on-device AidSleep library."""
        return await self._send_json_command(
            "AidSleep/Delete", {"SleepId": sleep_id, "Type": sleep_type})
