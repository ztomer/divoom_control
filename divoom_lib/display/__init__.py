# divoom_lib/display/__init__.py
import asyncio
import time

from .light import Light
from .drawing import Drawing
from .animation import Animation
from .text import Text
from .display_animation import DisplayAnimation
from .display_text import DisplayText

from ..utils.image_processing import process_image
from ..utils.divoom_image_encode import (
    encode_animation,
)
from .. import models as constants
from ..utils.converters import to_int_if_str, bool_to_byte
from ..sender_protocol import CommandSender

class Display:
    def __init__(self, communicator: CommandSender) -> None:
        self.communicator = communicator
        self.logger = communicator.logger

    async def set_clock_rich(self, style: int = 0, twentyfour: bool = True, humidity: bool = False, weather: bool = False, date: bool = False, color: str = "#ffffff") -> bool:
        """Set CLOCK channel using APK C2() 10-byte format (0x45).

        Wire: 0x45 [0x00, time_type, style, 0x01, humidity, weather, date, R, G, B]
        Different overlay positions than show_clock() — APK canonical.
        """
        rgb = self.communicator.convert_color(color)
        payload = [
            0x00, int(twentyfour), style & 0xFF, 0x01,
            int(humidity), int(weather), int(date),
            rgb[0], rgb[1], rgb[2],
        ]
        return await self.communicator.send_command("set light mode", payload)

    async def show_clock(self, clock: int = 0, twentyfour: bool = True, humidity: bool = False, weather: bool = False, date: bool = False, color: str | None = None, hot: bool | None = None) -> bool:
        """Show clock on the Divoom device in the color.

        Wire frame is the APK ``C2()`` canonical 10-byte env-mode layout
        (``CmdManager.java:316``, verified R60)::
            [0x00, time_type, style, 0x01, humidity, weather, date, R, G, B]
        The device's 0x45 clock env frame reads positions 4/5/6 as
        humidity/weather/date — so those are the overlay fields, not
        weather/temp/calendar.
        """
        clock = to_int_if_str(clock)
        if self.communicator.lan:
            await self.communicator.lan.set_clock(clock)
            return True

        if hot:
            # 0x26 "set hot" needs its 1-byte enable flag (canonical frame
            # 0x26 0x01); an empty payload made the device read a garbage/OOB
            # enable byte → hot mode didn't reliably turn on. Matches Control.set_hot.
            return await self.communicator.send_command("set hot", [constants.BOOLEAN_TRUE])

        args = [constants.BOOLEAN_FALSE]
        args += [bool_to_byte(twentyfour)]
        if clock >= 0 and clock <= 15:
            args += clock.to_bytes(1, byteorder='big')  # clock mode/style
            args += [constants.BOOLEAN_TRUE]  # clock activated
        else:
            args += [constants.BOOLEAN_FALSE, constants.BOOLEAN_FALSE]  # clock mode/style = 0 and clock deactivated
        # APK C2() canonical overlay order: humidity, weather, date (positions 4/5/6).
        args += [bool_to_byte(humidity)]
        args += [bool_to_byte(weather)]
        args += [bool_to_byte(date)]

        # Always append color payload to guarantee full 10-byte environmental packet format.
        # This prevents the clock face channel from getting stuck or failing to switch styles.
        color_val = color or "#ffffff"
        rgb = self.communicator.convert_color(color_val)
        args += [rgb[0], rgb[1], rgb[2]]
        return await self.communicator.send_command("set light mode", args)

    async def _set_work_mode(self, mode: int, sub_command_args: list | None = None) -> bool:
        """Helper method to set the work mode."""
        args = [mode]
        result = await self.communicator.send_command("set work mode", args)
        if sub_command_args:
            result = await self.communicator.send_command("set design", sub_command_args)
        return result

    async def show_design(self, number: int | None = None) -> bool:
        """Show custom art / design channel on the Divoom device"""
        if self.communicator.lan:
            await self.communicator.lan.set_channel(3)
            return True
        # Under protocol.md: Animation channel is command 0x45, payload [0x05]
        # Pad payload to 10 bytes to ensure the device switches channels successfully
        args = [0x05] + [0x00] * 9
        return await self.communicator.send_command("set light mode", args)

    async def show_scoreboard(self) -> bool:
        """Switch the device to the Scoreboard tool channel (0x06).

        The scoreboard is a tool (0x72 set tool, TOOL_TYPE_SCORE), not a
        display channel in the strict sense — but the device surfaces it
        in the channel-switch UI as channel id 0x06, so we route it through
        `set light mode` (0x45) with the same 10-byte padding pattern as
        show_clock / show_visualization / show_effects / show_design.

        After this call, the device is parked on the scoreboard channel
        and the actual scores are pushed via the 0x72 set-tool command
        (`divoom.scoreboard.set_scoreboard`).
        """
        if self.communicator.lan:
            # LAN devices use a generic set_channel API; 0x06 is the
            # scoreboard channel id per the LAN protocol map.
            try:
                await self.communicator.lan.set_channel(6)
            except Exception as e:
                self.logger.warning(f"LAN set_channel(6) failed: {e}")
                return False
            return True
        # Under protocol.md: Scoreboard channel is command 0x45, payload [0x06]
        # Pad payload to 10 bytes to ensure the device switches channels successfully
        args = [0x06] + [0x00] * 9
        return await self.communicator.send_command("set light mode", args)

    async def show_effects(self, number: int) -> bool:
        """Show VJ effects on the Divoom device"""
        if self.communicator.lan:
            self.logger.warning("VJ effects are not supported on Wi-Fi (LAN) devices.")
            return False
        # VJ effects are 1-indexed (1-16) on BLE hardware
        # Pad payload to 10 bytes to ensure the device switches channels successfully
        args = [0x03, int(number) + 1] + [0x00] * 8
        return await self.communicator.send_command("set light mode", args)

    async def show_image(self, file: str, time: int | None = None) -> bool:
        """Show image or animation on the Divoom device.

        The device expects a palette-quantized + bit-packed protocol,
        NOT raw RGB. We use `divoom_image_encode` to produce the
        on-wire bytes.

        Live device verification (Timoo, June 2026): the device only
        renders the image when sent as an animation (0x49), not as a
        static image (0x44). We therefore route ALL frames through
        `encode_animation`, which produces a single 0x49 packet for
        1-frame inputs.

        Round 4: routes multi-frame animations through the 0x8B
        3-phase protocol (per futpib reference), since the 0x49
        chunked approach is ACK'd by Timoo but doesn't cycle. For
        single-frame static, keeps the 0x49 path that works.

        Round 4: auto-detects 32×32 (Pixoo Max, Tivoo Max w/ extended
        LED) from `DivoomConfig.screensize` and uses the 32×32 encoder
        which emits the two required pre-frames + palette flag 0x03 +
        2-byte color count.
        """
        await self.show_design()
        screensize = self._get_screensize()
        # Resize to the device pixel grid BEFORE encoding. Without this, a
        # full-resolution source (e.g. a gallery gif) overflows the 2-byte
        # per-frame length field → "int too big to convert" (R11 item 1b).
        frames, frames_count, _w, _h = process_image(
            file, time=time, size=screensize
        )
        if frames_count >= 1:
            # Route ALL pushes (single still AND multi-frame) through the
            # 0x8B 3-phase protocol. This matches the futpib reference, whose
            # `send_image` pushes a still PNG through the *same* animation path
            # (`create_network_packets_from`) as a GIF — there is no separate
            # single-frame command. The earlier code special-cased 1-frame into
            # 0x49, which is why cover art (a single frame) did not render
            # (R11 item 2a). Uses the proven streamer (chunk-index offset ids,
            # 256-byte chunks, write-with-response + pacing). Falls back to 0x49.
            #
            # R35d: removed `screensize != 32` guard. The APK uses the same
            # AA-format frame encoding for ALL sizes; the hass-divoom 32×32
            # pre-frames and RR=0x03 are NOT in the APK. 0x8B now works for
            # 32×32 devices too.
            from .animation_8b import _build_animation_blob
            blob = _build_animation_blob(frames)
            anim = getattr(self.communicator, "animation", None)
            if blob and anim is not None:
                self.logger.info(
                    f"show_image: streaming {frames_count} frame(s) via 0x8B "
                    f"3-phase ({len(blob)} bytes)"
                )
                if await anim.stream_animation_8b(blob):
                    return True
                self.logger.warning(
                    "show_image: 0x8B stream failed, falling back to 0x49"
                )

        # Fallback path: 0x49 chunked animation.
        blobs = encode_animation(frames)
        # Honest bool: start False so an empty blob list (nothing sent) reports
        # failure rather than returning None (the annotated return type is bool).
        result: bool = False
        for packet in blobs:
            result = await self.communicator.send_command(
                "set animation frame", list(packet)
            )
            if not result:
                return False
        return bool(result)

    def _get_screensize(self) -> int:
        """Read the active device's screensize from the config.

        Defaults to 16. 32 = Pixoo Max / Tivoo Max w/ extended LED.
        See `divoom_lib/models/commands.py` for the channel command ids.
        """
        cfg = getattr(self.communicator, "cfg", None)
        if cfg is not None and hasattr(cfg, "screensize"):
            return int(getattr(cfg, "screensize") or 16)
        return 16

    async def display_image(
        self, file: str, time: int | None = None,
        wait_for_display: bool = False, poll_timeout_s: float = 2.0,
    ) -> bool:
        """High-level wrapper for showing a user-provided image on the device.

        Thin alias for `show_image` that:
          1. Switches the device to the design channel (already done by
             `show_image` -> `show_design`, which sends `0x45 0x05 ...`).
          2. Encodes the file and pushes the bytes (`0x44` set image, or
             `0x49` set animation frame for multi-frame files).
          3. Optionally polls `get work mode` after the push to verify
             the device has actually rendered the image.

        The channel switch + push dance is the right primitive for
        user-pushed content (cover art, custom art, stocks, sysmon,
        notifications, weather, calendar). This wrapper exists so the
        GUI's three push call sites (`_push_frame` for cover art /
        stocks / sysmon) and any future widget dev can call one
        function instead of duplicating the dance.

        Args:
            file: path to the image file. Any format PIL supports.
            time: optional animation frame time (ms). If the file is
                multi-frame, this controls the per-frame delay.
            wait_for_display: if True, poll `get work mode` after the
                push to confirm the device has rendered. Useful for
                tests + slow BLE hosts. Adds one or more BLE
                round-trips.
            poll_timeout_s: how long to wait for the device to render
                when `wait_for_display=True`. Default 2s.

        Returns:
            True on a successful push. If `wait_for_display=True`, the
            return value reflects whether the device actually rendered
            within the timeout (False if the device didn't switch to
            the design channel, which would indicate a stuck
            connection or a device-side error).
        """
        pushed = await self.show_image(file, time=time)
        if not pushed:
            return False
        if not wait_for_display:
            return True
        # Use the running event loop's monotonic clock (NOT time.monotonic()
        # — the `time` parameter above shadows the stdlib `time` module).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + poll_timeout_s
        target_mode = 0x05  # design / SOUND_USER channel
        last_mode: int | None = None
        while loop.time() < deadline:
            try:
                mode = await self._get_work_mode()
            except Exception as e:
                self.logger.warning(f"display_image: get_work_mode failed: {e}")
                await asyncio.sleep(0.2)
                continue
            last_mode = mode
            if mode == target_mode:
                return True
            await asyncio.sleep(0.2)
        self.logger.warning(
            f"display_image: device did not report work mode 0x{target_mode:02x} "
            f"within {poll_timeout_s}s of push (last mode: "
            f"{f'0x{last_mode:02x}' if last_mode is not None else 'unknown'})"
        )
        return False

    async def _get_work_mode(self) -> int | None:
        """Read the device's current work mode (0x13).

        Returns the work mode byte, or None if the device didn't respond.
        Used by `display_image` for the `wait_for_display` verification.
        """
        if self.communicator.lan:
            return await self.communicator.lan.get_work_mode()
        try:
            response = await self.communicator.send_command_and_wait_for_response(
                constants.COMMANDS["get work mode"], timeout=1.5
            )
        except Exception as e:
            self.logger.debug(f"_get_work_mode: send failed: {e}")
            return None
        if response and len(response) >= 1:
            return response[0]
        return None

    async def show_light(self, color: str, brightness: int | None = None, power: bool | None = None, lightning_type: int | None = None) -> bool:
        """Show light on the Divoom device in the color.

        ``lightning_type`` selects the ambient effect (0 Plain, 1 Love,
        2 Plants, 3 Sleeping, 4 No-Mosquito). BLE/SPP carry it in byte 5 of the
        0x45 lighting packet.

        R67/C1: on LAN this used to drop ``lightning_type`` on the floor and
        return True, so every effect silently rendered as Plain Colour and the
        UI reported success. Divoom's HTTP API has no field for it —
        ``Channel/SetAmbientLight`` accepts only Brightness/Color/Power — so the
        effect is genuinely unreachable over Wi-Fi. That is a real limitation,
        and the honest response is to refuse it rather than fake it, matching
        how ``show_effects`` already handles VJ-on-LAN.
        """
        if power is None:
            power = True
        if brightness is None:
            brightness = 100
        brightness = to_int_if_str(brightness)

        rgb_color = self.communicator.convert_color(color)
        effect = to_int_if_str(lightning_type) if lightning_type is not None \
            else constants.LIGHTNING_TYPE_PLAIN_COLOR

        if self.communicator.lan:
            if effect != constants.LIGHTNING_TYPE_PLAIN_COLOR:
                self.logger.warning(
                    "Ambient effect %s is not supported on Wi-Fi (LAN) devices — "
                    "Channel/SetAmbientLight has no effect field. Only Plain "
                    "Colour is reachable over LAN.", effect)
                return False
            await self.communicator.lan.set_ambient_light(
                brightness, rgb_color[0], rgb_color[1], rgb_color[2], 1 if power else 0
            )
            return True

        # Wire: [channel, R, G, B, brightness, lighting_type, power, 0, 0, 0].
        # Mirrors divoomd/src/packets.rs::LightPacket — keep the two in step.
        args = [
            constants.LIGHTNING_CHANNEL_NUMBER,
            rgb_color[0], rgb_color[1], rgb_color[2],
            brightness,
            effect,
            bool_to_byte(power),
            constants.FIXED_STRING_BYTE, constants.FIXED_STRING_BYTE, constants.FIXED_STRING_BYTE
        ]
        return await self.communicator.send_command("set channel light", args)

    async def show_visualization(self, number: int | None = None) -> bool:
        """Show visualization on the Divoom device"""
        if self.communicator.lan:
            await self.communicator.lan.set_channel(2)
            return True
        if number is None:
            return False
        number = to_int_if_str(number)
        # Under protocol.md: Visualization is command 0x45, payload [0x04, number]
        # Pad payload to 10 bytes to ensure the device switches channels successfully
        args = [0x04, number] + [0x00] * 8
        return await self.communicator.send_command("set light mode", args)

    async def switch_channel(self, channel: str) -> bool:
        """Switches display active channel mode (Clock, Visualizer, VJ, Design, Scoreboard)."""
        channel_lower = channel.lower()
        if self.communicator.lan:
            if channel_lower == "vj":
                self.logger.warning("VJ effects are not supported on Wi-Fi (LAN) devices.")
                return False
            mapping = {"clock": 0, "visualizer": 2, "design": 3, "scoreboard": 6}
            if channel_lower not in mapping:
                return False
            val = mapping[channel_lower]
            await self.communicator.lan.set_channel(val)
            return True

        if channel_lower == "clock":
            return await self.show_clock()
        elif channel_lower == "visualizer":
            return await self.show_visualization(number=0)
        elif channel_lower == "vj":
            return await self.show_effects(number=0)
        elif channel_lower == "design":
            return await self.show_design()
        elif channel_lower == "scoreboard":
            return await self.show_scoreboard()
        return False

__all__ = ["Display", "Light", "Drawing", "Animation", "Text"]
