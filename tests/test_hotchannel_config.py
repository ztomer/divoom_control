"""Unit tests for the shared hot-channel persistence layer.

What this file pins:

* the file holds the LOOP's own settings only — whether it runs and how often;
* the devices the loop pushes to are NOT here any more. They are the app's
  settings (``config.ini``'s ``[gallery]`` table — see
  ``tests/test_settings_devices.py``). A file written by an older build still
  carries the old keys: they are REPORTED and IGNORED, and the next save
  drops them.
* the default cadence is a DAY, because the content is refreshed almost daily.
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import hotchannel_config as hc


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "hotchannel.json"
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(p))
    return p


def test_defaults_when_missing(cfg_path):
    cfg = hc.load_config()
    assert cfg == {"enabled": False, "interval": 86400}


def test_the_default_cadence_is_a_day(cfg_path):
    """The "monthly best" content is refreshed almost daily — the CATEGORY is
    the cloud's name for it, not a monthly cadence — so the default push is
    daily. A weekly default would leave the device up to a week behind."""
    assert hc.load_config()["interval"] == 86400
    assert hc.DEFAULTS["interval"] == 86_400


def test_save_and_reload(cfg_path):
    assert hc.save_config({"enabled": True, "interval": 900})
    cfg = hc.load_config()
    assert cfg["enabled"] is True
    assert cfg["interval"] == 900


def test_partial_save_merges(cfg_path):
    hc.save_config({"interval": 1200})
    hc.save_config({"enabled": True})  # partial
    cfg = hc.load_config()
    assert cfg["enabled"] is True
    assert cfg["interval"] == 1200      # preserved


def test_interval_floor(cfg_path):
    hc.save_config({"interval": 5})
    assert hc.load_config()["interval"] == hc.MIN_INTERVAL


def test_the_device_list_is_not_in_this_file_any_more(cfg_path):
    """The old shape had `targets` and `device_galleries`. The devices live in
    the app's settings now, so a file that still carries them must not grow a
    device list back — and saving must not write one."""
    cfg_path.write_text(json.dumps({
        "enabled": True,
        "interval": 86400,
        "targets": ["AA:BB:CC:DD:EE:FF"],
        "device_galleries": {"AA:BB:CC:DD:EE:FF": 9},
    }), encoding="utf-8")

    cfg = hc.load_config()
    assert "targets" not in cfg
    assert "device_galleries" not in cfg

    hc.save_config({"enabled": False})
    written = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert written == {"enabled": False, "interval": 86400}, (
        "saving must MIGRATE the file: the stale device list is dropped, "
        "because the file is rewritten with the loop's own keys only"
    )


def test_a_stale_file_is_reported(cfg_path, caplog):
    """A file that still carries the old keys must SAY so. Silently ignoring a
    stale device list is how the empty-list bug stayed invisible for 36 days."""
    cfg_path.write_text(json.dumps({
        "enabled": True,
        "interval": 86400,
        "targets": ["AA:BB:CC:DD:EE:FF"],
    }), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        hc.load_config()

    assert any("targets" in record.getMessage() for record in caplog.records), (
        f"the stale key must be reported: {[r.getMessage() for r in caplog.records]}"
    )


def test_corrupt_file_falls_back(cfg_path):
    cfg_path.write_text("{not json", encoding="utf-8")
    assert hc.load_config()["interval"] == 86400


def test_written_file_is_valid_json(cfg_path):
    hc.save_config({"enabled": True, "interval": 3600})
    data = json.loads(cfg_path.read_text())
    assert data["interval"] == 3600


def test_a_non_dict_payload_falls_back_to_the_defaults(cfg_path):
    cfg_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert hc.load_config() == hc.DEFAULTS
