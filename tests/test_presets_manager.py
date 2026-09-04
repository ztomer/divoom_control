"""Coverage for divoom_gui/presets_manager.py.

Exercises the presets.json migration, load_config()'s per-section try/except
degradation, save/load of named presets and LAN devices, and the
export/import + file-dialog helpers (webview mocked). Follows the existing
convention in test_r42_fixes.py / test_r42_backup_restore.py: a bare
``Host(PresetsManagerMixin)`` plus ``monkeypatch.setattr(Path, "home", ...)``
pointed at ``tmp_path`` so nothing touches the user's real
``~/.config/divoom-control``.

Guardrail: ``_get_presets_file()``'s migration step reads
``Path(__file__).parent / "presets.json"`` — i.e. the *real*
``divoom_gui/presets.json`` checked into this repo — as the migration
source. Tests that exercise the migration branch monkeypatch the module's
``__file__`` global to a fake location under ``tmp_path`` so they never read
or (worse) ``unlink()`` the real repo file.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_gui import presets_manager
from divoom_gui.presets_manager import PresetsManagerMixin  # noqa: F401
from tests.support.presets_manager_common import (  # noqa: F401
    Host,
    _cfg_dir,
    home,
)
class _FakeCreds:
    def __init__(self, valid=True, email="cloud@example.com"):
        self._valid = valid
        self.email = email

    def is_valid(self):
        return self._valid


# ── _get_presets_file migration (lines 19-25) ──────────────────────────────

def test_get_presets_file_migrates_old_file(home, monkeypatch):
    tmp_path = home
    fake_gui_dir = Path(presets_manager.__file__).parent
    old_path = fake_gui_dir / "presets.json"
    old_path.write_text(json.dumps({"legacy": True}), encoding="utf-8")

    h = Host()
    result = h._get_presets_file()

    assert result == tmp_path / ".config" / "divoom-control" / "presets.json"
    assert result.exists()
    assert json.loads(result.read_text(encoding="utf-8")) == {"legacy": True}
    assert not old_path.exists(), "migration must remove the old file"


def test_get_presets_file_no_migration_when_new_already_exists(home):
    tmp_path = home
    fake_gui_dir = Path(presets_manager.__file__).parent
    old_path = fake_gui_dir / "presets.json"
    old_path.write_text(json.dumps({"legacy": True}), encoding="utf-8")

    cfg_dir = _cfg_dir(tmp_path)
    new_path = cfg_dir / "presets.json"
    new_path.write_text(json.dumps({"current": True}), encoding="utf-8")

    h = Host()
    result = h._get_presets_file()

    assert json.loads(result.read_text(encoding="utf-8")) == {"current": True}
    assert old_path.exists(), "must not touch old file when new already exists"


def test_get_presets_file_migration_failure_is_logged_not_raised(home, monkeypatch):
    tmp_path = home
    fake_gui_dir = Path(presets_manager.__file__).parent
    old_path = fake_gui_dir / "presets.json"
    old_path.write_text(json.dumps({"legacy": True}), encoding="utf-8")

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _boom)

    h = Host()
    result = h._get_presets_file()  # must not raise

    assert result == tmp_path / ".config" / "divoom-control" / "presets.json"
    assert old_path.exists(), "failed migration must leave the old file in place"


# ── save_credentials exception path (lines 63-65) ──────────────────────────

def test_save_credentials_returns_false_on_exception(home, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(presets_manager, "atomic_write_config", _boom)
    h = Host()
    assert h.save_credentials("me@example.com", "pw") is False


# ── load_config: presets branch, devices cache branch, cloud block ────────

def test_load_config_no_config_file_uses_defaults(home):
    """config_file.exists() False branch (93->103)."""
    h = Host()
    data = json.loads(h.load_config())
    assert data["email"] == ""
    assert data["cloud_connected"] is False


def test_load_config_loads_and_filters_slots(home):
    """Happy-path slot filtering: drops null value, missing name, and the
    mock MAC placeholder; keeps a valid slot (lines 106-117)."""
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text(json.dumps({
        "_last_active_slots_": {
            "AA:11:22:33:44:55": {"name": "Living Room", "x": 0},
            "BB:00:00:00:00:00": None,
            "CC:00:00:00:00:00": {"x": 1},  # missing name
            "AA:BB:CC:DD:EE:FF": {"name": "mock", "x": 2},  # placeholder mac
        }
    }), encoding="utf-8")

    h = Host()
    data = json.loads(h.load_config())
    assert data["slots"] == {"AA:11:22:33:44:55": {"name": "Living Room", "x": 0}}


def test_load_config_corrupt_presets_file_degrades_to_empty_slots(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text("{ not json !!", encoding="utf-8")

    h = Host()
    data = json.loads(h.load_config())
    assert data["slots"] == {}


def test_load_config_reads_devices_cache(home):
    """devices_cache_file exists branch, happy path (lines 122-125)."""
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "discovered_devices.json").write_text(
        json.dumps([{"mac": "AA:11:22:33:44:55", "name": "Dev"}]), encoding="utf-8"
    )
    h = Host()
    data = json.loads(h.load_config())
    assert data["devices"] == [{"mac": "AA:11:22:33:44:55", "name": "Dev"}]


def test_load_config_corrupt_devices_cache_degrades_to_empty_list(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "discovered_devices.json").write_text("not json", encoding="utf-8")
    h = Host()
    data = json.loads(h.load_config())
    assert data["devices"] == []


def test_load_config_cloud_connected_uses_creds_email(home):
    """cloud_connected block, creds has its own email (lines 130-131)."""
    h = Host(cached_creds=_FakeCreds(valid=True, email="creds@example.com"))
    data = json.loads(h.load_config())
    assert data["cloud_connected"] is True
    assert data["cloud_email"] == "creds@example.com"


def test_load_config_cloud_connected_falls_back_to_config_email(home):
    """creds valid but has no usable .email attr -> falls back to config.ini
    email (the `hasattr(...) and self.cached_creds.email` False arm)."""
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "config.ini").write_text("[divoom]\nemail = cfg@example.com\n", encoding="utf-8")

    creds = _FakeCreds(valid=True, email="")  # falsy email attr present
    h = Host(cached_creds=creds)
    data = json.loads(h.load_config())
    assert data["cloud_connected"] is True
    assert data["cloud_email"] == "cfg@example.com"


def test_load_config_no_cached_creds(home):
    h = Host(cached_creds=None)
    data = json.loads(h.load_config())
    assert data["cloud_connected"] is False
    assert data["cloud_email"] == ""


def test_load_config_outer_exception_returns_empty_json(home, monkeypatch):
    """Outer except (lines 146-148): the first json.dumps() call (building
    the success payload) raises; the except handler's own json.dumps({})
    call must still succeed and return '{}'."""
    orig_dumps = json.dumps
    state = {"first": True}

    def _flaky_dumps(*a, **k):
        if state["first"]:
            state["first"] = False
            raise RuntimeError("boom")
        return orig_dumps(*a, **k)

    monkeypatch.setattr(json, "dumps", _flaky_dumps)
    h = Host()
    assert h.load_config() == orig_dumps({})


# ── save_preset (lines 156-168) ────────────────────────────────────────────

def test_save_preset_corrupt_existing_file_is_overwritten(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text("{ corrupt", encoding="utf-8")

    h = Host()
    assert h.save_preset("New Preset", json.dumps({"AA": {"x": 1}})) is True
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert data == {"New Preset": {"AA": {"x": 1}}}


def test_save_preset_exception_returns_false(home, monkeypatch):
    monkeypatch.setattr(presets_manager, "atomic_write_text",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))
    h = Host()
    assert h.save_preset("X", json.dumps({})) is False


# ── load_preset_names (lines 179-184) ──────────────────────────────────────

def test_load_preset_names_corrupt_file_returns_empty(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text("not json", encoding="utf-8")
    h = Host()
    assert json.loads(h.load_preset_names()) == []


def test_load_preset_names_excludes_reserved_keys(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text(json.dumps({
        "Wall A": {}, "_last_active_slots_": {}, "lan_devices": []
    }), encoding="utf-8")
    h = Host()
    assert json.loads(h.load_preset_names()) == ["Wall A"]


def test_load_preset_names_outer_exception_returns_empty(home, monkeypatch):
    monkeypatch.setattr(presets_manager.PresetsManagerMixin, "_get_presets_file",
                         lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    h = Host()
    assert json.loads(h.load_preset_names()) == []


# ── load_preset_by_name (lines 191-200) ────────────────────────────────────

def test_load_preset_by_name_found_and_missing(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text(json.dumps({"Wall A": {"AA": {"x": 1}}}), encoding="utf-8")
    h = Host()
    assert json.loads(h.load_preset_by_name("Wall A")) == {"AA": {"x": 1}}
    assert json.loads(h.load_preset_by_name("Missing")) == {}


def test_load_preset_by_name_corrupt_file_returns_empty(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text("not json", encoding="utf-8")
    h = Host()
    assert json.loads(h.load_preset_by_name("Wall A")) == {}


def test_load_preset_by_name_outer_exception_returns_empty(home, monkeypatch):
    monkeypatch.setattr(presets_manager.PresetsManagerMixin, "_get_presets_file",
                         lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    h = Host()
    assert json.loads(h.load_preset_by_name("Wall A")) == {}


# ── load_lan_devices (lines 207-216) ───────────────────────────────────────

def test_load_lan_devices_no_file_returns_empty(home):
    """presets_file.exists() False branch (207->213)."""
    h = Host()
    assert json.loads(h.load_lan_devices()) == []


def test_load_lan_devices_happy_path(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text(json.dumps({"lan_devices": [{"ip": "1.2.3.4", "token": 9}]}),
                                           encoding="utf-8")
    h = Host()
    assert json.loads(h.load_lan_devices()) == [{"ip": "1.2.3.4", "token": 9}]


def test_load_lan_devices_corrupt_file_returns_empty(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    (cfg_dir / "presets.json").write_text("not json", encoding="utf-8")
    h = Host()
    assert json.loads(h.load_lan_devices()) == []


def test_load_lan_devices_outer_exception_returns_empty(home, monkeypatch):
    monkeypatch.setattr(presets_manager.PresetsManagerMixin, "_get_presets_file",
                         lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    h = Host()
    assert json.loads(h.load_lan_devices()) == []


# ── add_lan_device (lines 224-236, both any() arms) ────────────────────────

def test_add_lan_device_corrupt_file_starts_fresh(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text("not json", encoding="utf-8")
    h = Host()
    assert h.add_lan_device("1.2.3.4", 1) is True
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert data["lan_devices"] == [{"ip": "1.2.3.4", "token": 1}]


def test_add_lan_device_skips_duplicate_ip(home):
    """any(...) True arm: existing ip is not appended again (229->231)."""
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text(json.dumps({"lan_devices": [{"ip": "1.2.3.4", "token": 1}]}), encoding="utf-8")
    h = Host()
    assert h.add_lan_device("1.2.3.4", 999) is True
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert data["lan_devices"] == [{"ip": "1.2.3.4", "token": 1}]  # unchanged


def test_add_lan_device_appends_new_ip(home):
    """any(...) False arm: new ip is appended (229->231)."""
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text(json.dumps({"lan_devices": [{"ip": "1.2.3.4", "token": 1}]}), encoding="utf-8")
    h = Host()
    assert h.add_lan_device("5.6.7.8", 2) is True
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert {"ip": "5.6.7.8", "token": 2} in data["lan_devices"]
    assert len(data["lan_devices"]) == 2


def test_add_lan_device_exception_returns_false(home, monkeypatch):
    monkeypatch.setattr(presets_manager, "atomic_write_text",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))
    h = Host()
    assert h.add_lan_device("1.2.3.4", 1) is False


# ── delete_lan_device (lines 243-255) ──────────────────────────────────────

def test_delete_lan_device_corrupt_file_starts_fresh(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text("not json", encoding="utf-8")
    h = Host()
    assert h.delete_lan_device("1.2.3.4") is True
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert data["lan_devices"] == []


def test_delete_lan_device_removes_matching_ip(home):
    tmp_path = home
    cfg_dir = _cfg_dir(tmp_path)
    presets_file = cfg_dir / "presets.json"
    presets_file.write_text(json.dumps({"lan_devices": [
        {"ip": "1.2.3.4", "token": 1}, {"ip": "5.6.7.8", "token": 2}
    ]}), encoding="utf-8")
    h = Host()
    assert h.delete_lan_device("1.2.3.4") is True
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    assert data["lan_devices"] == [{"ip": "5.6.7.8", "token": 2}]


def test_delete_lan_device_exception_returns_false(home, monkeypatch):
    monkeypatch.setattr(presets_manager, "atomic_write_text",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))
    h = Host()
    assert h.delete_lan_device("1.2.3.4") is False
