"""
lan_transport.py — Local Wi-Fi HTTP transport for WiFi-capable Divoom devices.

Transport:  LAN — 100 % local, no internet, no Divoom account required.

Reverse-engineered from com.divoom.Divoom_3.8.22 APK (OkHttpUtils.java):

    String url = "http://" + deviceIp + ":9000/divoom_api";
    POST body: JSON with "Command", "LocalToken", and command-specific fields.

Supported devices (confirmed WiFi-capable):
  - Pixoo 64
  - Pixoo Max
  - Pixoo 4
  - Timebox Evo (with WiFi firmware)

The LocalToken is exchanged during device WiFi pairing. Defaults to 0 for
devices that do not enforce it (most consumer units).
"""

import json
import asyncio
import logging
from typing import Any

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

from divoom_lib.transport import Transport, via
from divoom_lib.lan_transport_photo import LanPhotoMixin
from divoom_lib.lan_transport_extras import LanExtrasMixin


class LanTransportError(Exception):
    """Raised when the LAN device HTTP API returns an error or is unreachable."""


def _validate_lan_response(status: int, text: str, command: str) -> dict:
    """Parse + validate a Divoom local-API HTTP response.

    The device returns HTTP 200 with a JSON body ``{"error_code": N, ...}`` where
    ``error_code == 0`` means success. A REJECTED command (bad LocalToken,
    out-of-range value, command unsupported on this model) comes back 200 with a
    NON-ZERO error_code — the old code returned that dict verbatim, so the daemon
    reported a silent success (ACK != success). Now a non-200 status, non-JSON
    body, or non-zero error_code all raise LanTransportError so the failure is
    honest. A missing error_code is tolerated (treated as success)."""
    try:
        result = json.loads(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise LanTransportError(
            f"device returned non-JSON for {command}: {text[:120]!r}") from e
    if status != 200:
        raise LanTransportError(f"device returned HTTP {status} for {command}")
    err = result.get("error_code") if isinstance(result, dict) else None
    if err not in (None, 0):
        raise LanTransportError(f"device rejected {command}: error_code={err}")
    return result


class LanTransport(LanPhotoMixin, LanExtrasMixin):
    """
    Sends commands to a WiFi-enabled Divoom device via its local HTTP API.

    Transport:  LAN — POST http://{device_ip}:9000/divoom_api

    No internet connection required. No Divoom account required.
    Faster than BLE for bulk/frequent commands.

    Usage::

        from divoom_lib.lan_transport import LanTransport

        async def main():
            lan = LanTransport(device_ip="192.168.1.42")
            ok = await lan.probe()          # check reachability
            if ok:
                await lan.set_brightness(80)
                await lan.set_channel(2)
    """

    PORT = 9000
    PATH = "/divoom_api"
    TIMEOUT = 5.0  # seconds

    def __init__(
        self,
        device_ip: str,
        local_token: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.device_ip = device_ip
        self.local_token = local_token
        self.logger = logger or logging.getLogger("divoom.lan")
        self._base_url = f"http://{device_ip}:{self.PORT}{self.PATH}"

    # ── Low-level POST ────────────────────────────────────────────────────────

    async def post(self, command: str, extra: dict[str, Any] | None = None) -> dict:
        """
        POST a JSON command to the device's local HTTP API.

        Transport:  LAN

        Args:
            command: The Divoom command string (e.g. "Channel/SetIndex").
            extra:   Additional JSON fields merged into the request body.

        Returns:
            Parsed JSON response dict from the device.

        Raises:
            LanTransportError: If the device is unreachable or returns an error.
        """
        if not _AIOHTTP_AVAILABLE:
            raise LanTransportError(
                "aiohttp is required for LAN transport. "
                "Install it with: pip install aiohttp"
            )

        body: dict[str, Any] = {
            "Command": command,
            "LocalToken": self.local_token,
        }
        if extra:
            body.update(extra)

        self.logger.debug(f"[LAN ] POST {self._base_url} → {command} {extra or ''}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._base_url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT),
                ) as resp:
                    status = resp.status
                    text = await resp.text()
        except aiohttp.ClientConnectorError as e:
            raise LanTransportError(
                f"Cannot reach device at {self.device_ip}:{self.PORT}. "
                f"Check that the device is on the same Wi-Fi network. ({e})"
            ) from e
        except asyncio.TimeoutError:
            raise LanTransportError(
                f"Device at {self.device_ip} did not respond within {self.TIMEOUT}s."
            )
        except Exception as e:
            raise LanTransportError(f"LAN request failed: {e}") from e

        # Validate OUTSIDE the network try so an honest-failure raise here isn't
        # re-wrapped as "LAN request failed" by the broad except above.
        result = _validate_lan_response(status, text, command)
        self.logger.debug(f"[LAN ] ← {result}")
        return result

    # ── Connection probe ──────────────────────────────────────────────────────

    async def probe(self) -> bool:
        """
        Check whether the device is reachable on the LAN.

        Transport:  LAN

        Returns:
            True if the device responded, False otherwise.

        Usage::

            if await lan.probe():
                print("Device reachable on LAN")
        """
        try:
            # Channel/GetIndex is a safe, read-only probe command
            result = await self.post("Channel/GetIndex")
            reachable = isinstance(result, dict)
            if reachable:
                self.logger.info(
                    f"[LAN ] Device at {self.device_ip} is reachable."
                )
            return reachable
        except LanTransportError:
            return False

    # ── Channel & Display ─────────────────────────────────────────────────────

    @via(Transport.LAN)
    async def set_channel(self, index: int) -> dict:
        """
        Switch the active channel.

        Transport:  LAN

        Args:
            index: Channel index (0=Clock, 1=Cloud, 2=Visualizer, 3=Custom,
                   4=Black screen).

        Usage::

            await lan.set_channel(0)   # Switch to clock
        """
        return await self.post("Channel/SetIndex", {"SelectIndex": index})

    @via(Transport.LAN)
    async def get_channel(self) -> dict:
        """
        Get the current active channel index.

        Transport:  LAN

        Usage::

            info = await lan.get_channel()
        """
        return await self.post("Channel/GetIndex")

    @via(Transport.LAN)
    async def set_brightness(self, brightness: int) -> dict:
        """
        Set screen brightness.

        Transport:  LAN

        Args:
            brightness: 0–100.

        Usage::

            await lan.set_brightness(80)
        """
        return await self.post("Channel/SetBrightness", {"Brightness": brightness})

    @via(Transport.LAN)
    async def set_clock(self, clock_id: int) -> dict:
        """
        Select a clock face by ID.

        Transport:  LAN

        Args:
            clock_id: The clock face ID (from the Divoom clock store).

        Usage::

            await lan.set_clock(182)
        """
        return await self.post("Channel/SetClockSelectId", {"ClockId": clock_id})

    @via(Transport.LAN)
    async def send_playlist(self, play_id: int) -> dict:
        """
        Push a cloud-hosted playlist's contents to this device.

        Transport:  LAN

        Confirmed live caller in the decompiled Divoom app
        (``PlayListModel.b()``), which POSTs ``{"PlayId": play_id}`` to
        ``Playlist/SendDevice`` — listed in the app's own
        ``HttpCommand.DeviceAndServerCmd`` array, meaning the app treats
        it as a combined device+server command rather than a pure cloud
        call, same as ``Channel/SetClockSelectId``. See
        ``divoom_lib.cloud.CloudClient.get_my_playlists`` /
        ``get_playlist_images`` to find a ``play_id``.

        Args:
            play_id: The playlist's ``PlayId`` (from
                ``CloudClient.get_my_playlists``).

        Usage::

            await lan.send_playlist(42)
        """
        return await self.post("Playlist/SendDevice", {"PlayId": play_id})

    @via(Transport.LAN)
    async def on_off_screen(self, on_off: int) -> dict:
        """
        Turn the screen on (1) or off (0).

        Transport:  LAN

        Usage::

            await lan.on_off_screen(0)   # screen off
            await lan.on_off_screen(1)   # screen on
        """
        return await self.post("Channel/OnOffScreen", {"OnOff": on_off})

    # ── Ambient Light & RGB ───────────────────────────────────────────────────

    @via(Transport.LAN)
    async def set_ambient_light(
        self, brightness: int, r: int, g: int, b: int, power: int = 1
    ) -> dict:
        """
        Configure the ambient light / LED ring.

        Transport:  LAN

        Args:
            brightness: 0–100.
            r, g, b:    RGB colour components (0–255).
            power:      1 = on, 0 = off.

        Usage::

            await lan.set_ambient_light(80, 255, 128, 0)
        """
        return await self.post("Channel/SetAmbientLight", {
            "Brightness": brightness,
            "Color": f"#{r:02X}{g:02X}{b:02X}",
            "Power": power,
        })

    @via(Transport.LAN)
    async def set_rgb_info(self, mode: int, speed: int, r: int, g: int, b: int) -> dict:
        """
        Configure the RGB LED strip.

        Transport:  LAN

        Usage::

            await lan.set_rgb_info(mode=1, speed=50, r=255, g=0, b=128)
        """
        return await self.post("Channel/SetRGBInfo", {
            "RgbMode": mode,
            "RgbSpeed": speed,
            "RgbColor": f"#{r:02X}{g:02X}{b:02X}",
        })

    # ── Tools ─────────────────────────────────────────────────────────────────

    @via(Transport.LAN)
    async def set_timer(self, minute: int, second: int, status: int) -> dict:
        """
        Set a countdown timer.

        Transport:  LAN

        Args:
            minute:  Minutes component.
            second:  Seconds component.
            status:  1 = start, 0 = stop.

        Usage::

            await lan.set_timer(5, 0, 1)   # 5-minute countdown, start
        """
        return await self.post("Tools/SetTimer", {
            "Minute": minute,
            "Second": second,
            "Status": status,
        })

    @via(Transport.LAN)
    async def set_scoreboard(self, blue: int, red: int) -> dict:
        """
        Update the scoreboard.

        Transport:  LAN

        Usage::

            await lan.set_scoreboard(blue=3, red=1)
        """
        return await self.post("Tools/SetScoreBoard", {
            "BlueScore": blue,
            "RedScore": red,
        })

    @via(Transport.LAN)
    async def set_stopwatch(self, status: int) -> dict:
        """
        Control the stopwatch.

        Transport:  LAN

        Args:
            status: 1 = start, 0 = stop, 2 = reset.

        Usage::

            await lan.set_stopwatch(1)   # start
        """
        return await self.post("Tools/SetStopWatch", {"Status": status})

    @via(Transport.LAN)
    async def set_noise_status(self, noise_status: int) -> dict:
        """
        Enable or disable the noise meter.

        Transport:  LAN

        Args:
            noise_status: 1 = enabled, 0 = disabled.

        Usage::

            await lan.set_noise_status(1)
        """
        return await self.post("Tools/SetNoiseStatus", {"NoiseStatus": noise_status})

    # ── Read-back getters (LAN counterparts of the Set commands above / BLE
    # equivalents in device_call/tools.rs) — same feature, reachable over
    # LAN when the device is on WiFi. Bare GET requests, no body.

    @via(Transport.LAN)
    async def get_eq_position(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_eq_position()"""
        return await self.post("Channel/GetEqPosition")

    @via(Transport.LAN)
    async def get_rgb_info(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_rgb_info()"""
        return await self.post("Channel/GetRGBInfo")

    @via(Transport.LAN)
    async def get_ambient_light(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_ambient_light()"""
        return await self.post("Channel/GetAmbientLight")

    @via(Transport.LAN)
    async def get_on_off_screen(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_on_off_screen()"""
        return await self.post("Channel/GetOnOffScreen")

    @via(Transport.LAN)
    async def get_noise_status(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_noise_status()"""
        return await self.post("Tools/GetNoiseStatus")

    @via(Transport.LAN)
    async def get_timer(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_timer()"""
        return await self.post("Tools/GetTimer")

    @via(Transport.LAN)
    async def get_scoreboard(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_scoreboard()"""
        return await self.post("Tools/GetScoreBoard")

    @via(Transport.LAN)
    async def get_stopwatch(self) -> dict:
        """Transport: LAN. Usage:: await lan.get_stopwatch()"""
        return await self.post("Tools/GetStopWatch")

    # ── Status / Info ─────────────────────────────────────────────────────────

    @property
    def transport(self) -> Transport:
        """Always returns Transport.LAN."""
        return Transport.LAN

    def __repr__(self) -> str:
        return (
            f"LanTransport(device_ip={self.device_ip!r}, "
            f"local_token={self.local_token}, "
            f"transport={self.transport.badge} {self.transport.label})"
        )
