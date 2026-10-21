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

    # The devices are the app's SETTINGS now — the `[gallery]` table in
    # config.ini, which is where the daemon reads them from too. The table is
    # an INI file, so a key cannot contain ':' (configparser's delimiter):
    # the addresses that live there are the UUID-shaped ones.
    from divoom_lib import settings_devices
    settings_devices.set_registered([
        "2b471aee-a9bd-24ab-7d5f-4afd88c16eeb",
        "e9a41e1e-9a96-974f-ce44-54f16d616f28",
    ])

    out = json.loads(m.get_sync_candidates())
    addrs = [c["address"] for c in out]
    assert addrs.count("AA:BB") == 1  # deduped across discovered+wall
    assert "2b471aee-a9bd-24ab-7d5f-4afd88c16eeb" in addrs
    assert "e9a41e1e-9a96-974f-ce44-54f16d616f28" in addrs
    by_addr = {c["address"]: c for c in out}
    assert by_addr["AA:BB"]["name"] == "Discovered1"  # first-seen (discovered) wins
    assert by_addr["2b471aee-a9bd-24ab-7d5f-4afd88c16eeb"]["selected"] is True
    assert by_addr["e9a41e1e-9a96-974f-ce44-54f16d616f28"]["name"] == "Divoom Screen"  # no name


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
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    from divoom_lib import settings_devices

    ok = m.set_sync_targets(
        targets_json=json.dumps({
            "checked": [
                "a9fccb71-3d3d-4de3-c381-0de382cdc4aa",
                "f90d2cc9-420e-65f9-9e06-f9554470fced",
            ],
            "known": [
                "a9fccb71-3d3d-4de3-c381-0de382cdc4aa",
                "f90d2cc9-420e-65f9-9e06-f9554470fced",
            ],
        }),
        galleries_json=json.dumps({"a9fccb71-3d3d-4de3-c381-0de382cdc4aa": 9}),
    )
    assert ok is True
    assert settings_devices.registered_devices() == [
        ("a9fccb71-3d3d-4de3-c381-0de382cdc4aa", 9),
        ("f90d2cc9-420e-65f9-9e06-f9554470fced", 18),
    ]


def test_set_sync_targets_never_unregisters_what_it_did_not_see(tmp_path, monkeypatch):
    """The Routines card's write carries the devices it was SHOWN. A write
    whose list was empty (the card had not rendered yet) must not empty the
    settings — that is how four registered devices disappeared in one write."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    from divoom_lib import settings_devices

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text(
        "[gallery]\na9fccb71-3d3d-4de3-c381-0de382cdc4aa = 17\n", encoding="utf-8"
    )
    before = settings_devices.registered_devices()

    assert m.set_sync_targets(targets_json=json.dumps({"checked": [], "known": []})) is True
    assert settings_devices.registered_devices() == before


def test_set_sync_targets_non_list_and_non_dict_payloads_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    from divoom_lib import settings_devices

    ok = m.set_sync_targets(targets_json=json.dumps({"not": "a list"}),
                             galleries_json=json.dumps([1, 2, 3]))
    assert ok is True  # registering nothing still succeeds
    assert settings_devices.registered_devices() == []


def test_set_sync_targets_none_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    ok = m.set_sync_targets(targets_json=None, galleries_json=None)
    assert ok is True


def test_set_sync_targets_malformed_json_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    ok = m.set_sync_targets(targets_json="{not valid json[")
    assert ok is False


def test_the_sync_target_write_says_what_it_saw():
    """The card's write carries the devices it was SHOWN, not only the checked
    ones.

    A write that reads the live checkboxes can see an empty list while the
    card is re-rendering — and a write that said "these ARE the devices"
    would then empty the settings, which is how four registered devices
    disappeared from them in one write (measured 2026-10-21)."""
    src = (
        Path(__file__).resolve().parent.parent
        / "divoom_gui" / "web_ui" / "gallery.js"
    ).read_text(encoding="utf-8")
    assert "set_sync_targets(JSON.stringify({ checked, known }))" in src, (
        "the write must carry both the checked devices and the ones it saw"
    )
    assert 'querySelectorAll("#sync-targets-list input:checked")' not in src, (
        "the write must not read the live DOM: a re-render can empty it"
    )


# ───────────────────── hot channel config get/save ─────────────────────

def test_get_hot_channel_config_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(tmp_path / "hotchannel.json"))
    m = _Host()
    cfg = json.loads(m.get_hot_channel_config())
    assert cfg == {"enabled": False, "interval": 86400}


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
    ok = m.save_hot_channel_config(enabled=True, interval=900)
    assert ok is True
    cfg = json.loads(m.get_hot_channel_config())
    assert cfg["interval"] == 900


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
