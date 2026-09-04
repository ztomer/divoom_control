"""Device-status reporting — backend honesty.

The UI's device-status surface (connection dot, known-but-undetected chips)
depends on two ScannerMixin methods returning the device's REAL state:

  * ``get_connection_state``  -> the appbar heartbeat's honest
    ``{connected, state}`` (connected / degraded / disconnected), never a
    stale/misleading claim.
  * ``get_known_devices``     -> the persistent cache minus the current scan,
    so a device missed by a scan still surfaces as a distinct "known" chip
    instead of vanishing.

Plus ``_cache_discovered`` (the merge that keeps the cache honest across
scans). These are the backend data sources the live UI consumes: the daemon
now PUSHES ``status`` / ``owned_devices`` events (handled in
``divoom_gui/web_ui/connection_events.js``) and the e2e tests in
``test_e2e_device_status_dot.py`` / ``test_e2e_device_status_chips.py`` assert
the dot + chips render those events faithfully.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from divoom_gui.scanner_mixin import ScannerMixin


class _FakeClient:
    def __init__(self, status):
        self._status = status

    def device_status(self):
        return self._status


class _BoomClient:
    def device_status(self):
        raise RuntimeError("socket dead")


class _TestScanner(ScannerMixin):
    """ScannerMixin has no _client of its own (that lives on the API class);
    a tiny subclass lets us inject a fake daemon without spawning anything."""

    def _client(self):
        return getattr(self, "_fake", None)


def _make():
    s = _TestScanner()
    s._fake = None
    s.discovered_list = []
    return s


# ── get_connection_state ────────────────────────────────────────────────────
def test_get_connection_state_connected():
    s = _make()
    s._fake = _FakeClient({"connected": True, "connection_state": "connected"})
    assert json.loads(s.get_connection_state()) == {
        "connected": True, "state": "connected"}


def test_get_connection_state_degraded():
    s = _make()
    s._fake = _FakeClient({"connected": True, "connection_state": "degraded"})
    assert json.loads(s.get_connection_state()) == {
        "connected": True, "state": "degraded"}


def test_get_connection_state_disconnected():
    s = _make()
    s._fake = _FakeClient({"connected": False})
    assert json.loads(s.get_connection_state()) == {
        "connected": False, "state": "disconnected"}


def test_get_connection_state_no_daemon_reads_disconnected():
    # A missing/unreachable daemon must read as disconnected, NOT as connected.
    s = _make()
    s._fake = None
    assert json.loads(s.get_connection_state()) == {
        "connected": False, "state": "disconnected"}


def test_get_connection_state_daemon_error_reads_disconnected():
    s = _make()
    s._fake = _BoomClient()
    assert json.loads(s.get_connection_state()) == {
        "connected": False, "state": "disconnected"}


def test_get_connection_state_explicit_disconnected_not_masked_by_connected():
    # The daemon's honest `state` must win over a stale connected:true flag.
    s = _make()
    s._fake = _FakeClient({"connected": True, "connection_state": "disconnected"})
    assert json.loads(s.get_connection_state()) == {
        "connected": False, "state": "disconnected"}


# ── get_known_devices ───────────────────────────────────────────────────────
def _write_cache(tmp, devices):
    p = tmp / ".config" / "divoom-control" / "discovered_devices.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(devices), encoding="utf-8")
    return p


def test_get_known_devices_excludes_detected(tmp_path):
    s = _make()
    s.discovered_list = [{"address": "AA"}]
    _write_cache(tmp_path, [{"address": "AA", "name": "Ditoo"},
                            {"address": "BB", "name": "Pixoo"}])
    with patch.object(Path, "home", return_value=tmp_path):
        out = json.loads(s.get_known_devices())
    assert out == [{"address": "BB", "name": "Pixoo", "detected": False}]


def test_get_known_devices_empty_when_no_cache(tmp_path):
    s = _make()
    s.discovered_list = [{"address": "AA"}]
    with patch.object(Path, "home", return_value=tmp_path):
        assert json.loads(s.get_known_devices()) == []


def test_get_known_devices_uses_ip_for_lan(tmp_path):
    s = _make()
    s.discovered_list = []
    _write_cache(tmp_path, [{"ip": "10.0.0.5", "name": "LAN Screen"}])
    with patch.object(Path, "home", return_value=tmp_path):
        out = json.loads(s.get_known_devices())
    assert out == [{"address": "10.0.0.5", "name": "LAN Screen", "detected": False}]


def test_get_known_devices_detected_wins_over_cache(tmp_path):
    # A device present in BOTH the cache and the current scan must NOT be
    # reported as an undetected "known" chip.
    s = _make()
    s.discovered_list = [{"address": "AA"}]
    _write_cache(tmp_path, [{"address": "AA", "name": "Ditoo"}])
    with patch.object(Path, "home", return_value=tmp_path):
        assert json.loads(s.get_known_devices()) == []


def test_get_known_devices_handles_malformed_cache(tmp_path):
    p = tmp_path / ".config" / "divoom-control"
    p.mkdir(parents=True, exist_ok=True)
    (p / "discovered_devices.json").write_text("{not json", encoding="utf-8")
    s = _make()
    with patch.object(Path, "home", return_value=tmp_path):
        assert json.loads(s.get_known_devices()) == []   # graceful, not a crash


# ── _cache_discovered (keeps the cache honest across scans) ─────────────────
def test_cache_discovered_merges_and_stamps(tmp_path):
    s = _make()
    cache = tmp_path / ".config" / "divoom-control" / "discovered_devices.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(
        [{"address": "AA", "name": "Ditoo", "first_seen": 100.0}]))
    with patch.object(Path, "home", return_value=tmp_path):
        s._cache_discovered([{"address": "AA", "name": "Ditoo-X"},
                             {"address": "BB", "name": "Pixoo"}])
        data = {d["address"]: d for d in json.loads(cache.read_text())}
    assert set(data) == {"AA", "BB"}
    assert data["AA"]["first_seen"] == 100.0        # preserved across scans
    assert data["AA"]["last_seen"] > 100.0          # bumped this scan
    assert data["AA"]["name"] == "Ditoo-X"          # fresh scan wins


def test_cache_discovered_updates_detected_count(tmp_path):
    s = _make()
    cfg = tmp_path / ".config" / "divoom-control" / "config.ini"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    with patch.object(Path, "home", return_value=tmp_path):
        s._cache_discovered([{"address": "AA"}, {"address": "BB"}])
        import configparser
        c = configparser.ConfigParser()
        c.read(cfg)
        assert c.get("gui", "last_detected_count") == "2"
