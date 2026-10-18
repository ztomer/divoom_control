"""LightingApi — light/clock/channel/vj/visualization/text (REVIEW §1.2).

Extracts the display/lighting command surface.
"""
from __future__ import annotations

import logging
from divoom_gui.api import WALL, ApiBase
from divoom_gui.widget_frames import WidgetFrameMixin

logger = logging.getLogger("divoom_gui.api.lighting")


class LightingApi(ApiBase, WidgetFrameMixin):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    def _stop_live_widgets(self, mac: str) -> None:
        """A static-display takeover (channel / clock / VJ / visualizer / solid
        light / image) is mutually exclusive with a streaming live widget. Stop
        the named display's live jobs first -- every slot's, for the wall -- or
        the widget's next tick re-pushes its frame and clobbers the switch
        (HW-confirmed). Best-effort."""
        client = self._client
        if client is None or not isinstance(mac, str) or not mac:
            return  # no panel named: stop nothing, least of all the daemon's default
        for target in (list(self._wall_slots) if mac == WALL else [mac]):
            try:
                client.live_jobs_stop_for(target)
            except Exception as e:
                logger.debug(f"stop live widgets on {target} before switch: {e}")

    def _show(self, mac: str, what: str, on_wall, on_panel) -> bool:
        """Every display takeover's one path (P5.6): the display the click
        named, its live widgets stopped, then the write. No panel named, no
        write -- and nothing stopped on a panel nobody chose."""
        target = self._display(mac)
        if target is None:
            return False
        logger.info(f"GUI Action: {what} on {mac}")
        self._stop_live_widgets(mac)
        try:
            return self._run_async((on_wall if mac == WALL else on_panel)(target))
        except Exception as e:
            logger.error(f"{what} on {mac} failed: {e}")
            return False

    def set_solid_light(self, mac: str, color: str, brightness: int, mode_type: int = 0) -> bool:
        return self._show(mac, f"solid light {color} (brightness={brightness}, mode_type={mode_type})",
                          lambda t: t.set_light(color, brightness),
                          lambda t: t.display.show_light(color, brightness, True, mode_type))

    def set_clock(self, mac: str, style: int, color: str = None) -> bool:
        return self._show(mac, f"clock style {style} with color {color}",
                          lambda t: t.show_clock(clock=style),
                          lambda t: t.display.show_clock(clock=style, color=color))

    def switch_channel(self, mac: str, channel: str) -> bool:
        return self._show(mac, f"channel {channel}",
                          lambda t: t.switch_channel(channel),
                          lambda t: t.display.switch_channel(channel))

    def set_vj_effect(self, mac: str, number: int) -> bool:
        return self._show(mac, f"VJ effect {number}",
                          lambda t: t.show_effects(number=int(number)),
                          lambda t: t.display.show_effects(number=int(number)))

    def set_visualization(self, mac: str, number: int) -> bool:
        return self._show(mac, f"visualizer {number}",
                          lambda t: t.show_visualization(number=int(number)),
                          lambda t: t.display.show_visualization(number=int(number)))

    def push_text(self, mac: str, text: str, color: str = "#FFFFFF", font_size: int = 1,
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
        if not text or not str(text).strip():
            return False
        try:
            # Drawn at the NAMED panel's size: the text is for the panel
            # clicked, not whichever one is selected when this runs.
            _extras, png_path = self._widget_frame(
                "text", self._device_size(mac),
                {"text": str(text), "color": color, "font_size": int(font_size)})
        except Exception as e:
            logger.error(f"push_text failed: {e}")
            return False
        return self._show(mac, "text", lambda t: t.show_image(str(png_path)),
                          lambda t: t.display.show_image(str(png_path)))

    def _device_size(self, mac: str) -> int:
        """The named display's pixel size as the daemon resolved it, or 16.

        R70 P3.3 note: this was deleted by accident along with
        `_render_text_png` — the two sat adjacent, and the cut took both. The
        full suite caught it (`push_text failed: 'LightingApi' object has no
        attribute '_device_size'`); the targeted runs did not, because none of
        them exercised push_text end to end.
        """
        getter = self._state_getter().get("_size_of")
        try:
            return int(getter(mac)) if callable(getter) else 16
        except Exception:
            return 16

    def display_wall_image(self, mac: str, file_path: str, cell_size: int | None = None) -> dict:
        """Show an image on the display ``mac`` names: one panel, or the wall
        when it says `MatrixWall` (P5.7).

        Also the gallery's push (`gallery_sync.play_gallery_art`). It used to
        go to the wall whenever wall slots existed and otherwise to
        `current_divoom`, the panel the bench selected last, read when the
        push RAN: the wall now has to be NAMED, and a call naming nothing is
        refused like every other display write. ``cell_size`` is the edge of
        a wall slot that carries no size of its own."""
        logger.info(f"GUI Action: Push image {file_path!r} to {mac} (cell size={cell_size})...")
        try:
            target = self._display(mac, cell_size=cell_size)
            if target is None:
                why = ("No panel selected" if not mac else
                       "The wall could not be built" if mac == WALL else
                       "The background service is not running")
                return {"success": False, "error": why, "previews": {}}
            self._stop_live_widgets(mac)
            if mac == WALL:
                ok = self._run_async(target.show_image(file_path))
            else:
                ok = self._run_async(target.display.show_image(file_path))

            previews = {}
            if ok and mac == WALL:
                try:
                    # R42 §6: the wall handle is a DaemonDeviceProxy — method
                    # calls return AWAITABLES. The bare call returned an
                    # un-awaited coroutine that poisoned the JSON reply, so the
                    # arranger never received its previews.
                    previews = self._run_async(target.get_last_previews())
                    if not isinstance(previews, dict):
                        previews = {}
                except Exception as ex:
                    logger.warning(f"Failed to get wall previews: {ex}")
            return {"success": bool(ok), "previews": previews}
        except Exception as e:
            logger.error(f"Wall display failed: {e}")
            return {"success": False, "error": str(e), "previews": {}}

    def set_clock_rich(self, mac: str, style: int = 0, twentyfour: bool = True,
                       humidity: bool = False, weather: bool = False,
                       date: bool = False, color: str = "#ffffff") -> bool:
        def rich(t):
            return t.display.set_clock_rich(style=style, twentyfour=twentyfour, humidity=humidity,
                                            weather=weather, date=date, color=color)
        return self._show(mac, f"rich clock (style={style}, twentyfour={twentyfour})", rich, rich)

    def play_album(self, mac: str, album_id: int) -> dict:
        """Play a cloud-browsed photo album on the device (Photo/PlayAlbum,
        LAN-only — see divoom_lib/lan_transport.py). Not meaningful on a
        Virtual Wall (the album targets one device's own local slideshow,
        not a composite image), so that target mode is rejected up front."""
        logger.info(f"GUI Action: Playing album {album_id} on device...")
        from divoom_gui.api import _lan_error
        if mac == WALL:
            return _lan_error("play the album",
                              "a Virtual Wall has no single device to play it on",
                              "wall")
        self._stop_live_widgets(mac)
        try:
            val = int(album_id)
        except (TypeError, ValueError):
            return _lan_error("play the album", f"{album_id!r} is not an album id",
                              "input")
        return self._lan_action(mac, "play the album", lambda t: t.lan.play_album(val))

    def push_playlist(self, mac: str, play_id: int) -> dict:
        """Push a cloud playlist to the device (Playlist/SendDevice, LAN-only —
        see divoom_lib/lan_transport.py). Not meaningful on a Virtual Wall
        (the playlist targets one device's own local slideshow, not a
        composite image), so that target mode is rejected up front."""
        logger.info(f"GUI Action: Pushing playlist {play_id} to device...")
        from divoom_gui.api import _lan_error
        if mac == WALL:
            return _lan_error("push the playlist",
                              "a Virtual Wall has no single device to play it on",
                              "wall")
        self._stop_live_widgets(mac)
        try:
            val = int(play_id)
        except (TypeError, ValueError):
            return _lan_error("push the playlist", f"{play_id!r} is not a playlist id",
                              "input")
        return self._lan_action(mac, "push the playlist",
                                lambda t: t.lan.send_playlist(val))

    def send_danmaku_text(self, mac: str, text: str, color: str = "#FFFFFF") -> dict:
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
        from divoom_gui.api import _lan_error
        if mac == WALL:
            return _lan_error("send the overlay",
                              "a Virtual Wall has no single device to draw it on",
                              "wall")
        text = (text or "").strip()
        if not text:
            return _lan_error("send the overlay", "there is no text to send", "input")
        # Keyword args: the daemon handler reads "Text"/"TextColor" by name
        # (get_arg_str(kw, ...)), and positional args would silently land as
        # neither — the command would ACK having sent an empty string.
        return self._lan_action(
            mac, "send the overlay",
            lambda t: t.lan.send_danmaku_text(Text=text, TextColor=color))

    def play_aid_sleep(self, mac: str, sleep_id: int, sleep_type: int = 0) -> bool:
        """Play a browsed AidSleep cloud sound on the device (AidSleep/Play —
        BLE/SPP JSON, no cloud round-trip; see divoom_lib/tools/aid_sleep.py
        and divoomd/src/device_call/aid_sleep.rs). Not meaningful on a
        Virtual Wall (audio is per-device, not composite)."""
        logger.info(f"GUI Action: Playing AidSleep sound {sleep_id} (type={sleep_type})...")
        if mac == WALL:
            logger.warning("AidSleep playback is not supported on a Virtual Wall target")
            return False
        self._stop_live_widgets(mac)
        try:
            return self._dispatch(mac, lambda t: t.aid_sleep.play(int(sleep_id), int(sleep_type)))
        except Exception as e:
            logger.error(f"AidSleep play failed: {e}")
            return False

