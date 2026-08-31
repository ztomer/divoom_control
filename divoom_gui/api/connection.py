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

    def probe_lan(self) -> str:
        logger.info("GUI Action: Probing LAN transport reachability (daemon)...")
        try:
            client = self._client()
            if client is None:
                return json.dumps({"reachable": False, "detail": "Daemon unavailable."})
            reply = client.probe_lan()
            ip = reply.get("device_ip")
            if not ip and not reply.get("reachable"):
                return json.dumps({"reachable": False, "detail": "No LAN IP configured. Save a device IP first."})
            ok = bool(reply.get("reachable"))
            return json.dumps({
                "reachable": ok,
                "detail": f"{' Connected' if ok else ' Unreachable'} — {ip}:9000",
            })
        except Exception as e:
            return json.dumps({"reachable": False, "detail": str(e)})

    def save_lan_config(self, device_ip: str, local_token: int) -> bool:
        logger.info(f"GUI Action: Saving LAN config ip={device_ip} token={local_token}...")
        try:
            import configparser
            config_file = Path.home() / ".config" / "divoom-control" / "config.ini"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            cfg = configparser.ConfigParser()
            if config_file.exists():
                cfg.read(config_file)
            if "lan" not in cfg:
                cfg["lan"] = {}
            cfg["lan"]["device_ip"] = device_ip
            cfg["lan"]["local_token"] = str(local_token)
            from divoom_lib.utils.atomic_io import atomic_write_config
            atomic_write_config(config_file, cfg, mode=0o600)  # config.ini holds creds
            return True
        except Exception as e:
            logger.error(f"Failed to save LAN config: {e}")
            return False

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