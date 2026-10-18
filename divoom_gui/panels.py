"""What each panel IS and how bright and loud it is -- asked of the daemon, by mac (P5.1).

Before this, brightness and volume were read once at GUI startup with no mac
(whichever panel `current_divoom` happened to be) and written with no mac,
and panel size was guessed from the device NAME in three places that
disagreed (`getDeviceDimensions`, `resolveDeviceSpec` and
`MediaSyncMixin._get_device_size`), although `device_status` has carried each
panel's model and resolution since P3.1. The per-device rule says every
per-panel fact has one owner, the daemon; these four calls are how the GUI
asks it, and every one of them names its panel.

Replies are JSON strings in the `{ok, ...}` shape the web UI already unwraps.
A value the daemon could not read is `null`, never a guess: the UI shows it as
unknown.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("divoom_gui")

#: The selector the bench uses for the virtual wall; a wall level goes to the
#: daemon-owned wall, not to a panel.
WALL = "MatrixWall"

#: `device_status` fields that say what a panel is (`divoomd/src/panel_model.rs`).
PANEL_FIELDS = ("mac", "connected", "selected", "model", "width", "height", "model_source", "features")


class PanelsMixin:
    """Mixed into DivoomGuiAPI; every method is callable from JS."""

    def _panel_proxy(self, mac: str):
        from divoom_gui.daemon_bridge import DaemonDeviceProxy
        client = self._client()
        if client is None:
            return None
        return DaemonDeviceProxy(client, target="device", mac=mac)

    def _panel_status(self, mac: str) -> dict:
        client = self._client()
        if client is None:
            return {}
        try:
            return client.device_status(mac=mac) or {}
        except Exception as exc:
            logger.debug("device_status(%s) failed: %s", mac, exc)
            return {}

    def _panel_pixels(self, mac: str | None) -> int | None:
        """The panel's edge in pixels as the daemon resolved it, or None when it
        cannot say (no daemon, an unknown panel, a LAN panel with no name)."""
        if not mac:
            return None
        width = self._panel_status(mac).get("width")
        return int(width) if isinstance(width, int) and width > 0 else None

    def get_panels(self) -> str:
        """Every linked panel with what the daemon knows it is."""
        client = self._client()
        if client is None:
            return json.dumps({"ok": False, "error": "the background service is not running", "panels": []})
        try:
            st = client.device_status() or {}
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc), "panels": []})
        panels = [{k: d.get(k) for k in PANEL_FIELDS} for d in (st.get("devices") or [])]
        return json.dumps({"ok": True, "panels": panels})

    def get_panel_levels(self, mac: str) -> str:
        """`{ok, mac, brightness, volume}` as the panel reports them now.

        Volume is not asked of a panel the vendor app says has no speaker (the
        read would only wait out its timeout); it is `null`, like any value
        the panel did not give."""
        if not mac or mac == WALL:
            return json.dumps({"ok": False, "mac": mac, "error": "name one panel"})
        proxy = self._panel_proxy(mac)
        if proxy is None:
            return json.dumps({"ok": False, "mac": mac, "error": "the background service is not running"})
        features = self._panel_status(mac).get("features") or {}
        out = {"ok": True, "mac": mac, "brightness": None, "volume": None}
        try:
            out["brightness"] = self._run_async(proxy.device.get_brightness())
            if features.get("speaker", True):
                out["volume"] = self._run_async(proxy.music.get_volume())
        except Exception as exc:
            return json.dumps({"ok": False, "mac": mac, "error": str(exc)})
        return json.dumps(out)

    def _level_write(self, mac: str, what: str, wall_call, panel_call) -> bool:
        if not mac:
            logger.error("%s refused: no panel named", what)
            return False
        try:
            if mac == WALL:
                if not self.lighting._rebuild_wall_instance():
                    return False
                return bool(self._run_async(wall_call(self.wall_instance)))
            proxy = self._panel_proxy(mac)
            if proxy is None:
                return False
            return bool(self._run_async(panel_call(proxy)))
        except Exception as exc:
            logger.error("%s on %s failed: %s", what, mac, exc)
            return False

    def set_brightness(self, brightness: int, mac: str) -> bool:
        val = max(0, min(100, int(brightness)))
        logger.info("GUI Action: brightness %s on %s", val, mac)

        def on_panel(p):
            # A LAN panel takes brightness over its HTTP API (`lan.set_brightness`
            # in divoomd/src/device_call/lan.rs), not the BLE opcode. `p.lan` is
            # only a status VIEW (`_LanView`, no methods): the old
            # `t.lan.set_brightness(...)` raised on every LAN panel and the
            # MagicMock tests never noticed.
            if p.lan:
                from divoom_gui.daemon_bridge import DaemonDeviceProxy
                return DaemonDeviceProxy(p._client, "lan", target="device", mac=mac).set_brightness(val)
            return p.device.set_brightness(val)

        return self._level_write(mac, "set_brightness", lambda w: w.set_brightness(val), on_panel)

    def set_volume(self, volume: int, mac: str) -> bool:
        val = max(0, min(15, int(volume)))
        logger.info("GUI Action: volume %s on %s", val, mac)
        return self._level_write(
            mac, "set_volume", lambda w: w.set_volume(val), lambda p: p.music.set_volume(val))
