"""R42 — bug-batch regression tests.

§1 scan-settings persistence read-back, §2 macOS 26 Notification Center DB
discovery, §5 presets non-destructive last-active-slots writer + atomic saves.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))


# ── §1 scan settings read back ─────────────────────────────────────────────

def test_get_scan_settings_reads_persisted_values(tmp_path, monkeypatch):
    from divoom_gui.scanner_mixin import ScannerMixin
    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text("[gui]\ntimeout = 33\nlimit = 7\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    s = json.loads(ScannerMixin().get_scan_settings())
    assert s == {"timeout": 33, "limit": 7}


def test_get_scan_settings_defaults_when_missing(tmp_path, monkeypatch):
    from divoom_gui.scanner_mixin import ScannerMixin
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    s = json.loads(ScannerMixin().get_scan_settings())
    assert s == {"timeout": 20, "limit": 4}


# ── §2 macOS 26 NC DB discovery ────────────────────────────────────────────

def test_nc_db_discovery_includes_macos26_group_container(tmp_path, monkeypatch):
    from divoom_client import macos_notifications as mn
    if not sys.platform.startswith("darwin"):
        pytest.skip("darwin-only discovery")
    db = tmp_path / "Library" / "Group Containers" / "group.com.apple.usernoted" / "db2" / "db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"sqlite")
    monkeypatch.setattr(mn.Path, "home", classmethod(lambda cls: tmp_path))
    # force the DARWIN_USER_DIR candidates to miss
    monkeypatch.setattr(mn.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    assert mn.find_notification_db_path() == db


def test_nc_db_unreadable_raises_actionable_permission_error(tmp_path):
    from divoom_client.macos_notifications import MacNotificationMonitor
    import sqlite3 as _sq
    db = tmp_path / "db"
    db.write_bytes(b"not-a-db")
    m = MacNotificationMonitor(db_path=db)
    with patch.object(_sq, "connect", side_effect=_sq.OperationalError("unable to open database file")):
        with pytest.raises(PermissionError, match="FULL DISK ACCESS"):
            m.start(lambda *a: None)


# ── §5 presets robustness ─────────────────────────────────────────────────

class _Host:
    """Minimal host carrying the mixin methods under test."""
    def __init__(self, presets_file):
        self._file = presets_file
        self.wall_slots = {}
        self.wall_instance = None

    def _get_presets_file(self):
        return self._file


def test_update_wall_slots_does_not_wipe_presets_on_corrupt_file(tmp_path):
    from divoom_gui.scanner_mixin import ScannerMixin
    f = tmp_path / "presets.json"
    f.write_text("{ corrupted json !!!")
    host = _Host(f)
    ScannerMixin.update_wall_slots(host, json.dumps({"AA": {"x": 0}}))
    # The corrupt file must be left untouched — NOT rewritten with only
    # _last_active_slots_ (the old behavior destroyed every named preset).
    assert f.read_text() == "{ corrupted json !!!"


def test_update_wall_slots_preserves_named_presets(tmp_path):
    from divoom_gui.scanner_mixin import ScannerMixin
    f = tmp_path / "presets.json"
    f.write_text(json.dumps({"My Wall": {"AA": {"x": 1}}}))
    host = _Host(f)
    ScannerMixin.update_wall_slots(host, json.dumps({"BB": {"x": 2}}))
    data = json.loads(f.read_text())
    assert data["My Wall"] == {"AA": {"x": 1}}          # named preset intact
    assert data["_last_active_slots_"] == {"BB": {"x": 2}}
    assert not (tmp_path / "presets.json.tmp").exists()  # atomic temp cleaned


def test_save_preset_roundtrip_atomic(tmp_path):
    from divoom_gui.presets_manager import PresetsManagerMixin

    class Host(PresetsManagerMixin):
        def _get_presets_file(self):
            return tmp_path / "presets.json"

    h = Host()
    assert h.save_preset("Wall A", json.dumps({"AA": {"x": 0}})) is True
    names = json.loads(h.load_preset_names())
    assert names == ["Wall A"]
    assert not (tmp_path / "presets.json.tmp").exists()


def test_load_config_corrupt_int_field_does_not_wipe_whole_config(tmp_path, monkeypatch):
    """One non-numeric field in config.ini (corrupt / hand-edited) must degrade
    to that field's default — NOT escape to the outer except and return {},
    which silently wiped email, wall slots, devices and cloud status too.

    Teeth: revert the _safe_int() calls back to int(cfg.get(...)) and the bad
    `timeout = abc` raises ValueError out to the `except`, so load_config()
    returns {} and the email/limit assertions below fail with KeyError.
    """
    from divoom_gui.presets_manager import PresetsManagerMixin
    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text(
        "[divoom]\nemail = user@example.com\n"
        "[gui]\ntimeout = abc\nlimit = 7\n"          # timeout corrupt, limit valid
        "[lan]\nlocal_token = notanint\n"            # token corrupt
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    class Host(PresetsManagerMixin):
        cached_creds = None
        def _get_presets_file(self):
            return tmp_path / "presets.json"

    data = json.loads(Host().load_config())
    assert data["email"] == "user@example.com"  # whole config survives
    assert data["timeout"] == 20                # corrupt -> default
    assert data["limit"] == 7                   # valid   -> parsed
    assert data["lan_token"] == 0               # corrupt -> default
