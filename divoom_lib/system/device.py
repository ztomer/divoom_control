import datetime
import logging
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    CHANNEL_ID_MIN, CHANNEL_ID_MAX,
    SD_STATUS_REMOVAL, SD_STATUS_INSERTION,
    TEMP_FORMAT_CELSIUS, TEMP_FORMAT_FAHRENHEIT,
    GDT_TEMP_FORMAT, GDT_TEMP_VALUE,
    GNTD_DISPLAY_MODES_START, GNTD_TIME_MINUTES_START,
    GDN_NAME_LENGTH, GDN_NAME_BYTES_START
)
from divoom_lib.utils.converters import bool_to_byte
from .device_settings import DeviceSettings

class Device(DeviceSettings):
    """
    Provides functionality to control the device system settings of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.device.set_brightness(50)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender) -> None:
        super().__init__(divoom)

    async def set_brightness(self, brightness: int) -> bool:
        """
        Set the screen brightness (0x74).
        """
        self.logger.info(f"Setting brightness to {brightness} (0x74)...")
        args = [brightness]
        return await self.communicator.send_command(COMMANDS["set brightness"], args)

    def _read_cache(self):
        """BLE Hardening P5: lazily attach a last-good read cache to the
        communicator so flaky ``get_*`` reads degrade to the previous value
        across calls (and survive a reconnect on the same device)."""
        cache = getattr(self.communicator, "_read_cache", None)
        if cache is None:
            from divoom_lib.ble_reads import ReadCache
            cache = ReadCache()
            try:
                self.communicator._read_cache = cache
            except Exception:
                pass
        return cache

    async def _read_brightness_once(self) -> int | None:
        command_id = COMMANDS["get light mode"]
        # Drain stale/proactive frames first: the device emits an UNSOLICITED
        # 0x46 when brightness/light state changes, so without this the query
        # reads a leftover frame and the value lags one step behind
        # (HW-confirmed on Ditoo/Pixoo/Timoo/Tivoo). send_command_and_wait_for_
        # response already drains; this manual reader must too.
        self.communicator.drain_notifications()
        self.communicator._expected_response_command = command_id
        async with self.communicator._framing_context(use_ios=self.communicator.use_ios_le_protocol, escape=False):
            await self.communicator.send_command(command_id, [])
        response_payload = await self.communicator.wait_for_response(command_id)
        if response_payload and len(response_payload) >= 7:
            try:
                return response_payload[6]
            except IndexError:
                return None
        return None

    async def get_brightness(self) -> int | None:
        """Get the screen brightness via get-light-mode (0x46), with BLE
        Hardening P5 bounded retry + last-good fallback so a single dropped reply
        doesn't blank the field. Returns the (possibly cached) value, or None
        only when never read and nothing cached."""
        self.logger.info("Getting brightness via get light mode (0x46)...")
        from divoom_lib.ble_reads import read_with_retry
        res = await read_with_retry(
            self._read_brightness_once,
            cache=self._read_cache(), cache_key="brightness")
        if res.ok and res.from_cache:
            self.logger.info("get_brightness: serving last-good cached value")
        return res.value if res.ok else None

    async def get_work_mode(self) -> int | None:
        """
        Get the current system working mode (0x06).
        """
        self.logger.info("Getting work mode (0x06)...")
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get work mode"])
        if response and len(response) >= 1:
            return response[0]
        return None

    async def set_work_mode(self, mode: int) -> bool:
        """
        Switch system working mode (0x05).
        """
        self.logger.info(f"Setting work mode to: {mode} (0x05)...")
        args = [mode]
        return await self.communicator.send_command(COMMANDS["set work mode"], args)

    async def set_channel(self, channel_id: int) -> bool:
        """
        Switch to a specific channel (0x45).
        """
        if not (CHANNEL_ID_MIN <= channel_id <= CHANNEL_ID_MAX):
            self.logger.error(f"Invalid channel ID: {channel_id}. Must be between {CHANNEL_ID_MIN} and {CHANNEL_ID_MAX}.")
            return False

        self.logger.info(f"Switching to channel: {channel_id} (0x45)...")
        args = [channel_id]
        return await self.communicator.send_command(COMMANDS["set channel light"], args)

    async def send_sd_status(self, status: int) -> bool:
        """
        Notify that there is an insertion or removal action on the TF card (0x15).
        """
        self.logger.info(f"Sending SD card status: {status} (0x15)...")
        args = [status]
        return await self.communicator.send_command(COMMANDS["send sd status"], args)

    async def get_device_temp(self) -> dict | None:
        """
        Get the device's temperature (0x59).
        """
        self.logger.info("Getting device temperature (0x59)....")
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get device temp"])
        if response and len(response) >= 2:
            temp_format = response[GDT_TEMP_FORMAT]  # 1: Fahrenheit, 0: Celsius
            temp_value = int.from_bytes(
                response[GDT_TEMP_VALUE:GDT_TEMP_VALUE + 1], byteorder='big', signed=True)
            return {"format": temp_format, "value": temp_value}
        return None

    async def send_net_temp(self, year: int, month: int, day: int, hour: int, minute: int, num: int, temp_data: list) -> bool:
        """
        Send network temperature (0x5d).
        """
        self.logger.info(f"Sending network temperature (0x5d)...")
        args = []
        args += year.to_bytes(2, byteorder='little')
        args += month.to_bytes(1, byteorder='big')
        args += day.to_bytes(1, byteorder='big')
        args += hour.to_bytes(1, byteorder='big')
        args += minute.to_bytes(1, byteorder='big')
        args += num.to_bytes(1, byteorder='big')
        for temp_val, weather_type in temp_data:
            args += temp_val.to_bytes(1, byteorder='big', signed=True)
            args += weather_type.to_bytes(1, byteorder='big')
        return await self.communicator.send_command(COMMANDS["send net temp"], args)

    async def send_net_temp_disp(self, display_modes: list, time_minutes: int) -> bool:
        """
        Send network temperature display settings (0x5e).
        """
        self.logger.info(f"Sending network temperature display (0x5e)...")
        args = []
        for mode in display_modes:
            args.append(bool_to_byte(mode))
        args += time_minutes.to_bytes(2, byteorder='little')
        return await self.communicator.send_command(COMMANDS["send net temp disp"], args)

    async def get_net_temp_disp(self) -> dict | None:
        """
        Obtain the network temperature display mode (0x73).
        """
        self.logger.info("Getting network temperature display (0x73)...")
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get net temp disp"])
        if response and len(response) >= 7:
            display_modes = [response[i] for i in range(GNTD_DISPLAY_MODES_START, GNTD_DISPLAY_MODES_START + 5)]
            time_minutes = int.from_bytes(response[GNTD_TIME_MINUTES_START:GNTD_TIME_MINUTES_START + 2], byteorder='little')
            return {"display_modes": display_modes, "time_minutes": time_minutes}
        return None

    async def set_device_name(self, name: str) -> bool:
        """
        Modify the Bluetooth device name (0x75).
        """
        self.logger.info(f"Setting device name to '{name}' (0x75)...")
        name_bytes = name.encode('utf-8')
        if len(name_bytes) > 16:
            self.logger.warning("Device name too long, truncating to 16 bytes.")
            name_bytes = name_bytes[:16]
        args = []
        args += len(name_bytes).to_bytes(1, byteorder='big')
        args.extend(list(name_bytes))
        return await self.communicator.send_command(COMMANDS["set device name"], args)

    async def _read_device_name_once(self) -> str | None:
        response = await self.communicator.send_command_and_wait_for_response(COMMANDS["get device name"])
        if response and len(response) >= 1:
            name_length = response[GDN_NAME_LENGTH]
            if len(response) >= GDN_NAME_BYTES_START + name_length:
                name_bytes = bytes(response[GDN_NAME_BYTES_START:GDN_NAME_BYTES_START + name_length])
                try:
                    return name_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    return None
        return None

    async def get_device_name(self) -> str | None:
        """The Bluetooth device name. HW finding (Ditoo/Pixoo/Timoo/Tivoo): the
        0x76 query does NOT return the full advertised name on these models — it
        replies with a 2-char suffix (e.g. "-2" for "Ditoo-light-2"). So prefer
        the authoritative advertised name the lib already holds (the name we
        connected with); fall back to the 0x76 read only when no name is known
        (connected by bare MAC). Keeps the P5 retry + last-good cache for the
        fallback path."""
        known = (getattr(self.communicator, "device_name", "") or "").strip()
        if known:
            return known
        self.logger.info("No advertised name; reading device name via 0x76...")
        from divoom_lib.ble_reads import read_with_retry
        res = await read_with_retry(
            self._read_device_name_once,
            validate=lambda v: isinstance(v, str) and len(v) > 0,
            cache=self._read_cache(), cache_key="device_name")
        if res.ok and res.from_cache:
            self.logger.info("get_device_name: serving last-good cached value")
        return res.value if res.ok else None

    async def send_current_temp(self, temp: int, weather: int) -> bool:
        """
        Send current temperature and weather (0x5f).
        """
        self.logger.info(f"Sending current temp: {temp}, weather: {weather} (0x5f)...")
        args = []
        args += temp.to_bytes(1, byteorder='big', signed=True)
        args += weather.to_bytes(1, byteorder='big')
        return await self.communicator.send_command(COMMANDS["send current temp"], args)

    async def set_temp_type(self, temp_type: int) -> bool:
        """
        Set the temperature format (0x2b).
        """
        self.logger.info(f"Setting temp type to {temp_type} (0x2b)...")
        args = [temp_type]
        return await self.communicator.send_command(COMMANDS["set temp type"], args)
