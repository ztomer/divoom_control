"""Coverage-focused tests for divoom_lib/hotchannel_config.py.

Complements tests/test_hotchannel_config.py by exercising the remaining
defensive branches: a non-dict JSON payload, save_config's OSError path, and
_normalize's interval coercion.
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
    assert cfg["enabled"] is False


def test_save_config_returns_false_on_oserror(monkeypatch, cfg_path):
    def boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr("divoom_lib.utils.atomic_io.atomic_write_text", boom)
    assert hc.save_config({"interval": 900}) is False


def test_save_config_non_numeric_interval_falls_back_to_default(cfg_path):
    hc.save_config({"interval": "not-a-number"})
    assert hc.load_config()["interval"] == hc.DEFAULTS["interval"]


def test_a_string_interval_is_coerced(cfg_path):
    hc.save_config({"interval": "1200"})
    assert hc.load_config()["interval"] == 1200


def test_normalize_drops_the_keys_it_does_not_know(cfg_path):
    """A key this build does not know is dropped rather than written back.
    That is what migrates a stale file: the devices are not this file's
    business any more."""
    hc.save_config({"enabled": True, "targets": ["AA:BB:CC:DD:EE:FF"]})
    written = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "targets" not in written
