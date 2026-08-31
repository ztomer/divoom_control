import json
import logging
from pathlib import Path
import configparser
from divoom_lib import divoom_auth
from divoom_lib.utils.atomic_io import atomic_write_text, atomic_write_config  # A1

logger = logging.getLogger("divoom_gui")

class PresetsManagerMixin:
    def _get_presets_file(self) -> Path:
        """Return path to presets.json under the user config directory.
        Migrates presets.json from the local gui folder if needed.
        """
        config_dir = Path.home() / ".config" / "divoom-control"
        config_dir.mkdir(parents=True, exist_ok=True)
        new_path = config_dir / "presets.json"
        old_path = Path(__file__).parent / "presets.json"
        if old_path.exists() and not new_path.exists():
            try:
                new_path.write_text(old_path.read_text(encoding="utf-8"), encoding="utf-8")
                old_path.unlink()
                logger.info("Migrated presets.json to ~/.config/divoom-control/")
            except Exception as e:
                logger.warning(f"Failed to migrate presets.json: {e}")
        return new_path

    def save_credentials(self, email: str, password: str) -> bool:
        """Hand the account to the daemon, which owns the credential store.

        R72 P1.1. This used to write config.ini itself and then log in through
        `divoom_lib.divoom_auth` -- a full second implementation of a store the
        daemon already has. Both of the hard-won rules that lived here now live
        in `cloud_store::save_config`, where every client gets them:

        * an EMPTY password means "keep the stored one". The settings form never
          re-populates that field, so a plain re-save submits "" -- and
          overwriting with it erased the credential, after which the next token
          expiry degraded the account to a guest login;
        * a re-login is only FORCED when a new password was actually supplied,
          because forcing one without a password falls back to guest.

        The daemon also had to learn not to destroy the rest of config.ini,
        which it did before this round. Moving a duplicate is not safe until the
        survivor is at least as good as what it replaces.
        """
        logger.info(f"GUI Action: Saving cloud credentials for {email}...")
        try:
            client = self._client()
            if client is None:
                logger.error("Cannot save credentials: no daemon available")
                return False
            self.cached_creds = client.save_credentials(email, password)
            return bool(self.cached_creds and self.cached_creds.is_valid())
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            return False

    def load_config(self) -> str:
        logger.info("GUI Action: Loading configurations...")
        try:
            from divoom_client.daemon_config import DEFAULT_SCAN_TIMEOUT, DEFAULT_SCAN_LIMIT
            default_timeout, default_limit = int(DEFAULT_SCAN_TIMEOUT), DEFAULT_SCAN_LIMIT
            config_file = Path.home() / ".config" / "divoom-control" / "config.ini"
            cfg = configparser.ConfigParser()
            email = ""
            timeout = default_timeout
            limit = default_limit
            lan_ip = ""
            lan_token = 0
            
            last_connected_device = ""
            last_detected_count = 0
            
            # Per-field int coercion that degrades to the default instead of
            # throwing: a single non-numeric field (corrupt/hand-edited
            # config.ini) used to escape to the outer except and return {} —
            # wiping email, slots, devices and cloud status along with it.
            def _safe_int(value: str, default: int) -> int:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default

            if config_file.exists():
                cfg.read(config_file)
                email = cfg.get("divoom", "email", fallback="")
                timeout = _safe_int(cfg.get("gui", "timeout", fallback=str(default_timeout)), default_timeout)
                limit = _safe_int(cfg.get("gui", "limit", fallback=str(default_limit)), default_limit)
                last_connected_device = cfg.get("gui", "last_connected_device", fallback="")
                last_detected_count = _safe_int(cfg.get("gui", "last_detected_count", fallback="0"), 0)
                lan_ip = cfg.get("lan", "device_ip", fallback="")
                lan_token = _safe_int(cfg.get("lan", "local_token", fallback="0"), 0)
                
            presets_file = self._get_presets_file()
            slots = {}
            if presets_file.exists():
                try:
                    data = json.loads(presets_file.read_text(encoding="utf-8"))
                    raw_slots = data.get("_last_active_slots_", {})
                    # Drop stale/placeholder slots (null value, missing name, or
                    # the mock "AA:BB:CC:DD:EE:FF" address) so the canvas never
                    # shows an "undefined" device.
                    slots = {
                        mac: s for mac, s in (raw_slots or {}).items()
                        if isinstance(s, dict) and s.get("name") and mac and mac != "AA:BB:CC:DD:EE:FF"
                    }
                except Exception:
                    pass
            
            devices_cache_file = Path.home() / ".config" / "divoom-control" / "discovered_devices.json"
            cached_devices = []
            if devices_cache_file.exists():
                try:
                    cached_devices = json.loads(devices_cache_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
                    
            cloud_connected = False
            cloud_email = ""
            # R72 P1.1: ask the DAEMON for its cached login, here rather than at
            # startup. Cache-only on purpose -- `get_cached_credentials` cannot
            # go to the network, so opening Settings never blocks behind a cloud
            # round trip. A failure just means "not signed in yet".
            if self.cached_creds is None:
                try:
                    client = self._client()
                    if client is not None:
                        self.cached_creds = client.get_cached_credentials()
                except Exception as exc:
                    logger.debug("cached credentials unavailable: %s", exc)
            if self.cached_creds and self.cached_creds.is_valid():
                cloud_connected = True
                cloud_email = self.cached_creds.email if (hasattr(self.cached_creds, "email") and self.cached_creds.email) else email

            return json.dumps({
                "email": email,
                "timeout": timeout,
                "limit": limit,
                "last_connected_device": last_connected_device,
                "slots": slots,
                "lan_ip": lan_ip,
                "lan_token": lan_token,
                "devices": cached_devices,
                "cloud_connected": cloud_connected,
                "cloud_email": cloud_email,
                "last_detected_count": last_detected_count
            })
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return json.dumps({})

    def save_preset(self, name: str, slots_json: str) -> bool:
        logger.info(f"GUI Action: Saving layout preset '{name}'...")
        try:
            presets_file = self._get_presets_file()
            presets = {}
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            presets[name] = json.loads(slots_json)
            # R42 §5 / A1: atomic write — a crash mid-write must not corrupt the
            # shared presets file (a corrupt file used to cascade into
            # update_wall_slots wiping every saved preset).
            atomic_write_text(presets_file, json.dumps(presets, indent=2))
            return True
        except Exception as e:
            logger.error(f"Failed to save preset: {e}")
            return False

    def load_preset_names(self) -> str:
        logger.info("GUI Action: Loading preset names...")
        try:
            presets_file = self._get_presets_file()
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                    names = [k for k in presets.keys() if k != "_last_active_slots_" and k != "lan_devices"]
                    return json.dumps(names)
                except Exception:
                    pass
            return json.dumps([])
        except Exception as e:
            logger.error(f"Failed to load preset names: {e}")
            return json.dumps([])

    def load_preset_by_name(self, name: str) -> str:
        logger.info(f"GUI Action: Loading preset '{name}'...")
        try:
            presets_file = self._get_presets_file()
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                    slots = presets.get(name, {})
                    return json.dumps(slots)
                except Exception:
                    pass
            return json.dumps({})
        except Exception as e:
            logger.error(f"Failed to load preset '{name}': {e}")
            return json.dumps({})

    def load_lan_devices(self) -> str:
        logger.info("GUI Action: Loading LAN devices...")
        try:
            presets_file = self._get_presets_file()
            devices = []
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                    devices = presets.get("lan_devices", [])
                except Exception:
                    pass
            return json.dumps(devices)
        except Exception as e:
            logger.error(f"Failed to load LAN devices: {e}")
            return json.dumps([])

    def add_lan_device(self, ip: str, token: int) -> bool:
        logger.info(f"GUI Action: Adding LAN device ip={ip} token={token}...")
        try:
            presets_file = self._get_presets_file()
            presets = {}
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            devices = presets.get("lan_devices", [])
            if not any(d.get("ip") == ip for d in devices):
                devices.append({"ip": ip, "token": token})
            presets["lan_devices"] = devices
            atomic_write_text(presets_file, json.dumps(presets, indent=2))
            return True
        except Exception as e:
            logger.error(f"Failed to add LAN device: {e}")
            return False

    def delete_lan_device(self, ip: str) -> bool:
        logger.info(f"GUI Action: Deleting LAN device ip={ip}...")
        try:
            presets_file = self._get_presets_file()
            presets = {}
            if presets_file.exists():
                try:
                    presets = json.loads(presets_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            devices = presets.get("lan_devices", [])
            devices = [d for d in devices if d.get("ip") != ip]
            presets["lan_devices"] = devices
            atomic_write_text(presets_file, json.dumps(presets, indent=2))
            return True
        except Exception as e:
            logger.error(f"Failed to delete LAN device: {e}")
            return False

    def export_settings_dialog(self) -> bool:
        logger.info("Opening save file dialog for settings export...")
        try:
            import webview
            window = getattr(self, "window", None)
            if not window:
                logger.error("No webview window reference available in PresetsManagerMixin.")
                return False
            
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename="divoom_settings_backup.json",
                file_types=('JSON files (*.json)', 'All files (*.*)')
            )
            
            path = result[0] if isinstance(result, list) else result
            if not path:
                logger.info("Export cancelled by user.")
                return False
                
            return self._export_settings_to_path(path)
        except Exception as e:
            logger.error(f"Error opening export file dialog: {e}")
            return False

    def _export_settings_to_path(self, path: str) -> bool:
        logger.info(f"Exporting settings to {path}...")
        try:
            config_dir = Path.home() / ".config" / "divoom-control"
            data = {}
            
            # 1. presets.json
            presets_file = config_dir / "presets.json"
            if presets_file.exists():
                try:
                    data["presets"] = json.loads(presets_file.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"Failed to read presets.json for export: {e}")
                    
            # 2. config.ini
            config_file = config_dir / "config.ini"
            if config_file.exists():
                data["config_ini"] = config_file.read_text(encoding="utf-8")
                
            # 3. alarms.json
            alarms_file = config_dir / "alarms.json"
            if alarms_file.exists():
                try:
                    data["alarms"] = json.loads(alarms_file.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"Failed to read alarms.json for export: {e}")
                    
            # 4. hotchannel.json
            hotchannel_file = config_dir / "hotchannel.json"
            if hotchannel_file.exists():
                try:
                    data["hotchannel"] = json.loads(hotchannel_file.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"Failed to read hotchannel.json for export: {e}")
                    
            # 5. notification_routing.json
            routing_file = config_dir / "notification_routing.json"
            if routing_file.exists():
                try:
                    data["notification_routing"] = json.loads(routing_file.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"Failed to read notification_routing.json for export: {e}")

            atomic_write_text(Path(path), json.dumps(data, indent=2))
            logger.info("Export completed successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to export settings: {e}")
            return False

    def import_settings_dialog(self) -> bool:
        logger.info("Opening open file dialog for settings import...")
        try:
            import webview
            window = getattr(self, "window", None)
            if not window:
                logger.error("No webview window reference available in PresetsManagerMixin.")
                return False
            
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=('JSON files (*.json)', 'All files (*.*)')
            )
            
            path = result[0] if (isinstance(result, list) and len(result) > 0) else result
            if not path:
                logger.info("Import cancelled by user.")
                return False
                
            return self._import_settings_from_path(path)
        except Exception as e:
            logger.error(f"Error opening import file dialog: {e}")
            return False

    def _import_settings_from_path(self, path: str) -> bool:
        logger.info(f"Importing settings from {path}...")
        try:
            backup_data = json.loads(Path(path).read_text(encoding="utf-8"))
            config_dir = Path.home() / ".config" / "divoom-control"
            config_dir.mkdir(parents=True, exist_ok=True)
            
            # Restore presets.json
            if "presets" in backup_data:
                atomic_write_text(config_dir / "presets.json",
                                  json.dumps(backup_data["presets"], indent=2))

            # Restore config.ini (holds the cloud password → 0600)
            if "config_ini" in backup_data:
                atomic_write_text(config_dir / "config.ini",
                                  backup_data["config_ini"], mode=0o600)

            # Restore alarms.json
            if "alarms" in backup_data:
                atomic_write_text(config_dir / "alarms.json",
                                  json.dumps(backup_data["alarms"], indent=2))

            # Restore hotchannel.json
            if "hotchannel" in backup_data:
                atomic_write_text(config_dir / "hotchannel.json",
                                  json.dumps(backup_data["hotchannel"], indent=2))

            # Restore notification_routing.json
            if "notification_routing" in backup_data:
                atomic_write_text(config_dir / "notification_routing.json",
                                  json.dumps(backup_data["notification_routing"], indent=2))
                
            logger.info("Import completed successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to import settings: {e}")
            return False

