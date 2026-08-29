# gui/media_sync.py

import json
import base64
import logging
import threading
import time
from pathlib import Path

from divoom_lib.utils import media_source
from divoom_lib.utils.atomic_io import atomic_write_text
from divoom_gui.gallery_sync import GallerySyncMixin
from divoom_gui.audio_visualizer import AudioVisualizerWorker

logger = logging.getLogger("divoom_gui")

class MediaSyncMixin(GallerySyncMixin):
    """Mixin for macOS active playback tracker, stock tickers, sysmon widget, and frame pushing."""
    def _get_device_size(self, address: str) -> int:
        for d in self.discovered_list:
            if d.get("address") == address:
                name = d.get("name", "").lower()
                if "64" in name:
                    return 64
                return 16
        return 16

    def get_system_stats_preview(self, size: int = 0) -> str:
        try:
            stats = media_source.get_system_stats()
            sz = int(size) if size and int(size) > 0 else self._active_device_size()
            frame_path = media_source.render_system_stats_frame(stats, size=sz)
            return json.dumps({
                "ok": True, "size": sz, "stats": stats,
                "preview": self._frame_to_data_url(frame_path),
            })
        except Exception as e:
            logger.error(f"get_system_stats_preview failed: {e}")
            return json.dumps({"ok": False, "error": str(e)})

    def apply_system_stats(self) -> str:
        try:
            stats = media_source.get_system_stats()
            if not self._has_push_target():
                return json.dumps({"success": False, "error": "No device connected", "stats": stats})
            size = self._active_device_size()
            frame_path = media_source.render_system_stats_frame(stats, size=size)
            res = self._push_frame(frame_path, size)
            return json.dumps({
                "success": res, "stats": stats,
                "preview": self._frame_to_data_url(frame_path),
            })
        except Exception as e:
            logger.error(f"apply_system_stats failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    def get_current_track_info(self) -> str:
        """What is playing — asked of the DAEMON, not discovered here.

        R67/C2: this used to call `media_source.get_current_playing_track()`,
        which ran osascript inside the GUI process against each player in turn
        and then guessed a cover-art URL from the iTunes Search API. That was a
        second implementation of a question the daemon already answered, and
        being in the GUI process is why the GUI asked for Apple Music access.

        The preview image is now the SAME artwork the device is pushed —
        downsampled from the same bytes — rather than a lookalike fetched from a
        different source. It is also a `data:` URL: the web UI is served from a
        `file://` origin, where WKWebView blocks remote subresources, which is
        why the old remote `artwork_url` rendered as a broken image.
        """
        try:
            client = self._client()
            if client is None:
                return json.dumps({})
            reply = client.now_playing(include_artwork=True)
            if not isinstance(reply, dict):
                return json.dumps({})

            if not reply.get("available", False):
                # Honest unavailable state: say WHY rather than looking idle.
                return json.dumps({"available": False,
                                   "reason": reply.get("reason", "unavailable")})
            if not reply.get("playing", False):
                return json.dumps({"available": True, "playing": False})

            preview = ""
            art_b64 = reply.get("artwork_b64")
            if art_b64:
                preview = self._artwork_preview(art_b64)

            return json.dumps({
                "available": True,
                "playing": True,
                "track": reply.get("title"),
                "artist": reply.get("artist"),
                "album": reply.get("album"),
                "source": reply.get("source"),
                "identity": reply.get("identity"),
                "preview": preview,
            })
        except Exception as e:
            logger.warning(f"now_playing failed: {e}")
            return json.dumps({})

    def _artwork_preview(self, artwork_b64: str) -> str:
        """Downsample the daemon's artwork bytes to the device size, as a data URL.

        Uses the same renderer path the device frame comes from, so the card and
        the panel cannot drift (house rule: previews mirror live state through
        the shared renderer, never a parallel pipeline).
        """
        import base64 as _b64
        import io
        try:
            raw = _b64.b64decode(artwork_b64)
            size = self._active_device_size()
            from PIL import Image
            # PIL sniffs the container itself, which matters: macOS reports
            # image/jpeg for what are actually TIFF bytes, so anything that
            # trusted the declared MIME would pick the wrong decoder.
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img = img.resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            logger.debug(f"artwork preview failed: {e}")
            return ""

    def _active_device_size(self, default: int = 16) -> int:
        try:
            if self.wall_slots:
                sizes = [s.get("size", default) for s in self.wall_slots.values() if isinstance(s, dict)]
                return min(sizes) if sizes else default
            dev = self.current_divoom
            mac = getattr(getattr(dev, "_conn", None), "mac", None) or getattr(dev, "mac", None)
            if mac:
                return self._get_device_size(mac)
        except Exception:
            pass
        return default

    def _has_push_target(self) -> bool:
        dev = self.current_divoom
        return bool(self.wall_slots) or bool(dev)

    def _push_frame(self, frame_path, size: int) -> bool:
        """Push a rendered frame to the wall or the single active (BLE/LAN) device with auto-reconnect support.

        Round 4 note: cover-art, sysmon, stock-ticker, and notifications
        all route through `dev.display.show_image` which uses the 0x49
        multi-frame command (NOT 0x44). When reading device ACK logs, a
        response like `01 06 00 04 31 55 50 e0 00 02` is the device
        ACKing our 0x49 push — the `0x31` byte is **0x31 hexadecimal =
        49 decimal**, which is the same as the `0x49` we sent. This is
        a common decimal-vs-hex confusion in raw-log parsing. The status
        byte `0x50` is the device's response code (unknown meaning,
        not a documented error). Cover art and single-frame pushes
        through this path are confirmed working on Timoo/Pixoo as of
        2026-06-05.
        """
        if self.wall_slots:
            if self._rebuild_wall_instance(size):
                async def connect_and_show():
                    await self.wall_instance.connect()
                    return await self.wall_instance.show_image(str(frame_path))
                return bool(self._run_async(connect_and_show()))
            return False
            
        dev = self.current_divoom
        if not dev:
            return False

        # Push directly. The daemon's device_call already ensures the device is
        # connected (_ensure_device_async reconnects an idle/dropped link, honest
        # is_alive) before the call AND routes to the right transport, so the GUI
        # must NOT pre-check `dev.is_connected` / `dev.lan` here: each was a BLOCKING
        # device_status() RPC — `is_connected` ran INSIDE the loop coroutine, stalling
        # the WHOLE asyncio loop for the round-trip; the reconnect was redundant too.
        return bool(self._run_async(dev.display.show_image(str(frame_path))))

    @staticmethod
    def _frame_to_data_url(frame_path) -> str:
        try:
            data = Path(frame_path).read_bytes()
            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        except Exception:
            return ""

    def get_ticker_preview(self, symbol: str, size: int = 0) -> str:
        try:
            # NB: this only RENDERS a local preview frame — it never pushes to the
            # device — so it must NOT touch the connection. The old dev.lan /
            # dev.is_connected / dev.connect() pre-check fired two blocking
            # device_status()/device_call RPCs on the pywebview JS thread per
            # render (freezing the preview button up to the 120s _run_async cap on
            # a wedged connect), for no benefit. Removed (same class as R53.30).
            data = media_source.fetch_stock_ticker(symbol)
            if not data:
                return json.dumps({"ok": False, "error": "no data"})
            sz = int(size) if size and int(size) > 0 else self._active_device_size()
            frame_path = media_source.render_stock_ticker_frame(symbol, data, size=sz)
            return json.dumps({
                "ok": True, "size": sz, "symbol": symbol,
                "preview": self._frame_to_data_url(frame_path),
                "price": data["price"], "change": data["change"], "pct_change": data["pct_change"],
            })
        except Exception as e:
            logger.error(f"get_ticker_preview failed: {e}")
            return json.dumps({"ok": False, "error": str(e)})

    def apply_stock_ticker(self, symbol: str) -> str:
        logger.info(f"GUI Action: Applying stock ticker for {symbol}...")
        try:
            data = media_source.fetch_stock_ticker(symbol)
            if not data:
                return json.dumps({"success": False, "error": "Could not fetch ticker data"})
            if not self._has_push_target():
                return json.dumps({"success": False, "error": "No device connected"})

            size = self._active_device_size()
            frame_path = media_source.render_stock_ticker_frame(symbol, data, size=size)
            res = self._push_frame(frame_path, size)

            return json.dumps({
                "success": res,
                "preview": self._frame_to_data_url(frame_path),
                "price": data["price"],
                "change": data["change"],
                "pct_change": data["pct_change"],
            })
        except Exception as e:
            logger.error(f"Failed to apply stock ticker: {e}")
            return json.dumps({"success": False, "error": str(e)})

    def _tickers_path(self):
        return Path.home() / ".config" / "divoom-control" / "tickers.json"

    def get_tickers(self) -> str:
        path = self._tickers_path()
        if path.exists():
            try:
                return json.dumps(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        seed = self._seed_tickers_from_macos()
        self.set_tickers(json.dumps(seed))
        return json.dumps(seed)

    def set_tickers(self, *symbols_arg, **kwargs) -> bool:
        try:
            symbols = self._coerce_list(symbols_arg, kwargs, "tickers")
            seen, clean = set(), []
            for s in symbols:
                s = str(s).strip().upper()
                if s and s not in seen:
                    seen.add(s)
                    clean.append(s)
            path = self._tickers_path()
            # Atomic (temp+fsync+rename): a truncated tickers.json would make
            # get_tickers() fall into its except branch and silently RE-SEED the
            # user's list from macOS/defaults — i.e. corruption here destroys the
            # saved tickers, not just fails to load them (A1).
            atomic_write_text(path, json.dumps(clean, indent=2))
            return True
        except Exception as e:
            logger.error(f"set_tickers failed: {e}")
            return False

    @staticmethod
    def _seed_tickers_from_macos() -> list:
        default = ["AAPL", "GOOGL", "MSFT", "TSLA", "BTC-USD", "ETH-USD"]
        try:
            import subprocess
            out = subprocess.run(
                ["defaults", "read", "com.apple.stocks"],
                capture_output=True, text=True, timeout=4)
            import re
            syms = re.findall(r'"?symbol"?\s*=\s*"?([A-Z][A-Z0-9.\-]{0,9})"?', out.stdout)
            cleaned = []
            for s in syms:
                s = s.upper()
                if s and s not in cleaned:
                    cleaned.append(s)
            return cleaned or default
        except Exception:
            return default

    def trigger_notification(self, app_name: str) -> str:
        try:
            import asyncio
            if not self._has_push_target():
                return json.dumps({"success": False, "error": "No device connected"})
            
            size = self._active_device_size()
            frame_path = media_source.render_notification_frame(app_name, size=size)
            
            # Trigger BLE hardware alert in the background
            if self.current_divoom and not self.current_divoom.lan:
                mapping = {"kakao": 1, "instagram": 2, "facebook": 4, "whatsapp": 6, "mail": 7, "telegram": 13}
                code = mapping.get(app_name.lower(), 7)
                color_map = {"whatsapp": [34, 197, 94], "mail": [255, 255, 255], "telegram": [14, 165, 233]}
                rgb = color_map.get(app_name.lower(), [255, 90, 31])
                try:
                    if self.current_divoom.device:
                        async def send_hw_notif():
                            try:
                                await self.current_divoom.device.send_command(0x60, [code, rgb[0], rgb[1], rgb[2]])
                            except Exception:
                                pass
                        asyncio.run_coroutine_threadsafe(send_hw_notif(), self.loop_thread.loop)
                except Exception:
                    pass
            
            # Push pixel art frame (which switches BLE device to design channel automatically)
            res = self._push_frame(frame_path, size)
            return json.dumps({
                "success": res,
                "preview": self._frame_to_data_url(frame_path),
            })
        except Exception as e:
            logger.error(f"trigger_notification failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    # ── 1. ACTIVE LIVE WIDGETS SYNC LOOPS (Daemon-delegated) ──
    def _active_device_mac(self) -> str | None:
        if self.wall_slots:
            return "MatrixWall"
        dev = self.current_divoom
        if not dev:
            return None
        if dev.lan:
            return f"LAN:{dev.lan.device_ip}"
        mac = getattr(getattr(dev, "_conn", None), "mac", None) or getattr(dev, "mac", None)
        return mac

    def _get_live_params(self) -> dict:
        params = {"size": self._active_device_size()}
        if self.wall_slots:
            params["wall_slots"] = self.wall_slots
        dev = self.current_divoom
        if dev and dev.lan:
            params["lan_token"] = getattr(dev.lan, "local_token", 0)
        # R67/C2: the weather job reads params["location"] and this never sent
        # it, so the daemon fell back to IP geolocation while the GUI preview
        # resolved the location its own way. Same machine usually agrees — but
        # not when the daemon was started separately (the dev bundle, launchd)
        # and so did not inherit the GUI's DIVOOM_CONTROL_WEATHER_* env. Send
        # the resolved value rather than letting two resolvers guess apart.
        try:
            from divoom_lib.weather_provider import _resolve_location
            location = _resolve_location(None)
            if location:
                params["location"] = location
        except Exception as e:
            logger.debug(f"could not resolve weather location for live params: {e}")
        return params

    @staticmethod
    def _job_reply_ok(reply) -> bool:
        """Did the daemon actually accept the live-job command?

        R67/C4: every toggle used to `return True` without reading the reply, so
        a job the daemon refused still showed as enabled. "Switched on" and
        "working" must not be the same signal.
        """
        if isinstance(reply, dict):
            return bool(reply.get("success", False))
        return bool(reply)

    def _toggle_live_job(self, enable: bool, kind: str, params: dict | None = None) -> bool:
        """Start or stop one live job and report what the daemon actually said."""
        client = self._client()
        if client is None:
            return False
        mac = self._active_device_mac()
        if not mac:
            return False
        try:
            if enable:
                reply = client.live_job_start(mac, kind, params or self._get_live_params())
            else:
                reply = client.live_job_stop(mac, kind)
        except Exception as e:
            logger.error(f"live job {kind} {'start' if enable else 'stop'} failed: {e}")
            return False
        ok = self._job_reply_ok(reply)
        if not ok:
            logger.warning(f"daemon refused live job {kind}: {reply}")
        return ok

    def toggle_sysmon_sync(self, enable: bool) -> bool:
        logger.info(f"GUI Action: Toggle sysmon sync to {enable}")
        self.sysmon_sync_active = enable
        return self._toggle_live_job(enable, "sysmon")

    def toggle_stocks_sync(self, enable: bool, symbol: str = "") -> bool:
        logger.info(f"GUI Action: Toggle stocks sync to {enable} for symbol {symbol}")
        self.stocks_sync_active = enable
        if symbol:
            self.stocks_symbol = symbol
        params = self._get_live_params()
        params["symbol"] = symbol or getattr(self, "stocks_symbol", "")
        return self._toggle_live_job(enable, "stocks", params)

    def toggle_music_sync(self, enable: bool) -> bool:
        logger.info(f"GUI Action: Toggle music sync to {enable}")
        self.music_sync_active = enable
        return self._toggle_live_job(enable, "music")

    def toggle_weather_sync(self, enable: bool) -> bool:
        logger.info(f"GUI Action: Toggle weather sync to {enable}")
        return self._toggle_live_job(enable, "weather")

    # ── 2. AUDIO VISUALIZER API BINDINGS ──
    def toggle_audio_visualizer(self, enable: bool) -> bool:
        logger.info(f"GUI Action: Toggle audio visualizer to {enable}")
        if enable:
            if not getattr(self, "_audio_worker", None):
                self._audio_worker = AudioVisualizerWorker()
                self._audio_worker.start()
        else:
            if getattr(self, "_audio_worker", None):
                self._audio_worker.stop()
                self._audio_worker = None
        return True

    def get_audio_levels(self) -> str:
        worker = getattr(self, "_audio_worker", None)
        if worker:
            return json.dumps({
                "levels": worker.levels,
                "loopback_active": worker.loopback_active,
                "device_name": worker.device_name
            })
        return json.dumps({
            "levels": [0.0] * 10,
            "loopback_active": False,
            "device_name": "None"
        })
