"""Connection-router coverage: connect() name resolution, SPP-vs-BLE routing
and transport teardown (split from test_connection_router_coverage.py)."""
import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import divoom_lib.divoom  # noqa: F401  - import first to resolve the import cycle
from divoom_lib import bt_spp_transport
from divoom_lib import models
from divoom_lib import spp_connection
from divoom_lib.ble_transport import BLETransport
from divoom_lib.connection import DivoomConnection
from tests.support.connection_router_common import (  # noqa: F401
    _FakeClient,
    _FakeDivoom,
    _FakeSpp,
    _make_conn,
    _run,
)


# ── connect(): device-name resolution (IOBluetooth + discovered-devices cache) ──

def test_connect_resolves_name_via_iobluetooth_then_routes_to_spp(monkeypatch):
    mock_iobluetooth = MagicMock()
    mock_dev = MagicMock()
    mock_dev.getName.return_value = "Ditoo-Pro"
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = mock_dev
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)
    monkeypatch.setattr(spp_connection, "resolve_classic_mac",
                         lambda *a, **k: "11-22-33-44-55-66")
    monkeypatch.setattr(bt_spp_transport, "BTSppTransport", _FakeSpp)

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn.device_name == "Ditoo-Pro"
    assert conn._use_spp is True
    assert isinstance(conn._active_transport, _FakeSpp)
    assert conn._active_transport.kwargs["device_kind"] == "ditoo"


def test_connect_iobluetooth_returns_none_falls_back_to_cache_file(monkeypatch, tmp_path):
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text(json.dumps(
        [{"address": "AA:BB:CC:DD:EE:FF", "name": "Cached-NoneDev"}]))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn.device_name == "Cached-NoneDev"
    assert conn._use_spp is False


def test_connect_iobluetooth_exception_falls_back_to_cache_file(monkeypatch, tmp_path):
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.side_effect = RuntimeError("no bt stack")
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text(json.dumps(
        [{"address": "AA:BB:CC:DD:EE:FF", "name": "Cached-Other"}]))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)
    _run(conn.connect())            # must not raise from the swallowed IOBluetooth error

    assert conn.device_name == "Cached-Other"
    assert conn._use_spp is False


def test_connect_cache_file_read_error_is_swallowed(monkeypatch, tmp_path, caplog):
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text("{ not valid json")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)

    with caplog.at_level(logging.DEBUG):
        _run(conn.connect())        # malformed cache must not crash connect()

    assert conn.device_name is None
    assert conn._use_spp is False
    assert any("Failed to load device name from cache" in r.message for r in caplog.records)


def test_connect_cache_file_missing_leaves_name_none(monkeypatch, tmp_path):
    """cache_file.exists() is False — the whole read/parse block is skipped.

    NB: mac is a 17-char colon address, so connect() WILL attempt the
    IOBluetooth resolution branch first — stub sys.modules['IOBluetooth']
    (as every other name-resolution test here does) so this never reaches
    the real macOS IOBluetooth framework."""
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)   # tmp_path has no .config dir at all

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn.device_name is None
    assert conn._use_spp is False


def test_connect_cache_file_skips_non_matching_entries_before_match(monkeypatch, tmp_path):
    """Two devices in the cache; the loop must iterate past the non-matching
    first entry before finding the match on the second."""
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text(json.dumps([
        {"address": "FF:FF:FF:FF:FF:FF", "name": "Someone-Else"},
        {"address": "AA:BB:CC:DD:EE:FF", "name": "Cached-Second-Match"},
    ]))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn.device_name == "Cached-Second-Match"


def test_connect_cache_file_empty_devices_list_leaves_name_none(monkeypatch, tmp_path):
    """An empty discovered-devices list: the for-loop body never executes."""
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text(json.dumps([]))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn.device_name is None


def test_connect_skips_iobluetooth_when_mac_not_standard_format(monkeypatch, tmp_path):
    """mac that isn't a 17-char, ':'/'-'-separated address must skip the
    IOBluetooth resolution branch entirely but still try the cache file."""
    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text(json.dumps(
        [{"address": "shortmac", "name": "Cached-NoFormat"}]))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    conn = _make_conn(monkeypatch, device_name=None, mac="shortmac", use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn.device_name == "Cached-NoFormat"


def test_connect_is_mock_env_skips_name_resolution_and_spp(monkeypatch):
    conn = _make_conn(monkeypatch, device_name=None, use_ios_le_protocol=False, mock_ble_env=True)
    _run(conn.connect())

    assert conn.device_name is None      # never resolved — is_mock short-circuited it
    assert conn._use_spp is False
    assert isinstance(conn._active_transport, BLETransport)


def test_connect_is_mock_via_client_class_name(monkeypatch):
    class MockBleakClient:
        def __init__(self):
            self.is_connected = False

    cfg = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name=None,
                               client=MockBleakClient(),
                               write_characteristic_uuid="w", notify_characteristic_uuid="n",
                               read_characteristic_uuid="r", use_ios_le_protocol=False)
    conn = DivoomConnection(_FakeDivoom(), cfg)
    monkeypatch.setattr(BLETransport, "connect", AsyncMock())

    _run(conn.connect())

    assert conn.device_name is None
    assert conn._use_spp is False


# ── connect(): SPP-vs-BLE routing decision ──────────────────────────────────

def test_connect_pixoo64_device_name_is_excluded_from_spp(monkeypatch):
    conn = _make_conn(monkeypatch, device_name="Pixoo 64", use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn._use_spp is False
    assert isinstance(conn._active_transport, BLETransport)


@pytest.mark.parametrize("name,expected_kind", [
    ("Pixoo-Max", "pixoo"),
    ("Timoo-One", "timoo"),
    ("Tivoo-Max", "tivoo"),
])
def test_connect_spp_device_kind_by_name(monkeypatch, name, expected_kind):
    monkeypatch.setattr(spp_connection, "resolve_classic_mac",
                         lambda *a, **k: "11-22-33-44-55-66")
    monkeypatch.setattr(bt_spp_transport, "BTSppTransport", _FakeSpp)

    conn = _make_conn(monkeypatch, device_name=name, use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn._active_transport.kwargs["device_kind"] == expected_kind


def test_connect_spp_device_kind_defaults_for_unmatched_keyword(monkeypatch):
    """'timebox' triggers the SPP keyword match but isn't one of the
    pixoo/timoo/ditoo/tivoo device_kind buckets — device_kind stays 'default'."""
    monkeypatch.setattr(spp_connection, "resolve_classic_mac",
                         lambda *a, **k: "11-22-33-44-55-66")
    monkeypatch.setattr(bt_spp_transport, "BTSppTransport", _FakeSpp)

    conn = _make_conn(monkeypatch, device_name="Timebox-Evo", use_ios_le_protocol=False)
    _run(conn.connect())

    assert conn._active_transport.kwargs["device_kind"] == "default"


def test_connect_spp_resolve_fails_falls_back_to_ble_with_warning(monkeypatch, caplog):
    monkeypatch.setattr(spp_connection, "resolve_classic_mac", lambda *a, **k: None)

    conn = _make_conn(monkeypatch, device_name="Pixoo-Test", use_ios_le_protocol=False)
    with caplog.at_level(logging.WARNING):
        _run(conn.connect())

    assert conn._use_spp is False
    assert isinstance(conn._active_transport, BLETransport)
    assert any("Could not resolve Bluetooth Classic MAC" in r.message for r in caplog.records)


def test_connect_ble_to_spp_switch_tears_down_old_ble_transport(monkeypatch):
    monkeypatch.setattr(spp_connection, "resolve_classic_mac",
                         lambda *a, **k: "11-22-33-44-55-66")
    monkeypatch.setattr(bt_spp_transport, "BTSppTransport", _FakeSpp)

    conn = _make_conn(monkeypatch, device_name="Ditoo-Classic", use_ios_le_protocol=False)
    old_transport = conn._active_transport
    old_transport.disconnect = AsyncMock()

    _run(conn.connect())

    old_transport.disconnect.assert_awaited_once()
    assert isinstance(conn._active_transport, _FakeSpp)


def test_connect_spp_to_ble_switch_tears_down_old_spp_transport(monkeypatch, caplog):
    conn = _make_conn(monkeypatch, device_name="Generic Device", use_ios_le_protocol=False)

    class _OldSpp:
        def __init__(self):
            self.mac_address = "AA-BB-CC-DD-EE-FF"
            self.device_name = "Generic Device"
            self.disconnect = AsyncMock()

    old_spp = _OldSpp()
    conn._active_transport = old_spp
    conn._use_spp = True

    with caplog.at_level(logging.INFO):
        _run(conn.connect())

    old_spp.disconnect.assert_awaited_once()
    assert conn._use_spp is False
    assert isinstance(conn._active_transport, BLETransport)
    assert any("Switching transport to BLETransport" in r.message for r in caplog.records)


def test_connect_spp_reconnect_same_type_is_a_noop_swap(monkeypatch):
    """Already on SPP with the same concrete transport type: the router must
    reuse the existing transport rather than re-resolving/re-swapping."""
    resolve_called = {"n": 0}

    def _resolve(*a, **k):
        resolve_called["n"] += 1
        return "11-22-33-44-55-66"

    monkeypatch.setattr(spp_connection, "resolve_classic_mac", _resolve)
    monkeypatch.setattr(bt_spp_transport, "BTSppTransport", _FakeSpp)

    conn = _make_conn(monkeypatch, device_name="Ditoo-Reconnect", use_ios_le_protocol=False)
    existing = _FakeSpp(device_kind="ditoo", device_name="Ditoo-Reconnect")
    conn._active_transport = existing
    conn._use_spp = True

    _run(conn.connect())

    assert conn._active_transport is existing   # no swap happened
    assert resolve_called["n"] == 0              # resolve wasn't even attempted


# ── _teardown_outgoing_transport() ──────────────────────────────────────────

def test_teardown_outgoing_transport_none_is_noop(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport = None
    _run(conn._teardown_outgoing_transport())   # must not raise


def test_teardown_outgoing_transport_swallows_disconnect_exception(monkeypatch, caplog):
    conn = _make_conn(monkeypatch)

    class _Boom:
        async def disconnect(self):
            raise RuntimeError("disc fail")

    conn._active_transport = _Boom()
    with caplog.at_level(logging.DEBUG):
        _run(conn._teardown_outgoing_transport())   # must not raise

    assert any("outgoing transport teardown failed" in r.message for r in caplog.records)
