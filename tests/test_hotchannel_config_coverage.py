"""Coverage-focused tests for divoom_lib/hotchannel_config.py (R61 coverage push).

Complements tests/test_hotchannel_config.py by exercising the remaining
defensive/normalization branches: a non-dict JSON payload, save_config's
OSError path, get_device_classify's non-numeric fallback, and _normalize's
per-field coercion failures (interval/classify/targets/device_galleries),
including a device_galleries key that isn't a (non-blank) string.
"""
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


def test_non_dict_json_payload_falls_back_to_defaults(cfg_path):
    """A JSON file holding a list (not an object) must be ignored, not crash
    load_config()'s "never raises" contract."""
    cfg_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    cfg = hc.load_config()
    assert cfg["interval"] == hc.DEFAULTS["interval"]
    assert cfg["targets"] == []


def test_save_config_returns_false_on_oserror(monkeypatch, cfg_path):
    def boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr("divoom_lib.utils.atomic_io.atomic_write_text", boom)
    assert hc.save_config({"interval": 900}) is False


def test_get_device_classify_falls_back_on_non_numeric_value():
    cfg = {"classify": 7, "device_galleries": {"AA:BB": "not-a-number"}}
    assert hc.get_device_classify(cfg, "AA:BB") == 7


def test_get_device_classify_falls_back_when_address_absent():
    cfg = {"classify": 9, "device_galleries": {}}
    assert hc.get_device_classify(cfg, "unknown") == 9


def test_get_device_classify_uses_valid_per_device_value():
    cfg = {"classify": 7, "device_galleries": {"AA:BB": "12"}}
    assert hc.get_device_classify(cfg, "AA:BB") == 12


def test_save_config_non_numeric_interval_falls_back_to_default(cfg_path):
    hc.save_config({"interval": "not-a-number"})
    assert hc.load_config()["interval"] == hc.DEFAULTS["interval"]


def test_save_config_non_numeric_classify_falls_back_to_default(cfg_path):
    hc.save_config({"classify": "not-a-number"})
    assert hc.load_config()["classify"] == hc.DEFAULTS["classify"]


def test_save_config_non_list_targets_becomes_empty(cfg_path):
    hc.save_config({"targets": "AA:BB:CC:DD:EE:FF"})  # a string, not a list
    assert hc.load_config()["targets"] == []


def test_save_config_non_dict_device_galleries_becomes_empty(cfg_path):
    hc.save_config({"device_galleries": ["AA:BB", "CC:DD"]})  # a list, not a dict
    assert hc.load_config()["device_galleries"] == {}


def test_normalize_drops_non_string_and_blank_gallery_keys(cfg_path):
    """_normalize must tolerate a non-string key (possible via direct
    programmatic use, even though JSON round-trips always give string keys)
    and a blank-string key, dropping both while keeping a valid entry."""
    hc.save_config({"device_galleries": {123: 5, "": 7, "valid:mac": 9}})
    assert hc.load_config()["device_galleries"] == {"valid:mac": 9}
