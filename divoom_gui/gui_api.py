import json
import logging
import asyncio
import sys
import webview
from pathlib import Path

from divoom_lib import divoom_auth

from divoom_gui.presets_manager import PresetsManagerMixin
from divoom_gui.media_sync import MediaSyncMixin
from divoom_gui.scanner_mixin import ScannerMixin
from divoom_gui.debug_mixin import DebugMixin
from divoom_gui.lifecycle_mixin import LifecycleSettingsMixin
from divoom_gui.clock_faces import ClockFacesMixin
from divoom_gui.playlists import PlaylistsMixin
from divoom_gui.aid_sleep import AidSleepMixin
from divoom_gui.photo_albums import PhotoAlbumsMixin
from divoom_gui.weather_city import WeatherCityMixin
from divoom_gui.lighting_forward import LightingForwardMixin

from divoom_gui.api import AsyncLoopThread
from divoom_gui.api.connection import ConnectionApi
from divoom_gui.api.lighting import LightingApi
from divoom_gui.api.tools import ToolsApi
from divoom_gui.api.widgets import WidgetsApi
from divoom_gui.api.window import WindowApi

logger = logging.getLogger("divoom_gui")

class DivoomGuiAPI(DebugMixin, MediaSyncMixin, PresetsManagerMixin, ScannerMixin,
                   LifecycleSettingsMixin, ClockFacesMixin, PlaylistsMixin, AidSleepMixin,
                   PhotoAlbumsMixin, WeatherCityMixin, LightingForwardMixin):
    """The PyWebView JS api bridge orchestrator."""
    def __init__(self) -> None:
        self.loop_thread = AsyncLoopThread()
        self.loop_thread.start()
        self.loop_thread.ready.wait()

        self.current_divoom = None
        self.discovered_list = []
        self.wall_slots = {}
        self.wall_instance = None
        self.cached_creds = None
        self.device_pw = 0
        self.device_id = 0
        self.window = None

        self.music_sync_active = False
        self.music_thread = None
        self.current_track_cache = None
        self.current_target_mode = "single"

        self._daemon_client = None

        # Cache-only at startup: never block (or network-fail) GUI launch on a
        # Divoom cloud login. Real auth happens lazily when a cloud op needs it.
        try:
            self.cached_creds = divoom_auth.get_cached_credentials()
        except Exception as e:
            logger.warning(f"Failed to load cached credentials on startup: {e}")

        device_cache_path = Path.home() / ".config" / "divoom-control" / "virtual_device.json"
        if not device_cache_path.exists():
            device_cache_path = Path(__file__).parent.parent / "api_scraper" / "divoom_docs" / "virtual_device.json"
        if device_cache_path.exists():
            try:
                device_info = json.loads(device_cache_path.read_text(encoding="utf-8"))
                self.device_id = device_info.get("BluetoothDeviceId", 0)
                self.device_pw = device_info.get("DevicePassword", 0)
                logger.info(f"Loaded virtual device: DeviceId={self.device_id}")
            except Exception as e:
                logger.warning(f"Failed to load virtual device: {e}")

        self._wire_collaborators()

    def _wire_collaborators(self):
        _state = lambda: self.__dict__
        # Expose the active-device-size resolver to collaborators through the shared
        # state dict. It's a METHOD (on MediaSyncMixin), so it isn't in __dict__ by
        # default → LightingApi._device_size's `_state.get("_active_device_size")`
        # always missed and push_text rendered text at the 16px fallback on every
        # non-16px device. Storing the bound method here makes the lookup resolve.
        self.__dict__["_active_device_size"] = self._active_device_size
        _dc = lambda: self._daemon_client
        self.connection = ConnectionApi(self.loop_thread, _dc, _state)
        self.lighting = LightingApi(self.loop_thread, _dc, _state)
        self.tools = ToolsApi(self.loop_thread, _dc, _state)
        self.widgets = WidgetsApi(self.loop_thread, _dc, _state)
        self.window_mgr = WindowApi(self.loop_thread, _dc, _state)

    def _client(self):
        """Return a live DaemonClient, auto-spawning the daemon if needed (R17
        P5). Cached; ``None`` only if the daemon can't be reached/started."""
        from divoom_gui.daemon_bridge import ensure_daemon
        if self._daemon_client is None:
            self._daemon_client = ensure_daemon()
        return self._daemon_client

    def _run_async(self, coro, *, timeout: float = 120.0):
        # A3: bound the wait. Without a timeout a wedged async chain (a daemon
        # that stopped answering, a hung device op) blocked the pywebview JS-API
        # thread FOREVER — a frozen button with no error. 120s is well beyond any
        # legit op (a 60s scan, a slow BLE push); on expiry we cancel + raise so
        # the GUI surfaces an error instead of hanging.
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(coro, self.loop_thread.loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error("GUI async op timed out after %.0fs", timeout)
            raise RuntimeError(f"Operation timed out after {timeout:.0f}s")

    def minimize_window(self) -> None:
        self.window_mgr.minimize_window()

    def maximize_window(self) -> None:
        self.window_mgr.maximize_window()

    def close_window(self) -> None:
        # Tie the daemon's lifecycle to the GUI: stop the daemon we spawned so it
        # doesn't linger after the window closes (clean kill switch).
        try:
            from divoom_lib.lifecycle_config import (
                get_keep_daemon_alive, should_stop_daemon_on_dashboard_quit)
            if self._daemon_client is not None and should_stop_daemon_on_dashboard_quit(get_keep_daemon_alive()):
                self._daemon_client.shutdown()
        except Exception as e:
            logger.debug(f"daemon shutdown on close skipped: {e}")
        self.window_mgr.close_window()

    def set_solid_light(self, color: str, brightness: int, mode_type: int = 0) -> bool:
        return self.lighting.set_solid_light(color, brightness, mode_type)

    def set_clock(self, style: int, color: str = None) -> bool:
        return self.lighting.set_clock(style, color)

    def switch_channel(self, channel: str) -> bool:
        return self.lighting.switch_channel(channel)

    def set_vj_effect(self, number: int) -> bool:
        return self.lighting.set_vj_effect(number)

    def set_visualization(self, number: int) -> bool:
        return self.lighting.set_visualization(number)

    def push_text(self, text: str, color: str = "#FFFFFF", font_size: int = 1,
                  speed: int = 50, effect_style: int = 1) -> bool:
        return self.lighting.push_text(text, color, font_size, speed, effect_style)

    def send_danmaku_text(self, text: str, color: str = "#FFFFFF") -> bool:
        return self.lighting.send_danmaku_text(text, color)

    def get_alarms(self) -> str:
        return self.tools.get_alarms()

    def set_alarm(self, index: int, enabled, hour: int, minute: int,
                  week: int = 0, mode: int = 0, trigger_mode: int = 0) -> bool:
        return self.tools.set_alarm(index, enabled, hour, minute, week, mode, trigger_mode)

    def start_sleep(self, minutes: int = 30, color: str = "#2040ff", volume: int = 10) -> bool:
        return self.tools.start_sleep(minutes, color, volume)

    def stop_sleep(self) -> bool:
        return self.tools.stop_sleep()

    def set_timer(self, action: str = "start") -> bool:
        return self.tools.set_timer(action)

    def set_countdown(self, action: str = "start", minutes: int = 5, seconds: int = 0) -> bool:
        return self.tools.set_countdown(action, minutes, seconds)

    def set_noise(self, action: str = "start") -> bool:
        return self.tools.set_noise(action)

    def set_hour_type(self, is_24h) -> bool:
        return self.tools.set_hour_type(is_24h)

    def set_temp_unit(self, fahrenheit) -> bool:
        return self.tools.set_temp_unit(fahrenheit)

    def sync_time(self) -> bool:
        return self.tools.sync_time()

    def set_device_name(self, name: str) -> bool:
        return self.tools.set_device_name(name)

    def set_auto_power_off(self, minutes: int) -> bool:
        return self.tools.set_auto_power_off(minutes)

    def set_low_power(self, on) -> bool:
        return self.tools.set_low_power(on)


    def set_temperature_channel(self, celsius: bool = True, color: str = "#ffffff") -> bool:
        # Route to LightingApi: it honors `color` and is wall-aware via _dispatch.
        # The old WidgetsApi version hard-coded white (dropped the user's color) and
        # only ever targeted the single active device.
        return self.lighting.set_temperature_channel(celsius, color)

    def set_clock_rich(self, style: int = 0, twentyfour: bool = True,
                       humidity: bool = False, weather: bool = False,
                       date: bool = False, color: str = "#ffffff") -> bool:
        return self.lighting.set_clock_rich(style, twentyfour, humidity, weather, date, color)

    def get_weather(self) -> dict:
        return self.widgets.get_weather()

    def set_fm_frequency(self, freq_x10: int) -> bool:
        return self.tools.set_fm_frequency(freq_x10)

    def set_memorial(self, index, enabled, month, day, hour, minute, title="") -> bool:
        return self.tools.set_memorial(index, enabled, month, day, hour, minute, title)

    def set_timeplan(self, index, enabled, hour, minute, week=0, channel=0) -> bool:
        return self.tools.set_timeplan(index, enabled, hour, minute, week, channel)

    def set_screen_dir(self, direction) -> bool:
        return self.tools.set_screen_dir(direction)

    def set_screen_mirror(self, on) -> bool:
        return self.tools.set_screen_mirror(on)

    def factory_reset(self, confirm="") -> bool:
        if str(confirm) != "RESET":
            logger.warning("factory_reset refused: missing/invalid confirm token")
            return False
        return self.tools.factory_reset(confirm)

    # Lifecycle-settings methods (keep_daemon_alive / quit_menubar_on_exit) live
    # on LifecycleSettingsMixin so pywebview still exposes them as api.get_*().

    def live_job_list(self, mac: str | None = None) -> dict:
        client = self._client()
        if client is None:
            return {"success": False, "error": "daemon unavailable"}
        return client.live_job_list(mac)

    def send_notification(self, app_type, text="") -> bool:
        t = int(app_type)
        if not (1 <= t <= 14):
            logger.warning(f"send_notification: app_type {t} out of range 1-14")
            return False
        return self.tools.send_notification(t, text)

    # ── macOS notification mirroring (daemon-owned) ───────────────────────
    # The daemon is the SINGLE owner of the macOS Notification Center monitor
    # (see docs/archive/superseded/PLANNING_daemon_ownership.md). It polls the DB, routes each
    # notification to the device it owns, and broadcasts events. The GUI must
    # NOT run its own monitor — doing so double-routes every notification. These
    # methods are thin pass-throughs to the daemon's RPCs.

    @staticmethod
    def _daemon_state_running(reply: dict) -> bool:
        return reply.get("state") == "active"

    def start_notification_listener(self) -> dict:
        """Ask the daemon to start its notification monitor. Returns a status
        dict for the JS side (``{running, db_path, error?}``). Idempotent."""
        if sys.platform != "darwin":
            return {"running": False, "error": "macOS only"}
        client = self._client()
        if client is None:
            return {"running": False, "error": "daemon unavailable"}
        reply = client.start_notifications()
        from divoom_client.macos_notifications import find_notification_db_path
        db_path = find_notification_db_path()
        out = {
            "running": self._daemon_state_running(reply),
            "db_path": str(db_path) if db_path else None,
        }
        if reply.get("error"):
            out["error"] = reply["error"]
        return out

    def stop_notification_listener(self) -> dict:
        """Ask the daemon to stop its notification monitor. No-op if idle."""
        client = self._client()
        if client is None:
            return {"running": False}
        reply = client.stop_notifications()
        return {"running": self._daemon_state_running(reply)}

    def get_notification_listener_status(self) -> dict:
        """Rich status snapshot for the Settings → Devices card.

        Returns a dict the JS side can render directly::

            {
              "platform_supported": bool,    # False on non-darwin
              "running": bool,
              "db_path": str | None,         # macOS Notification Center DB
              "routing_path": str,           # ~/.config/divoom-control/...
              "rules": [[substr, app_type], ...],
              "counters": {"seen": int, "routed": int, "dropped": int},
              "error": str | None,
            }
        """
        from divoom_client.macos_notifications import (
            ROUTING_PATH, load_routing_table, find_notification_db_path,
        )
        if sys.platform != "darwin":
            return {
                "platform_supported": False,
                "running": False,
                "db_path": None,
                "routing_path": str(ROUTING_PATH),
                "rules": [list(r) for r in load_routing_table()],
                "counters": {"seen": 0, "routed": 0, "dropped": 0},
                "error": "macOS notifications are only supported on macOS",
            }
        # The daemon owns the monitor; ask it for live state + counters. The
        # routing table and DB path are read from disk (no monitor needed).
        client = self._client()
        if client is None:
            return {
                "platform_supported": True,
                "running": False,
                "db_path": None,
                "routing_path": str(ROUTING_PATH),
                "rules": [list(r) for r in load_routing_table()],
                "counters": {"seen": 0, "routed": 0, "dropped": 0},
                "error": "daemon unavailable",
            }
        status = client.notification_status()
        db_path = find_notification_db_path()
        return {
            "platform_supported": True,
            "running": self._daemon_state_running(status),
            "db_path": str(db_path) if db_path else None,
            "routing_path": str(ROUTING_PATH),
            "rules": [list(r) for r in load_routing_table()],
            "counters": status.get("counters") or {"seen": 0, "routed": 0, "dropped": 0},
            "error": status.get("error"),
        }

    def save_notification_routing(self, json_text: str) -> dict:
        """Save a user-edited routing table. Validated here, then persisted +
        hot-reloaded on the daemon (which owns the monitor) via ``set_routing``.

        Returns ``{"rules": [[substr, app_type], ...], "error": str|None}``.

        On parse / validation error, returns the *previous* rule list
        unchanged and a non-null ``error`` string — the GUI shows the
        error and keeps the user's draft.
        """
        from divoom_client.macos_notifications import load_routing_table
        import json as _json
        try:
            parsed = _json.loads(json_text) if json_text.strip() else []
        except _json.JSONDecodeError as e:
            return {"rules": [list(r) for r in load_routing_table()], "error": f"Invalid JSON: {e}"}
        try:
            rules = [(s, int(t)) for s, t in parsed]
        except (ValueError, TypeError) as e:
            return {
                "rules": [list(r) for r in load_routing_table()],
                "error": f"Invalid routing entries: {e}",
            }
        client = self._client()
        if client is None:
            return {"rules": [list(r) for r in load_routing_table()], "error": "daemon unavailable"}
        reply = client.set_routing(rules)
        if not reply.get("success"):
            return {
                "rules": [list(r) for r in load_routing_table()],
                "error": reply.get("error") or "set_routing failed",
            }
        logger.info(f"save_notification_routing: saved {len(rules)} rules via daemon")
        return {"rules": [list(r) for r in load_routing_table()], "error": None}

    def device_call(self, method: str, args: list = None, kwargs: dict = None,
                     target: str = "device", blobs: dict = None,
                     token: str = None) -> str:
        """Generic device method proxy (exposed to JS). Routes through daemon."""
        client = self._client()
        if client is None:
            return json.dumps({"success": False, "error": "daemon unavailable"})
        reply = client.device_call(method, args, kwargs, target=target,
                                   blobs=blobs, token=token)
        return json.dumps(reply)

    def open_file_dialog(self) -> str | None:
        logger.info("Opening native file dialog...")
        try:
            if not self.window:
                logger.error("No webview window reference available.")
                return None
            
            file_types = ('Image files (*.png;*.jpg;*.jpeg;*.gif)', 'All files (*.*)')
            result = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=file_types
            )
            
            if result and len(result) > 0:
                logger.info(f"Selected file: {result[0]}")
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Error opening file dialog: {e}")
            return None

    def get_brightness(self) -> int | None:
        return self.tools.get_brightness()

    def get_device_name(self) -> str | None:
        return self.tools.get_device_name()

    def get_work_mode(self) -> int | None:
        return self.tools.get_work_mode()

    def get_volume(self) -> int | None:
        return self.tools.get_volume()

    def set_scoreboard(self, on_off: int, red: int = 0, blue: int = 0) -> bool:
        return self.tools.set_scoreboard(on_off, red, blue)

    # ── Round 15 §5 (R28: routes through the daemon) ──────────────────
    #
    # The GUI spawns ``python -m divoom_lib.cli mcp-server`` as a subprocess and
    # tracks it via MCPController. pywebview's event loop and the MCP server's
    # stdio loop would otherwise fight over file descriptors — subprocess
    # isolation is the clean fix. The MCP server no longer opens its own BLE
    # connection: it's a daemon client, so no MAC is required.

    def start_mcp_server(self, mac: str = "") -> dict:
        """Start the MCP stdio server subprocess (R15 §5; R28 daemon-routed).

        ``mac`` is optional and no longer required — the MCP server routes
        through the daemon (the sole device owner). It's passed through only so a
        spawned daemon can target a specific device. Returns a status dict (see
        ``mcp_server_status()``)."""
        from divoom_gui.mcp_control import MCPController, status_to_dict
        ctl = MCPController.instance()
        target_mac = mac or None
        return status_to_dict(ctl.start(mac=target_mac))

    def stop_mcp_server(self) -> dict:
        """Stop the MCP server subprocess (no-op if not running)."""
        from divoom_gui.mcp_control import MCPController, status_to_dict
        ctl = MCPController.instance()
        return status_to_dict(ctl.stop())

    def mcp_server_status(self) -> dict:
        """Snapshot of the subprocess state (JSON-friendly)."""
        from divoom_gui.mcp_control import MCPController, status_to_dict
        return status_to_dict(MCPController.instance().status())
