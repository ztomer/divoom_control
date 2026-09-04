"""Unit tests for the shared hot-channel persistence layer."""

import json
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
    assert cfg == {"enabled": False, "interval": 3600, "classify": 18, "targets": [], "device_galleries": {}}


def test_save_and_reload(cfg_path):
    assert hc.save_config({"enabled": True, "interval": 900, "classify": 5,
                           "targets": ["AA:BB:CC:DD:EE:FF"]})
    cfg = hc.load_config()
    assert cfg["enabled"] is True
    assert cfg["interval"] == 900
    assert cfg["classify"] == 5
    assert cfg["targets"] == ["AA:BB:CC:DD:EE:FF"]


def test_partial_save_merges(cfg_path):
    hc.save_config({"targets": ["X"], "interval": 1200})
    hc.save_config({"enabled": True})  # partial
    cfg = hc.load_config()
    assert cfg["enabled"] is True
    assert cfg["targets"] == ["X"]      # preserved
    assert cfg["interval"] == 1200      # preserved


def test_interval_floor(cfg_path):
    hc.save_config({"interval": 5})
    assert hc.load_config()["interval"] == hc.MIN_INTERVAL


def test_targets_dedupe_and_clean(cfg_path):
    hc.set_targets(["AA", "AA", "  ", "BB", ""])
    assert hc.get_targets() == ["AA", "BB"]


def test_corrupt_file_falls_back(cfg_path):
    cfg_path.write_text("{not json", encoding="utf-8")
    assert hc.load_config()["interval"] == 3600


def test_written_file_is_valid_json(cfg_path):
    hc.save_config({"targets": ["LAN:192.168.1.5"]})
    data = json.loads(cfg_path.read_text())
    assert data["targets"] == ["LAN:192.168.1.5"]


def test_nonnumeric_device_gallery_does_not_raise(cfg_path):
    """load_config() promises 'never raises' and runs unguarded in the headless
    daemon's main(). A non-numeric device_galleries value (hand-edited JSON or a
    blank style from the GUI) must be DROPPED, not crash _normalize().

    Teeth: revert _normalize() to `{k: int(v) ...}` and this raises ValueError
    out of load_config() (the int(v) is outside its try/except), reproducing the
    daemon-killing startup crash.
    """
    cfg_path.write_text(
        json.dumps({
            "device_galleries": {
                "AA:BB:CC:DD:EE:FF": "recommend",  # non-numeric -> dropped
                "11:22:33:44:55:66": "",           # blank        -> dropped
                "77:88:99:AA:BB:CC": 9,            # valid        -> kept
            }
        }),
        encoding="utf-8",
    )
    cfg = hc.load_config()  # must NOT raise
    assert cfg["device_galleries"] == {"77:88:99:AA:BB:CC": 9}


def test_set_device_galleries_with_blank_value_does_not_raise(cfg_path):
    """The GUI can hand set_device_galleries an empty style; it must persist
    cleanly (dropping the blank) rather than throwing out of save_config."""
    assert hc.set_device_galleries({"AA:BB:CC:DD:EE:FF": ""}) is True
    assert hc.load_config()["device_galleries"] == {}
