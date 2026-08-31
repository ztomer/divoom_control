"""ConnectionApi — scan/connect/status/LAN (REVIEW §1.2).

Extracts the ScannerMixin surface + daemon lifecycle methods.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from divoom_gui.api import ApiBase

logger = logging.getLogger("divoom_gui.api.connection")


class ConnectionApi(ApiBase):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    # ── ScannerMixin methods ────────────────────────────────────────────

    def scan_devices(self, timeout: float = 10.0) -> str:
        logger.info("GUI Action: Scanning for devices...")
        try:
            client = self._client()   # method form (ConnectionApi shadows the base property)
            if client is None:
                return json.dumps([])
            reply = client.scan(timeout=timeout, limit=4)
            return json.dumps(reply.get("devices", []))
        except Exception as e:
            logger.error(f"Scan failed: {e}")
            return json.dumps([])

    def get_capabilities(self) -> str:
        client = self._client()   # method form (ConnectionApi shadows the base property)
        if client is None:
            return json.dumps({})
        reply = client.device_call("get_capabilities", [], {}, target="device")
        return json.dumps(reply.get("result", {}))

    # ── Daemon lifecycle ────────────────────────────────────────────────

    def _client(self):
        from divoom_gui.daemon_bridge import ensure_daemon
        if self._state_getter().get("_daemon_client") is None:
            self._state_getter()["_daemon_client"] = ensure_daemon()
        return self._state_getter().get("_daemon_client")

    def _device_status(self) -> dict:
        client = self._client()
        if client is None:
            return {"connected": False, "mac": None, "lan_ip": None, "wall": False}
        st = client.device_status()
        return st if st.get("success") else {"connected": False, "mac": None, "lan_ip": None, "wall": False}

    # ── Wall configuration ──────────────────────────────────────────────

    def update_wall_slots(self, json_text: str) -> None:
        import json as _json
        self._state_getter()["wall_slots"] = _json.loads(json_text)

    # ── Window controls ─────────────────────────────────────────────────

    def minimize_window(self) -> None:
        window = self._state_getter().get("window")
        if window:
            window.minimize()

    def maximize_window(self) -> None:
        window = self._state_getter().get("window")
        if window:
            window.toggle_fullscreen()

    def close_window(self) -> None:
        loop_thread = self._loop_thread
        if loop_thread:
            loop_thread.stop()
        window = self._state_getter().get("window")
        if window:
            def _destroy():
                import time
                time.sleep(0.1)
                window.destroy()
            import threading
            threading.Thread(target=_destroy, daemon=True).start()