"""gallery_sync coverage: sync_artwork, sync candidates/targets, hot-channel
config and gallery style/filter persistence (split from
test_gallery_sync_coverage.py)."""
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.support.gallery_sync_common import (  # noqa: F401
    _Host,
    _wait_for_fetch_thread,
)


# ───────────────────── batch_sync_artwork / _sync_artwork_detailed ─────────────────────

def test_sync_artwork_no_daemon_available():
    m = _Host()
    m._daemon_client = None
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "abc"}))
    assert ok is False
    assert err == "no daemon available"
    assert m.batch_sync_artwork(json.dumps({"file_id": "abc"})) is False


def test_sync_artwork_wall_mode_rebuild_fails():
    m = _Host()
    m.current_target_mode = "wall"
    m._daemon_client = MagicMock()
    m._rebuild_wall_instance = MagicMock(return_value=False)
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "abc"}))
    assert ok is False
    assert err == "wall not configured"


def test_sync_artwork_wall_mode_success_via_explicit_mode():
    m = _Host()
    m.current_target_mode = "wall"
    fake_client = MagicMock()
    fake_client.sync_artwork.return_value = {"success": True}
    m._daemon_client = fake_client
    m._rebuild_wall_instance = MagicMock(return_value=True)
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "abc"}))
    assert ok is True
    assert err is None
    fake_client.sync_artwork.assert_called_once_with("abc", target="wall")


def test_sync_artwork_wall_mode_inferred_from_no_device_and_wall_slots():
    """current_target_mode="single" but no current_divoom + wall_slots set
    still routes to wall (the `or` arm of the is_wall condition)."""
    m = _Host()
    m.current_divoom = None
    m.wall_slots = {"AA:BB": {"x": 0}}
    fake_client = MagicMock()
    fake_client.sync_artwork.return_value = {"success": True}
    m._daemon_client = fake_client
    m._rebuild_wall_instance = MagicMock(return_value=True)
    ok, _ = m._sync_artwork_detailed(json.dumps({"file_id": "abc"}))
    assert ok is True
    fake_client.sync_artwork.assert_called_once_with("abc", target="wall")


def test_sync_artwork_single_device_connected_uses_active_device_size():
    m = _Host()
    m.current_divoom = MagicMock(is_connected=True, lan=None)
    m._active_device_size = lambda: 32
    fake_client = MagicMock()
    fake_client.sync_artwork.return_value = {"success": True}
    m._daemon_client = fake_client
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "xyz"}))
    assert ok is True
    fake_client.sync_artwork.assert_called_once_with("xyz", default_size=32, target="device")


def test_sync_artwork_single_device_falls_back_to_16_without_size_helper():
    m = _Host()
    m.current_divoom = MagicMock(is_connected=True, lan=None)
    assert not hasattr(m, "_active_device_size")
    fake_client = MagicMock()
    fake_client.sync_artwork.return_value = {"success": True}
    m._daemon_client = fake_client
    m._sync_artwork_detailed(json.dumps({"file_id": "xyz"}))
    fake_client.sync_artwork.assert_called_once_with("xyz", default_size=16, target="device")


def test_sync_artwork_single_device_via_lan_not_ble_connected():
    """is_connected False but a `lan` attribute is truthy -> still routes to
    the single-device path (covers the `or getattr(..., "lan", None)` arm)."""
    m = _Host()
    m.current_divoom = MagicMock(is_connected=False, lan="192.168.1.20")
    fake_client = MagicMock()
    fake_client.sync_artwork.return_value = {"success": True}
    m._daemon_client = fake_client
    ok, _ = m._sync_artwork_detailed(json.dumps({"file_id": "xyz"}))
    assert ok is True
    fake_client.sync_artwork.assert_called_once_with("xyz", default_size=16, target="device")


def test_sync_artwork_no_connected_device():
    m = _Host()
    m.current_divoom = None
    m.wall_slots = {}
    m._daemon_client = MagicMock()
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "abc"}))
    assert ok is False
    assert err == "no connected device"


def test_sync_artwork_reply_failure_with_and_without_error_message():
    m = _Host()
    m.current_divoom = MagicMock(is_connected=True, lan=None)
    m._active_device_size = lambda: 16

    fake_client = MagicMock()
    fake_client.sync_artwork.return_value = {"success": False, "error": "device busy"}
    m._daemon_client = fake_client
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "a"}))
    assert ok is False
    assert err == "device busy"

    fake_client.sync_artwork.return_value = {"success": False}
    ok, err = m._sync_artwork_detailed(json.dumps({"file_id": "a"}))
    assert ok is False
    assert err == "unknown daemon error"


def test_sync_artwork_malformed_json_and_missing_file_id_are_caught():
    m = _Host()
    m._daemon_client = MagicMock()

    ok, err = m._sync_artwork_detailed("{not json")
    assert ok is False
    assert err  # exception message from json.loads

    ok, err = m._sync_artwork_detailed(json.dumps({"no_file_id": True}))
    assert ok is False
    assert "file_id" in err  # KeyError message


# ─────────────────────────── get_sync_candidates ───────────────────────────

def test_get_sync_candidates_merges_and_dedupes_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "discovered_devices.json").write_text(json.dumps([
        {"address": "AA:BB", "name": "Discovered1"},
        {"address": "", "name": "NoAddress"},  # falsy address -> skipped
    ]))
    m.wall_slots = {"AA:BB": {"name": "WallDup"}, "CC:DD": {"name": "WallOnly"}}

    from divoom_lib import hotchannel_config
    hotchannel_config.set_targets(["CC:DD", "EE:FF"])  # EE:FF only via "selected"

    out = json.loads(m.get_sync_candidates())
    addrs = [c["address"] for c in out]
    assert addrs.count("AA:BB") == 1  # deduped across discovered+wall
    assert "CC:DD" in addrs
    assert "EE:FF" in addrs
    by_addr = {c["address"]: c for c in out}
    assert by_addr["AA:BB"]["name"] == "Discovered1"  # first-seen (discovered) wins
    assert by_addr["CC:DD"]["selected"] is True
    assert by_addr["EE:FF"]["name"] == "Divoom Screen"  # no name -> default


def test_get_sync_candidates_handles_malformed_discovered_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "discovered_devices.json").write_text("not json{{{")

    out = json.loads(m.get_sync_candidates())
    assert out == []  # malformed file -> caught, no crash, nothing discovered


# ─────────────────────────── set_sync_targets ───────────────────────────

def test_set_sync_targets_valid_list_and_galleries(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    from divoom_lib import hotchannel_config

    ok = m.set_sync_targets(
        targets_json=json.dumps(["AA:BB", "CC:DD"]),
        galleries_json=json.dumps({"AA:BB": 9}),
    )
    assert ok is True
    assert hotchannel_config.get_targets() == ["AA:BB", "CC:DD"]
    assert hotchannel_config.load_config()["device_galleries"] == {"AA:BB": 9}


def test_set_sync_targets_non_list_and_non_dict_payloads_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    from divoom_lib import hotchannel_config

    ok = m.set_sync_targets(targets_json=json.dumps({"not": "a list"}),
                             galleries_json=json.dumps([1, 2, 3]))
    assert ok is True  # set_targets([]) still succeeds
    assert hotchannel_config.get_targets() == []
    assert hotchannel_config.load_config()["device_galleries"] == {}


def test_set_sync_targets_none_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    ok = m.set_sync_targets(targets_json=None, galleries_json=None)
    assert ok is True


def test_set_sync_targets_malformed_json_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    ok = m.set_sync_targets(targets_json="{not valid json[")
    assert ok is False


# ───────────────────── hot channel config get/save ─────────────────────

def test_get_hot_channel_config_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    cfg = json.loads(m.get_hot_channel_config())
    assert cfg["classify"] == 18
    assert cfg["targets"] == []


def test_save_hot_channel_config_positional_json_string(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    ok = m.save_hot_channel_config(json.dumps({"enabled": True, "interval": 120}))
    assert ok is True
    cfg = json.loads(m.get_hot_channel_config())
    assert cfg["enabled"] is True
    assert cfg["interval"] == 120


def test_save_hot_channel_config_kwargs_style(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    ok = m.save_hot_channel_config(enabled=True, classify=9)
    assert ok is True
    cfg = json.loads(m.get_hot_channel_config())
    assert cfg["classify"] == 9


def test_save_hot_channel_config_swallows_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    with patch("divoom_lib.hotchannel_config.save_config", side_effect=RuntimeError("boom")):
        ok = m.save_hot_channel_config(enabled=True)
    assert ok is False


# ───────────────────────── gallery style persistence ─────────────────────────

def test_get_gallery_style_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert m.get_gallery_style("AABB") == 18


def test_set_and_get_gallery_style_roundtrip(tmp_path, monkeypatch):
    # NOTE: configparser's default delimiters include ":", so device
    # addresses used as ini keys here must not contain a colon (a real
    # MAC-address key would need sanitizing — out of scope for this test).
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert m.set_gallery_style("AABB", 7) is True
    assert m.get_gallery_style("AABB") == 7
    # A different, never-configured device with no "default" key falls back to 18.
    assert m.get_gallery_style("ZZZZ") == 18


def test_get_gallery_style_falls_back_to_default_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert m.set_gallery_style("", 3) is True  # "" -> key "default"
    assert m.get_gallery_style("never-seen-device") == 3


def test_get_gallery_style_exception_path_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text("[gallery]\nAABB = not-an-int\n")
    assert m.get_gallery_style("AABB") == 18


def test_set_gallery_style_preserves_existing_keys_and_handles_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert m.set_gallery_style("AABB", 1) is True
    assert m.set_gallery_style("CCDD", 2) is True  # merges into existing [gallery] section
    assert m.get_gallery_style("AABB") == 1
    assert m.get_gallery_style("CCDD") == 2

    with patch("divoom_gui.gallery_sync.atomic_write_config", side_effect=OSError("disk full")):
        assert m.set_gallery_style("EEFF", 5) is False


# ───────────────────────── gallery filter persistence ─────────────────────────

def test_get_gallery_filter_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert json.loads(m.get_gallery_filter()) == {"sort": 1, "file_size": 0}


def test_set_and_get_gallery_filter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert m.set_gallery_filter(sort=2, file_size=64) is True
    assert json.loads(m.get_gallery_filter()) == {"sort": 2, "file_size": 64}


def test_get_gallery_filter_exception_path_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text("[gallery]\ngallery_sort = not-an-int\n")
    assert json.loads(m.get_gallery_filter()) == {"sort": 1, "file_size": 0}


def test_set_gallery_filter_exception_path_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    with patch("divoom_gui.gallery_sync.atomic_write_config", side_effect=OSError("disk full")):
        assert m.set_gallery_filter(sort=3, file_size=16) is False
