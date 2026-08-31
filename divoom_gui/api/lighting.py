"""LightingApi — light/clock/channel/vj/visualization/text (REVIEW §1.2).

Extracts the display/lighting command surface.
"""
from __future__ import annotations

import logging
from divoom_gui.api import ApiBase
from divoom_gui.widget_frames import WidgetFrameMixin

logger = logging.getLogger("divoom_gui.api.lighting")


class LightingApi(ApiBase, WidgetFrameMixin):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    def _stop_live_widgets(self) -> None:
        """A static-display takeover (channel / clock / VJ / visualizer / solid
        light) is mutually exclusive with a streaming live widget. Stop the
        active device's live jobs first, or the widget's next tick re-pushes its
        frame and clobbers the switch (HW-confirmed). Best-effort."""
        try:
            client = self._client
            if client is not None:
                client.live_jobs_stop_for()
        except Exception as e:
            logger.debug(f"stop live widgets before switch: {e}")

    def set_solid_light(self, color: str, brightness: int, mode_type: int = 0) -> bool:
        logger.info(f"GUI Action: Applying solid light {color} (brightness={brightness}, mode_type={mode_type})...")
        self._stop_live_widgets()
        try:
            return self._dispatch(lambda t: t.set_light(color, brightness)
                                if t is self._wall_instance else t.display.show_light(color, brightness, True, mode_type))
        except Exception as e:
            logger.error(f"Light setting failed: {e}")
            return False

    def set_clock(self, style: int, color: str = None) -> bool:
        logger.info(f"GUI Action: Applying clock style {style} with color {color}...")
        self._stop_live_widgets()
        try:
            return self._dispatch(lambda t: t.show_clock(clock=style)
                                if t is self._wall_instance else t.display.show_clock(clock=style, color=color))
        except Exception as e:
            logger.error(f"Clock setting failed: {e}")
            return False

    def switch_channel(self, channel: str) -> bool:
        logger.info(f"GUI Action: Switching channel to {channel}...")
        self._stop_live_widgets()
        try:
            return self._dispatch(lambda t: t.switch_channel(channel)
                                if t is self._wall_instance else t.display.switch_channel(channel))
        except Exception as e:
            logger.error(f"Channel switch failed: {e}")
            return False

    def set_vj_effect(self, number: int) -> bool:
        logger.info(f"GUI Action: Applying VJ effect {number}...")
        self._stop_live_widgets()
        try:
            return self._dispatch(lambda t: t.show_effects(number=int(number))
                                if t is self._wall_instance else t.display.show_effects(number=int(number)))
        except Exception as e:
            logger.error(f"VJ effect failed: {e}")
            return False

    def set_visualization(self, number: int) -> bool:
        logger.info(f"GUI Action: Applying visualizer {number}...")
        self._stop_live_widgets()
        try:
            return self._dispatch(lambda t: t.show_visualization(number=int(number))
                                if t is self._wall_instance else t.display.show_visualization(number=int(number)))
        except Exception as e:
            logger.error(f"Visualizer failed: {e}")
            return False

    def push_text(self, text: str, color: str = "#FFFFFF", font_size: int = 1,
                  speed: int = 50, effect_style: int = 1) -> bool:
        """Render the text on the DAEMON and push it as an image.

        R32 §D: the 0x87 "set light phone word attr" sequence does NOT render on
        the Pixoo-class LED matrices these devices are, so nothing appeared. The
        known-working references (hass-divoom, futpib) rasterise text into image
        frames and push them through the normal image path; so do we.

        R70 P3.3: the rasterising moved to `divoomd`. It was a SECOND reader of
        the same font blob — `divoom_lib/fonts/bitmap_font.py` and
        `live_jobs/render.rs` both over `divoom_fond16_default_half.bin` — and
        the copy here then NEAREST-scaled the finished bitmap down to fit, which
        destroys a bitmap font: at 16px "HELLO WORLD" came out as two rows of
        noise. The daemon draws at native size and clips, so fewer characters
        appear and they are intact.

        ``speed``/``effect_style`` are accepted for call compatibility and
        unused (static image); scrolling frames remain the real answer for long
        strings, and remain a follow-up.
        """
        try:
            if not text or not str(text).strip():
                return False
            size = self._device_size()
            _extras, png_path = self._widget_frame(
                "text", size,
                {"text": str(text), "color": color, "font_size": int(font_size)})
            return self._dispatch(lambda t: t.show_image(str(png_path))
                                if t is self._wall_instance else t.display.show_image(str(png_path)))
        except Exception as e:
            logger.error(f"push_text failed: {e}")
            return False

    def _device_size(self) -> int:
        """The active device's pixel size, or 16.

        R70 P3.3 note: this was deleted by accident along with
        `_render_text_png` — the two sat adjacent, and the cut took both. The
        full suite caught it (`push_text failed: 'LightingApi' object has no
        attribute '_device_size'`); the targeted runs did not, because none of
        them exercised push_text end to end.
        """
        getter = self._state_getter().get("_active_device_size")
        try:
            return int(getter() if callable(getter) else (getter or 16))
        except Exception:
            return 16

    def set_brightness(self, brightness: int) -> bool:
        logger.info(f"GUI Action: Setting brightness to {brightness}...")
        try:
            val = int(brightness)
            return self._dispatch(lambda t: t.set_brightness(val)
                                if t is self._wall_instance else
                                (t.lan.set_brightness(val) if t.lan else t.device.set_brightness(val)))
        except Exception as e:
            logger.error(f"Brightness setting failed: {e}")
            return False

    def set_volume(self, volume: int) -> bool:
        logger.info(f"GUI Action: Setting volume to {volume}...")
        try:
            val = max(0, min(15, int(volume)))
            return self._dispatch(lambda t: t.set_volume(val)
                                if t is self._wall_instance else t.music.set_volume(val))
        except Exception as e:
            logger.error(f"Volume setting failed: {e}")
            return False

    def display_wall_image(self, file_path: str, cell_size: int) -> dict:
        logger.info(f"GUI Action: Push display wall asset {file_path!r} (cell size={cell_size})...")
        try:
            self._rebuild_wall_instance(cell_size)
            target = self._wall_instance if self._wall_instance else self._current_divoom
            if target is None:
                raise RuntimeError("No active device or wall configured")

            if target is self._wall_instance:
                ok = self._run_async(target.show_image(file_path))
            else:
                ok = self._run_async(target.display.show_image(file_path))

            previews = {}
            if ok and self._wall_instance:
                try:
                    # R42 §6: the wall handle is a DaemonDeviceProxy — method
                    # calls return AWAITABLES. The bare call returned an
                    # un-awaited coroutine that poisoned the JSON reply, so the
                    # arranger never received its previews.
                    previews = self._run_async(self._wall_instance.get_last_previews())
                    if not isinstance(previews, dict):
                        previews = {}
                except Exception as ex:
                    logger.warning(f"Failed to get wall previews: {ex}")
            return {"success": bool(ok), "previews": previews}
        except Exception as e:
            logger.error(f"Wall display failed: {e}")
            return {"success": False, "error": str(e), "previews": {}}

    def set_temperature_channel(self, celsius: bool = True, color: str = "#ffffff") -> bool:
        logger.info(f"GUI Action: Setting temperature channel (celsius={celsius}, color={color})...")
        try:
            return self._dispatch(lambda t: t.display.set_temperature_channel(celsius=celsius, color=color)
                                if t is self._wall_instance else t.display.set_temperature_channel(celsius=celsius, color=color))
        except Exception as e:
            logger.error(f"Temperature channel failed: {e}")
            return False

    def set_clock_rich(self, style: int = 0, twentyfour: bool = True,
                       humidity: bool = False, weather: bool = False,
                       date: bool = False, color: str = "#ffffff") -> bool:
        logger.info(f"GUI Action: Setting rich clock (style={style}, twentyfour={twentyfour}, ...)")
        try:
            return self._dispatch(lambda t: t.display.set_clock_rich(style=style, twentyfour=twentyfour,
                                                                     humidity=humidity, weather=weather,
                                                                     date=date, color=color)
                                if t is self._wall_instance else t.display.set_clock_rich(style=style, twentyfour=twentyfour,
                                                                                          humidity=humidity, weather=weather,
                                                                                          date=date, color=color))
        except Exception as e:
            logger.error(f"Rich clock failed: {e}")
            return False

    def play_album(self, album_id: int) -> bool:
        """Play a cloud-browsed photo album on the device (Photo/PlayAlbum,
        LAN-only — see divoom_lib/lan_transport.py). Not meaningful on a
        Virtual Wall (the album targets one device's own local slideshow,
        not a composite image), so that target mode is rejected up front."""
        logger.info(f"GUI Action: Playing album {album_id} on device...")
        if self._current_target_mode == "wall":
            logger.warning("Album playback is not supported on a Virtual Wall target")
            return False
        self._stop_live_widgets()
        try:
            val = int(album_id)
            return self._dispatch(lambda t: t.lan.play_album(val))
        except Exception as e:
            logger.error(f"Album playback failed: {e}")
            return False

    def push_playlist(self, play_id: int) -> bool:
        """Push a cloud playlist to the device (Playlist/SendDevice, LAN-only —
        see divoom_lib/lan_transport.py). Not meaningful on a Virtual Wall
        (the playlist targets one device's own local slideshow, not a
        composite image), so that target mode is rejected up front."""
        logger.info(f"GUI Action: Pushing playlist {play_id} to device...")
        if self._current_target_mode == "wall":
            logger.warning("Playlist push is not supported on a Virtual Wall target")
            return False
        self._stop_live_widgets()
        try:
            val = int(play_id)
            return self._dispatch(lambda t: t.lan.send_playlist(val))
        except Exception as e:
            logger.error(f"Playlist push failed: {e}")
            return False

    def send_danmaku_text(self, text: str, color: str = "#FFFFFF") -> bool:
        """Send a Danmaku scrolling bullet-chat overlay (Danmaku/SendText,
        LAN-only — see divoomd/src/device_call/lan.rs).

        **The render is UNCONFIRMED on real hardware.** This command is in the
        vendor app's DeviceAndServerCmd table and ACKs cleanly, but nobody has
        watched it draw on a matrix here. R32 §D is the cautionary case: a
        superficially similar "set light phone word" command ACKed and rendered
        nothing. The UI says so next to the button rather than presenting this
        as equivalent to `push_text`, which uses the known-working bitmap path.

        Distinct from `push_text`, not a duplicate of it: this is the device's
        own overlay layer, drawn over whatever channel is showing, rather than a
        bitmap we render and upload.

        Wall mode is rejected up front for the same reason album and playlist
        playback are — the overlay targets one device's own display, not a
        composite image across several.
        """
        logger.info("GUI Action: Sending Danmaku overlay text...")
        if self._current_target_mode == "wall":
            logger.warning("Danmaku overlay is not supported on a Virtual Wall target")
            return False
        text = (text or "").strip()
        if not text:
            logger.warning("Danmaku text is empty; nothing to send")
            return False
        try:
            # Keyword args: the daemon handler reads "Text"/"TextColor" by name
            # (get_arg_str(kw, ...)), and positional args would silently land as
            # neither — the command would ACK having sent an empty string.
            return self._dispatch(
                lambda t: t.lan.send_danmaku_text(Text=text, TextColor=color))
        except Exception as e:
            logger.error(f"Danmaku send failed: {e}")
            return False

    def play_aid_sleep(self, sleep_id: int, sleep_type: int = 0) -> bool:
        """Play a browsed AidSleep cloud sound on the device (AidSleep/Play —
        BLE/SPP JSON, no cloud round-trip; see divoom_lib/tools/aid_sleep.py
        and divoomd/src/device_call/aid_sleep.rs). Not meaningful on a
        Virtual Wall (audio is per-device, not composite)."""
        logger.info(f"GUI Action: Playing AidSleep sound {sleep_id} (type={sleep_type})...")
        if self._current_target_mode == "wall":
            logger.warning("AidSleep playback is not supported on a Virtual Wall target")
            return False
        self._stop_live_widgets()
        try:
            return self._dispatch(lambda t: t.aid_sleep.play(int(sleep_id), int(sleep_type)))
        except Exception as e:
            logger.error(f"AidSleep play failed: {e}")
            return False

