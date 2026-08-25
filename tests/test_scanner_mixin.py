"""Coverage push (R61 #1): divoom_gui/scanner_mixin.py.

ScannerMixin is a thin daemon-RPC client (scan/connect/wall-build); the only
impure boundary is the daemon client (``self._client()``) and the on-disk
config/cache files under ``~/.config/divoom-control``. Both are faked here —
a MagicMock daemon client (never real BLE/network) and a per-test tmp_path
standing in for ``Path.home()`` — so these tests are safe to run in any shell
(no CoreBluetooth, no sockets).
"""
import json
import sys
import configparser
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from tests.support.scanner_support import (  # noqa: F401
    CACHE_REL,
    CONFIG_REL,
    _write_ini,
    host,
)


# ── save_scan_settings ────────────────────────────────────────────────────

def test_save_scan_settings_new_file(host, tmp_path):
    assert host.save_scan_settings(30, 5) is True
    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / CONFIG_REL)
    assert cfg["gui"]["timeout"] == "30"
    assert cfg["gui"]["limit"] == "5"


def test_save_scan_settings_merges_existing_gui_section(host, tmp_path):
    """Covers the exists()==True read branch AND the '"gui" already in cfg'
    branch (no re-creation of the section)."""
    _write_ini(tmp_path, "[gui]\ntimeout = 1\nlast_connected_device = AA:BB\n")
    assert host.save_scan_settings(60, 10) is True
    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / CONFIG_REL)
    assert cfg["gui"]["timeout"] == "60"
    assert cfg["gui"]["limit"] == "10"
    # Untouched sibling key survives the merge.
    assert cfg["gui"]["last_connected_device"] == "AA:BB"


def test_save_scan_settings_exception_returns_false(host, monkeypatch):
    monkeypatch.setattr("divoom_gui.scanner_mixin.atomic_write_config",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert host.save_scan_settings(30, 5) is False


# ── get_last_connect_error ─────────────────────────────────────────────────

def test_get_last_connect_error_default_empty(host):
    assert host.get_last_connect_error() == ""


def test_get_last_connect_error_returns_set_value(host):
    host._last_connect_error = "BLE off"
    assert host.get_last_connect_error() == "BLE off"


# ── set_device_activity ───────────────────────────────────────────────────

def test_set_device_activity_no_client(host):
    host._daemon_client = None
    assert host.set_device_activity("AA:BB", "clock") is False


def test_set_device_activity_success(host):
    client = pytest.importorskip("unittest.mock").MagicMock()
    client.set_device_activity.return_value = {"success": True}
    host._daemon_client = client
    ok = host.set_device_activity("AA:BB", "clock", name="Pixoo", preview="data:x")
    assert ok is True
    client.set_device_activity.assert_called_once_with("AA:BB", "clock", "Pixoo", "data:x")


def test_set_device_activity_exception_returns_false(host):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.set_device_activity.side_effect = RuntimeError("boom")
    host._daemon_client = client
    assert host.set_device_activity("AA:BB", "clock") is False


# ── get_device_activity ───────────────────────────────────────────────────

def test_get_device_activity_no_client(host):
    host._daemon_client = None
    assert host.get_device_activity() == "{}"


def test_get_device_activity_success(host):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.get_device_activity.return_value = {"activity": {"AA:BB": {"kind": "clock"}}}
    host._daemon_client = client
    assert json.loads(host.get_device_activity()) == {"AA:BB": {"kind": "clock"}}


def test_get_device_activity_exception_returns_empty(host):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.get_device_activity.side_effect = RuntimeError("boom")
    host._daemon_client = client
    assert host.get_device_activity() == "{}"


# ── get_scan_settings ──────────────────────────────────────────────────────

def test_get_scan_settings_no_file_uses_defaults(host):
    from divoom_client.daemon_config import DEFAULT_SCAN_TIMEOUT, DEFAULT_SCAN_LIMIT
    out = json.loads(host.get_scan_settings())
    assert out == {"timeout": int(DEFAULT_SCAN_TIMEOUT), "limit": DEFAULT_SCAN_LIMIT}


def test_get_scan_settings_reads_persisted_values(host, tmp_path):
    _write_ini(tmp_path, "[gui]\ntimeout = 42\nlimit = 7\n")
    out = json.loads(host.get_scan_settings())
    assert out == {"timeout": 42, "limit": 7}


def test_get_scan_settings_exception_falls_back_to_defaults(host, tmp_path):
    """A malformed config.ini raises inside the try; the except branch must
    still return sane (default) values rather than propagate."""
    from divoom_client.daemon_config import DEFAULT_SCAN_TIMEOUT, DEFAULT_SCAN_LIMIT
    _write_ini(tmp_path, "not an ini file *** broken\n")
    out = json.loads(host.get_scan_settings())
    assert out == {"timeout": int(DEFAULT_SCAN_TIMEOUT), "limit": DEFAULT_SCAN_LIMIT}


# ── get_known_devices ──────────────────────────────────────────────────────

def test_get_known_devices_no_cache_file(host):
    assert json.loads(host.get_known_devices()) == []


def test_get_known_devices_cache_not_a_list(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert json.loads(host.get_known_devices()) == []


def test_get_known_devices_filters_detected_and_dupes(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps([
        {"address": "AA:11", "name": "Pixoo-1"},   # detected this scan -> excluded
        {"address": "BB:22", "name": "Timoo"},      # undetected -> included
        {"address": "BB:22", "name": "Timoo-dupe"}, # dup addr already in `seen` -> skipped
        {"name": "no-addr-entry"},                  # missing address -> skipped
    ]), encoding="utf-8")
    # discovered_list has one entry with no address (skip branch) and one
    # detected device that should be excluded from the known-undetected list.
    host.discovered_list = [{"name": "no-address-here"}, {"address": "AA:11"}]
    out = json.loads(host.get_known_devices())
    assert out == [{"address": "BB:22", "name": "Timoo", "detected": False}]


# ── scan_devices ───────────────────────────────────────────────────────────

def test_scan_devices_explicit_timeout_and_limit(host, tmp_path):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.scan.return_value = {"success": True, "devices": [{"address": "AA:11", "name": "Pixoo"}]}
    host._daemon_client = client
    out = json.loads(host.scan_devices(timeout=12, limit=3))
    client.scan.assert_called_once_with(timeout=12.0, limit=3)
    assert out == [{"address": "AA:11", "name": "Pixoo"}]


def test_scan_devices_defaults_from_daemon_config(host, tmp_path):
    from unittest.mock import MagicMock
    from divoom_client.daemon_config import load_daemon_config
    cfg = load_daemon_config()
    client = MagicMock()
    client.scan.return_value = {"success": True, "devices": []}
    host._daemon_client = client
    host.scan_devices()
    client.scan.assert_called_once_with(timeout=float(cfg.scan_timeout), limit=cfg.scan_limit)


def test_scan_devices_mock_ble_env(host, monkeypatch, tmp_path):
    monkeypatch.setenv("DIVOOM_MOCK_BLE", "1")
    out = json.loads(host.scan_devices())
    assert out == [{"name": "Pixoo-Mock", "address": "AA:BB:CC:DD:EE:FF"}]
    assert host.discovered_list == out
    assert (tmp_path / CACHE_REL).exists()


def test_scan_devices_no_daemon_returns_empty(host):
    host._daemon_client = None
    assert json.loads(host.scan_devices(timeout=5, limit=1)) == []


def test_scan_devices_failed_reply_returns_empty(host):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.scan.return_value = {"success": False}
    host._daemon_client = client
    assert json.loads(host.scan_devices(timeout=5, limit=1)) == []


# ── _cache_discovered ──────────────────────────────────────────────────────

def test_cache_discovered_existing_not_a_list_is_ignored(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    host._cache_discovered([{"address": "AA:11", "name": "Pixoo"}])
    merged = json.loads(cache_file.read_text(encoding="utf-8"))
    assert merged == [{"address": "AA:11", "name": "Pixoo",
                        "first_seen": merged[0]["first_seen"],
                        "last_seen": merged[0]["last_seen"]}]


def test_cache_discovered_existing_entry_without_address_skipped(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    # One entry has no address (skip branch), one has an address (kept branch)
    # -- exercises both arms of the existing-entries loop in one pass.
    cache_file.write_text(json.dumps([
        {"name": "no-addr"},
        {"address": "CC:33", "name": "Kept"},
    ]), encoding="utf-8")
    host._cache_discovered([])
    merged = json.loads(cache_file.read_text(encoding="utf-8"))
    assert [d["address"] for d in merged] == ["CC:33"]


def test_cache_discovered_malformed_json_falls_back_to_empty(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{ not valid json", encoding="utf-8")
    host._cache_discovered([{"address": "AA:11", "name": "Pixoo"}])
    merged = json.loads(cache_file.read_text(encoding="utf-8"))
    assert len(merged) == 1 and merged[0]["address"] == "AA:11"


def test_cache_discovered_result_without_address_skipped(host, tmp_path):
    host._cache_discovered([{"name": "no-address-result"}])
    cache_file = tmp_path / CACHE_REL
    merged = json.loads(cache_file.read_text(encoding="utf-8"))
    assert merged == []


def test_cache_discovered_reads_existing_config_and_preserves_gui_section(host, tmp_path):
    """Covers config_file.exists()==True (cfg.read) AND the '"gui" already in
    cfg' skip-create branch inside _cache_discovered's count-write."""
    _write_ini(tmp_path, "[gui]\ntimeout = 9\n")
    host._cache_discovered([{"address": "AA:11", "name": "Pixoo"}])
    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / CONFIG_REL)
    assert cfg["gui"]["last_detected_count"] == "1"
    assert cfg["gui"]["timeout"] == "9"


def test_cache_discovered_config_write_exception_is_caught(host, monkeypatch, tmp_path):
    monkeypatch.setattr("divoom_gui.scanner_mixin.atomic_write_config",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    # Should not raise despite the config write failing.
    host._cache_discovered([{"address": "AA:11", "name": "Pixoo"}])
    # The devices cache (a separate atomic_write_text call) still succeeded.
    cache_file = tmp_path / CACHE_REL
    assert json.loads(cache_file.read_text(encoding="utf-8"))[0]["address"] == "AA:11"




# ── _persist_last_connected ─────────────────────────────────────────────

def test_persist_last_connected_writes_config(host, tmp_path):
    host._persist_last_connected("AA:BB:CC:DD:EE:FF")
    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / CONFIG_REL)
    assert cfg["gui"]["last_connected_device"] == "AA:BB:CC:DD:EE:FF"


def test_persist_last_connected_merges_existing_gui_section(host, tmp_path):
    """Covers the exists()==True read branch AND the '"gui" already present'
    skip-create branch."""
    _write_ini(tmp_path, "[gui]\ntimeout = 9\n")
    host._persist_last_connected("AA:BB:CC:DD:EE:FF")
    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / CONFIG_REL)
    assert cfg["gui"]["last_connected_device"] == "AA:BB:CC:DD:EE:FF"
    assert cfg["gui"]["timeout"] == "9"


def test_persist_last_connected_exception_is_caught(host, monkeypatch):
    monkeypatch.setattr("divoom_gui.scanner_mixin.atomic_write_config",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    # Must not raise.
    host._persist_last_connected("AA:BB")


# ── update_wall_slots ────────────────────────────────────────────────────

def test_update_wall_slots_save_exception_is_caught(host, monkeypatch):
    monkeypatch.setattr("divoom_gui.scanner_mixin.atomic_write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    # Must not raise even though persisting _last_active_slots_ fails.
    host.update_wall_slots(json.dumps({"0": {"mac": "AA:BB"}}))
    assert host.wall_slots == {"0": {"mac": "AA:BB"}}
    assert host.wall_instance is None


# ── _rebuild_wall_instance ───────────────────────────────────────────────

def test_rebuild_wall_instance_no_slots(host):
    host.wall_slots = {}
    assert host._rebuild_wall_instance() is False


def test_rebuild_wall_instance_no_daemon(host):
    host.wall_slots = {"0": {"mac": "AA:BB"}}
    host._daemon_client = None
    assert host._rebuild_wall_instance() is False


def test_rebuild_wall_instance_failed_reply(host):
    from unittest.mock import MagicMock
    host.wall_slots = {"0": {"mac": "AA:BB"}}
    client = MagicMock()
    client.wall_configure.return_value = {"success": False, "error": "no such wall"}
    host._daemon_client = client
    assert host._rebuild_wall_instance() is False
    assert host.wall_instance is None
