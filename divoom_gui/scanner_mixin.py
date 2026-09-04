# divoom_gui/scanner_mixin.py
#
# R17 P5 full cutover: the GUI no longer touches the BLE radio. Scanning,
# connecting (BLE + LAN), and the multi-device wall are all owned by the
# daemon; this mixin is a thin client that issues daemon RPCs and stores
# `current_divoom`/`wall_instance` as DaemonDeviceProxy handles.

import os
import json
import logging
from pathlib import Path

from divoom_gui.daemon_bridge import DaemonDeviceProxy
from divoom_lib.utils.atomic_io import atomic_write_text, atomic_write_config

logger = logging.getLogger("divoom_gui")

class ScannerMixin:
    """Bluetooth scanning, discovery, and device selection — via the daemon."""
    def save_scan_settings(self, timeout: int, limit: int) -> bool:
        try:
            import configparser
            config_file = Path.home() / ".config" / "divoom-control" / "config.ini"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            cfg = configparser.ConfigParser()
            if config_file.exists():
                cfg.read(config_file)
            if "gui" not in cfg:
                cfg["gui"] = {}
            cfg["gui"]["timeout"] = str(int(timeout))
            cfg["gui"]["limit"] = str(int(limit))
            atomic_write_config(config_file, cfg, mode=0o600)  # holds creds
            return True
        except Exception as e:
            logger.warning(f"Failed to save scan config: {e}")
            return False

    def get_last_connect_error(self) -> str:
        """BLE Hardening P1: the actionable reason from the most recent failed
        connect (empty if none / last connect succeeded)."""
        return getattr(self, "_last_connect_error", "") or ""

    def set_device_activity(self, mac: str, kind: str, name: str = "",
                            preview: str = "") -> bool:
        """R46 #3 / R50: tell the daemon what a device is showing so the menubar
        can render a per-device tile. ``preview`` is an optional PNG data URL for
        the tile thumbnail. Best-effort (a missing daemon is fine)."""
        try:
            client = self._client()
            if client is None:
                return False
            return bool(client.set_device_activity(
                mac, kind, name or None, preview or None).get("success"))
        except Exception as e:
            logger.debug(f"set_device_activity failed: {e}")
            return False

    def get_device_activity(self) -> str:
        """R47: what each device the daemon owns is doing — JSON
        ``{mac: {name, kind, at}}``. Lets the GUI surface daemon-owned /
        streaming devices in the selector even when a scan missed them (they're
        connected, hence not advertising)."""
        try:
            client = self._client()
            if client is None:
                return "{}"
            return json.dumps(client.get_device_activity().get("activity", {}) or {})
        except Exception as e:
            logger.debug(f"get_device_activity failed: {e}")
            return "{}"

    def get_connection_state(self) -> str:
        """BLE Hardening P6: the daemon's honest connection_state for the active
        device, for the appbar heartbeat. Returns JSON
        ``{"connected": bool, "state": "connected"|"degraded"|"disconnected"}``;
        a missing/unreachable daemon reads as disconnected.

        The honest ``state`` wins over a stale ``connected`` flag: a device
        reporting ``state: "disconnected"`` is forced to ``connected: False`` so
        the UI never shows a green "connected" dot for a link that's down
        (defense-in-depth — the frontend's ``refreshConnectionState`` enforces
        the same, but the data source itself must be honest)."""
        try:
            client = self._client()
            if client is None:
                return json.dumps({"connected": False, "state": "disconnected"})
            status = client.device_status() or {}
            state = status.get("connection_state", "disconnected")
            connected = bool(status.get("connected"))
            if state == "disconnected":
                connected = False
            return json.dumps({"connected": connected, "state": state})
        except Exception as e:
            logger.debug(f"get_connection_state failed: {e}")
            return json.dumps({"connected": False, "state": "disconnected"})

    # ── Daemon health / reconnect (R53) ───────────────────────────────
    #
    # The daemon is the sole device owner and is deliberately killed on quit
    # (keep_daemon_alive defaults False), so a restart MUST respawn it. The eager
    # launch spawn can fail silently; if it does nothing works and the user had
    # no indication and no way to recover. These two methods back the frontend's
    # daemon-down banner: a fast liveness probe (no spawn — so it can tell
    # "daemon down" from "no device connected", which get_connection_state above
    # conflates) and an explicit reconnect that resets the cached client.

    def daemon_health(self) -> str:
        """Fast, honest daemon liveness for the frontend heartbeat. Probes the
        socket WITHOUT spawning so "daemon down" is distinguishable from "device
        disconnected". Returns JSON ``{"daemon": bool}``. A configured remote
        daemon (DIVOOM_DAEMON_HOST) is never spawned locally — report it healthy
        and let real calls surface any transport error."""
        if os.environ.get("DIVOOM_DAEMON_HOST"):
            return json.dumps({"daemon": True})
        try:
            from divoom_gui.daemon_bridge import daemon_alive
            alive = bool(daemon_alive())
        except Exception as e:
            logger.debug(f"daemon_health failed: {e}")
            alive = False
        if alive:
            return json.dumps({"daemon": True})
        # R67: carry the REASON to the banner. "Background service isn't
        # running" is true but unactionable; when the daemon refused to bind it
        # knows exactly why (stale socket cleared automatically, a directory in
        # the way, a permission problem) and wrote it next to the socket.
        payload: dict = {"daemon": False}
        try:
            from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH
            from divoom_client.socket_failure import read_socket_failure
            failure = read_socket_failure(DEFAULT_SOCKET_PATH)
            if failure is not None:
                payload["reason"] = failure.reason
                payload["remedy"] = failure.remedy
                payload["transient"] = failure.transient
        except Exception as e:  # never let diagnosis break liveness reporting
            logger.debug(f"reading socket failure report failed: {e}")
        return json.dumps(payload)

    def reconnect_daemon(self) -> str:
        """Drop the cached client and (re)ensure a live daemon, spawning one if
        needed. Backs the banner's Reconnect button and the frontend's silent
        auto-reconnect. Returns JSON ``{"daemon": bool}``."""
        from divoom_gui.daemon_bridge import ensure_daemon
        self._daemon_client = None
        try:
            client = ensure_daemon()
        except Exception as e:
            logger.warning(f"reconnect_daemon: ensure_daemon failed: {e}")
            client = None
        self._daemon_client = client
        if client is not None:
            logger.info("Daemon reconnected (client re-ensured).")
        return json.dumps({"daemon": client is not None})

    def get_scan_settings(self) -> str:
        """R42 §1: the persisted scan timeout/limit (config.ini [gui]) so the
        Settings inputs restore between sessions — save_scan_settings wrote them
        on every scan but nothing ever read them back."""
        import configparser
        from divoom_client.daemon_config import DEFAULT_SCAN_TIMEOUT, DEFAULT_SCAN_LIMIT
        timeout, limit = int(DEFAULT_SCAN_TIMEOUT), DEFAULT_SCAN_LIMIT
        try:
            config_file = Path.home() / ".config" / "divoom-control" / "config.ini"
            if config_file.exists():
                cfg = configparser.ConfigParser()
                cfg.read(config_file)
                timeout = cfg.getint("gui", "timeout", fallback=timeout)
                limit = cfg.getint("gui", "limit", fallback=limit)
        except Exception as e:
            logger.warning(f"get_scan_settings failed: {e}")
        return json.dumps({"timeout": timeout, "limit": limit})

    def get_known_devices(self) -> str:
        """Return all known devices with a ``detected`` flag indicating whether
        each was seen in the most recent scan. Used by the frontend to render
        known-but-undetected chips."""
        try:
            cache_file = Path.home() / ".config" / "divoom-control" / "discovered_devices.json"
            if not cache_file.exists():
                return json.dumps([])
            known = json.loads(cache_file.read_text(encoding="utf-8"))
            if not isinstance(known, list):
                return json.dumps([])
            detected = set()
            for d in (getattr(self, "discovered_list", None) or []):
                addr = d.get("address") or d.get("ip")
                if addr:
                    detected.add(addr)
            # Annotate and filter: only include devices not in the scan (the
            # scan results are already in discoveredDevices). Include at most
            # one entry per address (if an undetected known device somehow
            # shares an address with a detected one, the detected wins).
            out = []
            seen = set(detected)
            for d in known:
                addr = d.get("address") or d.get("ip")
                if not addr or addr in detected:
                    continue
                if addr in seen:
                    continue
                seen.add(addr)
                out.append({"address": addr, "name": d.get("name", addr),
                            "detected": False})
            return json.dumps(out)
        except Exception as e:
            logger.warning(f"get_known_devices failed: {e}")
            return json.dumps([])

    def scan_devices(self, timeout: int | None = None, limit: int | None = None) -> str:
        # Fall back to the shared daemon config (daemon.ini) when the UI sends
        # nothing, so the scan defaults live in ONE place. The UI normally passes
        # the user's chosen timeout (Divoom scans are slow — 30-60s — hence the
        # large defaults).
        from divoom_client.daemon_config import load_daemon_config
        cfg = load_daemon_config()
        if timeout is None:
            timeout = int(cfg.scan_timeout)
        if limit is None:
            limit = cfg.scan_limit
        logger.info(f"GUI Action: Scanning devices (daemon) timeout={timeout}, limit={limit}...")
        self.save_scan_settings(timeout, limit)

        if os.environ.get("DIVOOM_MOCK_BLE") in ("1", "true", "yes"):
            mock = [{"name": "Pixoo-Mock", "address": "AA:BB:CC:DD:EE:FF"}]
            self.discovered_list = mock
            self._cache_discovered(mock)
            return json.dumps(mock)

        client = self._client()
        if client is None:
            logger.error("Scan failed: no daemon available")
            return json.dumps([])
        reply = client.scan(timeout=float(timeout), limit=int(limit))
        results = reply.get("devices", []) if reply.get("success") else []
        self.discovered_list = results
        self._cache_discovered(results)
        return json.dumps(results)

    def _cache_discovered(self, results: list) -> None:
        try:
            cfg_dir = Path.home() / ".config" / "divoom-control"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cfg_dir / "discovered_devices.json"
            # Merge: preserve existing known devices, update with fresh scan
            known = {}
            if cache_file.exists():
                try:
                    existing = json.loads(cache_file.read_text(encoding="utf-8"))
                    if isinstance(existing, list):
                        for d in existing:
                            addr = d.get("address") or d.get("ip")
                            if addr:
                                known[addr] = d
                except Exception:
                    known = {}
            now = __import__("time").time()
            for d in results:
                addr = d.get("address") or d.get("ip")
                if addr:
                    prev = known.get(addr, {})
                    prev.update(d)
                    prev["first_seen"] = prev.get("first_seen", now)
                    prev["last_seen"] = now
                    known[addr] = prev
            merged = list(known.values())
            atomic_write_text(cache_file, json.dumps(merged, indent=2))
            import configparser
            config_file = cfg_dir / "config.ini"
            cfg = configparser.ConfigParser()
            if config_file.exists():
                cfg.read(config_file)
            if "gui" not in cfg:
                cfg["gui"] = {}
            cfg["gui"]["last_detected_count"] = str(len(results))
            atomic_write_config(config_file, cfg, mode=0o600)
        except Exception as ce:
            logger.warning(f"Failed to cache discovered devices/count: {ce}")

    def connect_single_device(self, address: str) -> bool:
        logger.info(f"GUI Action: Connecting to {address} (daemon-owned)...")
        try:
            if address == "MatrixWall":
                self.current_target_mode = "wall"
                logger.info("Switched to multi-screen display wall mode.")
                self._persist_last_connected(address)
                return True

            self.current_target_mode = "single"

            # R57: a connect click must never target a stale/dead daemon socket.
            # reconnect_daemon() is a cheap no-op when a daemon is already live
            # (it only probes get_status), and respawns one if the process died.
            # The Rust daemon's BleCentral timeout (divoomd/src/
            # central.rs) covers the remaining wedge case (dead CoreBluetooth).
            self.reconnect_daemon()
            client = self._client()
            if client is None:
                logger.error("Connect failed: daemon could not be (re)started")
                return False

            # Drop any prior daemon-owned device first.
            client.disconnect_device()

            if address.startswith("LAN:"):
                ip = address.split("LAN:")[1]
                token = self._lan_token_for(ip)
                reply = client.connect_device(lan_ip=ip, lan_token=token)
            else:
                device_name = self._device_name_for(address)
                reply = client.connect_device(
                    mac=address, device_name=device_name, use_ios_le_protocol=True)

            if not reply.get("success") or not reply.get("connected"):
                # BLE Hardening P1: keep the daemon's actionable message/reason
                # so the GUI toast says WHY (asleep / BT off / held by phone),
                # not just "Failed to connect".
                self._last_connect_error = (
                    reply.get("message") or reply.get("error") or "Could not connect")
                logger.error(f"Daemon connect failed: {reply.get('reason', '')} "
                             f"{reply.get('error', reply)}")
                self.current_divoom = None
                return False

            self.current_divoom = DaemonDeviceProxy(client, target="device")
            if not self.current_divoom.is_connected:
                logger.error("Daemon reported success but device is NOT connected.")
                self.current_divoom = None
                return False

            self._last_connect_error = ""
            self._persist_last_connected(address)
            return True
        except Exception as e:
            logger.error(f"Single connect failed: {e}")
            self._last_connect_error = str(e)
            self.current_divoom = None
            return False

    def _lan_token_for(self, ip: str) -> int:
        presets_file = self._get_presets_file()
        if presets_file.exists():
            try:
                presets = json.loads(presets_file.read_text(encoding="utf-8"))
                for d in presets.get("lan_devices", []):
                    if d.get("ip") == ip:
                        return int(d.get("token", 0))
            except Exception:
                pass
        return 0

    def _device_name_for(self, address: str) -> str | None:
        for d in self.discovered_list:
            if d.get("address") == address:
                return d.get("name")
        try:
            cache_file = Path.home() / ".config" / "divoom-control" / "discovered_devices.json"
            if cache_file.exists():
                for d in json.loads(cache_file.read_text(encoding="utf-8")):
                    if d.get("address") == address:
                        return d.get("name")
        except Exception:
            pass
        return None

    def _persist_last_connected(self, address: str) -> None:
        try:
            import configparser
            config_file = Path.home() / ".config" / "divoom-control" / "config.ini"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            cfg = configparser.ConfigParser()
            if config_file.exists():
                cfg.read(config_file)
            if "gui" not in cfg:
                cfg["gui"] = {}
            cfg["gui"]["last_connected_device"] = address
            atomic_write_config(config_file, cfg, mode=0o600)  # holds creds
            logger.info(f"Saved last active connection: {address}")
        except Exception as save_err:
            logger.warning(f"Failed to persist active connection: {save_err}")

    def update_wall_slots(self, slots_json: str) -> None:
        logger.info(f"GUI Action: Syncing free-form layout slots: {slots_json}")
        self.wall_slots = json.loads(slots_json)
        self.wall_instance = None

        try:
            presets_file = self._get_presets_file()
            presets = {}
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                except Exception as parse_err:
                    # R42 §5: this writer fires on EVERY arranger change; if an
                    # existing file fails to parse (partial write, race), do NOT
                    # plough on with {} — that rewrote presets.json with only
                    # _last_active_slots_ and silently destroyed every saved
                    # preset. Skip this save instead.
                    logger.warning(
                        f"presets.json exists but is unreadable ({parse_err}); "
                        "skipping last-active-slots save to avoid wiping presets")
                    return
            presets["_last_active_slots_"] = self.wall_slots
            # Atomic write so a crash mid-write can't corrupt the file other
            # writers/readers share. The previous hand-rolled version used a
            # FIXED ".json.tmp" name with no fsync — two arranger changes close
            # together (this fires on EVERY change) wrote the same tmp path and
            # could interleave/replace each other's partial file. Use the shared
            # helper (unique temp per call + fsync + os.replace), matching the
            # other writers in this file.
            atomic_write_text(presets_file, json.dumps(presets, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save last active slots: {e}")

    def _rebuild_wall_instance(self, cell_size: int = 16) -> bool:
        if not self.wall_slots:
            return False
        client = self._client()
        if client is None:
            logger.error("Wall build failed: no daemon available")
            return False
        reply = client.wall_configure(self.wall_slots, cell_size=cell_size)
        if not reply.get("success") or not reply.get("wall"):
            logger.error(f"Failed to build display wall: {reply.get('error', reply)}")
            self.wall_instance = None
            return False
        self.wall_instance = DaemonDeviceProxy(client, target="wall")
        return True
