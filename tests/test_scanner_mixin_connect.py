"""ScannerMixin connect/lan-token/device-name coverage (split from
test_scanner_mixin.py)."""
import configparser
import json
import pytest

from tests.support.scanner_support import CACHE_REL, CONFIG_REL, host  # noqa: F401


# ── connect_single_device ──────────────────────────────────────────────────

def test_connect_single_device_matrix_wall(host, tmp_path):
    assert host.connect_single_device("MatrixWall") is True
    assert host.current_target_mode == "wall"
    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / CONFIG_REL)
    assert cfg["gui"]["last_connected_device"] == "MatrixWall"


def test_connect_single_device_no_daemon(host, monkeypatch):
    monkeypatch.setattr(host, "reconnect_daemon", lambda: None)
    host._daemon_client = None
    assert host.connect_single_device("AA:BB") is False


def test_connect_single_device_lan_success(host, monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    monkeypatch.setattr(host, "reconnect_daemon", lambda: None)
    client = MagicMock()
    client.connect_device.return_value = {"success": True, "connected": True}
    client.device_status.return_value = {"connected": True}
    host._daemon_client = client
    ok = host.connect_single_device("LAN:192.168.1.50")
    assert ok is True
    client.disconnect_device.assert_called_once()
    _, kwargs = client.connect_device.call_args
    assert kwargs["lan_ip"] == "192.168.1.50"
    assert kwargs["lan_token"] == 0
    assert host.current_divoom is not None


def test_connect_single_device_ble_fail_reply_sets_last_error(host, monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(host, "reconnect_daemon", lambda: None)
    client = MagicMock()
    client.connect_device.return_value = {"success": False, "message": "asleep"}
    host._daemon_client = client
    ok = host.connect_single_device("AA:BB:CC:DD:EE:FF")
    assert ok is False
    assert host.get_last_connect_error() == "asleep"
    assert host.current_divoom is None


def test_connect_single_device_reports_success_but_not_connected(host, monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(host, "reconnect_daemon", lambda: None)
    client = MagicMock()
    client.connect_device.return_value = {"success": True, "connected": True}
    client.device_status.return_value = {"connected": False}
    host._daemon_client = client
    ok = host.connect_single_device("AA:BB:CC:DD:EE:FF")
    assert ok is False
    assert host.current_divoom is None


def test_connect_single_device_exception_sets_last_error(host, monkeypatch):
    monkeypatch.setattr(host, "reconnect_daemon", lambda: None)

    class _Boom:
        def _client(self):
            raise RuntimeError("wire fell over")

    monkeypatch.setattr(host, "_client", _Boom()._client)
    ok = host.connect_single_device("AA:BB:CC:DD:EE:FF")
    assert ok is False
    assert "wire fell over" in host.get_last_connect_error()
    assert host.current_divoom is None


# ── _lan_token_for ──────────────────────────────────────────────────────────

def test_lan_token_for_no_presets_file(host):
    assert host._lan_token_for("192.168.1.50") == 0


def test_lan_token_for_match_found(host):
    host._presets_file.write_text(json.dumps(
        {"lan_devices": [{"ip": "192.168.1.50", "token": 4242}]}), encoding="utf-8")
    assert host._lan_token_for("192.168.1.50") == 4242


def test_lan_token_for_no_match_returns_zero(host):
    host._presets_file.write_text(json.dumps(
        {"lan_devices": [{"ip": "10.0.0.1", "token": 1}]}), encoding="utf-8")
    assert host._lan_token_for("192.168.1.50") == 0


def test_lan_token_for_malformed_json_returns_zero(host):
    host._presets_file.write_text("{ broken", encoding="utf-8")
    assert host._lan_token_for("192.168.1.50") == 0


# ── _device_name_for ─────────────────────────────────────────────────────

def test_device_name_for_found_in_discovered_list(host):
    # A non-matching entry first, so the loop's false-branch (continue to next
    # item) fires before the matching entry is found.
    host.discovered_list = [{"address": "ZZ:ZZ", "name": "Other"},
                            {"address": "AA:BB", "name": "Pixoo-Live"}]
    assert host._device_name_for("AA:BB") == "Pixoo-Live"


def test_device_name_for_found_in_cache_file(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    # Same shape: a non-matching entry before the match, exercising the
    # cache-file loop's continue branch too.
    cache_file.write_text(json.dumps([
        {"address": "ZZ:ZZ", "name": "Other"},
        {"address": "AA:BB", "name": "Pixoo-Cached"},
    ]), encoding="utf-8")
    assert host._device_name_for("AA:BB") == "Pixoo-Cached"


def test_device_name_for_malformed_cache_returns_none(host, tmp_path):
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{ broken", encoding="utf-8")
    assert host._device_name_for("AA:BB") is None


def test_device_name_for_not_found_anywhere(host):
    assert host._device_name_for("ZZ:ZZ") is None


def test_device_name_for_cache_loop_exhausts_without_match(host, tmp_path):
    """The cache-file loop runs to completion (no match) and falls through to
    the trailing `return None` — distinct from the malformed-JSON except path."""
    cache_file = tmp_path / CACHE_REL
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps([{"address": "XX:XX", "name": "Other"}]),
                          encoding="utf-8")
    assert host._device_name_for("AA:BB") is None
