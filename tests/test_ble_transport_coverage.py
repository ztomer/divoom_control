"""Coverage push (PLANNING_ROUND61 #1) for divoom_lib/ble_transport.py.

HAZARD: BLETransport.__init__/connect() re-import BleakClient via a call-time
``from .divoom import BleakClient`` (not the ble_transport module-level name).
The ONLY correct patch target is ``divoom_lib.divoom.BleakClient`` — patching
``divoom_lib.ble_transport.BleakClient`` silently does nothing, and a missed
patch lets a real ``BleakClient.connect()`` reach macOS CoreBluetooth and
SIGABRT the whole pytest process (see commit e26fc6d). Every test here either
patches ``divoom_lib.divoom.BleakClient`` before constructing a transport with
a MAC, or constructs one with no MAC at all (the ``self.client = None`` path
never touches bleak).

These tests target the connect()/disconnect()/send_command()/
_send_payload_locked()/_send_basic_protocol_payload() gaps identified by
`--cov-report=term-missing` on this file: device-name resolution (IOBluetooth
+ discovered-devices cache), the already-connected/already-subscribed skip
branches, disconnect()'s two swallowed-exception paths, send_command()'s own
payload building + exception handling, the retry loop's self-reconnect and
ios-le-retry branches, and the large-message chunking path in
_send_basic_protocol_payload (never exercised elsewhere — DEFAULT_CHUNK_SIZE
is 200 bytes and every existing test sends short payloads).
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from divoom_lib import models
from divoom_lib.ble_transport import BLETransport
from divoom_lib.exceptions import CharacteristicConfigError
from divoom_lib.protocol import DivoomProtocol


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _transport(monkeypatch, **cfg_kwargs):
    """A BLETransport with a controllable AsyncMock bleak client, registry/IO
    paths disabled (DIVOOM_MOCK_BLE), and tiny timeouts — mirrors the fixture
    in test_ble_timeout_hardening.py."""
    monkeypatch.setenv("DIVOOM_MOCK_BLE", "1")
    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = AsyncMock()
        proto = DivoomProtocol(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice", **cfg_kwargs)
    proto.WRITE_CHARACTERISTIC_UUID = "w"
    proto.NOTIFY_CHARACTERISTIC_UUID = "n"
    proto.READ_CHARACTERISTIC_UUID = "r"
    t = proto._conn._active_transport
    t.CONNECT_TIMEOUT = 0.05
    t.NOTIFY_TIMEOUT = 0.05
    t.STOP_NOTIFY_TIMEOUT = 0.05
    t.DISCONNECT_TIMEOUT = 0.05
    return t


# ── __init__: no mac, no client → client stays None ─────────────────────────

def test_init_without_mac_or_client_leaves_client_none():
    cfg = models.DivoomConfig(mac=None, client=None)
    t = BLETransport(cfg, logging.getLogger("t"))
    assert t.client is None


# ── connect(): device-name resolution (IOBluetooth + cache file) ────────────

def test_connect_resolves_device_name_via_iobluetooth(monkeypatch):
    mock_iobluetooth = MagicMock()
    mock_dev = MagicMock()
    mock_dev.getName.return_value = "Pixoo-64"
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = mock_dev
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = MagicMock()
        cfg = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name=None,
                                   write_characteristic_uuid=None,
                                   notify_characteristic_uuid=None,
                                   read_characteristic_uuid=None)
        t = BLETransport(cfg, logging.getLogger("t"))

    # UUIDs are unset so connect() raises right after resolving the name —
    # this never reaches a real client.connect() call.
    with pytest.raises(CharacteristicConfigError):
        _run(t.connect())
    assert t.device_name == "Pixoo-64"


def test_connect_iobluetooth_exception_is_swallowed(monkeypatch):
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.side_effect = RuntimeError("no bt stack")
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = MagicMock()
        cfg = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name=None,
                                   write_characteristic_uuid=None,
                                   notify_characteristic_uuid=None,
                                   read_characteristic_uuid=None)
        t = BLETransport(cfg, logging.getLogger("t"))

    with pytest.raises(CharacteristicConfigError):
        _run(t.connect())            # must not raise from the swallowed IOBluetooth error
    assert t.device_name is None


def test_connect_resolves_device_name_via_cache_file(monkeypatch, tmp_path):
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text(json.dumps(
        [{"address": "AA:BB:CC:DD:EE:FF", "name": "Cached-Ditoo"}]))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = MagicMock()
        cfg = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name=None,
                                   write_characteristic_uuid=None,
                                   notify_characteristic_uuid=None,
                                   read_characteristic_uuid=None)
        t = BLETransport(cfg, logging.getLogger("t"))

    with pytest.raises(CharacteristicConfigError):
        _run(t.connect())
    assert t.device_name == "Cached-Ditoo"


def test_connect_cache_file_read_error_is_swallowed(monkeypatch, tmp_path):
    mock_iobluetooth = MagicMock()
    mock_iobluetooth.IOBluetoothDevice.deviceWithAddressString_.return_value = None
    monkeypatch.setitem(sys.modules, "IOBluetooth", mock_iobluetooth)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovered_devices.json").write_text("{ not valid json")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = MagicMock()
        cfg = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name=None,
                                   write_characteristic_uuid=None,
                                   notify_characteristic_uuid=None,
                                   read_characteristic_uuid=None)
        t = BLETransport(cfg, logging.getLogger("t"))

    with pytest.raises(CharacteristicConfigError):
        _run(t.connect())            # malformed cache must not crash connect()
    assert t.device_name is None


# ── connect(): already-connected-mid-race / already-subscribed / no-notify ──

def test_connect_skips_redundant_connect_when_client_already_connected(monkeypatch):
    """If self.client.is_connected flips True between the early return check
    (line ~144) and the actual-connect check (line ~158) — e.g. a concurrent
    reconnect elsewhere completed during the eviction await — connect() must
    not call client.connect() again."""
    t = _transport(monkeypatch)
    reads = {"n": 0}

    def _is_connected(_self):
        reads["n"] += 1
        return reads["n"] > 1   # False the first read, True from then on

    type(t.client).is_connected = property(_is_connected)
    t.client.start_notify = AsyncMock()
    t.use_ios_le_protocol = False       # skip autoprobe
    monkeypatch.setattr("divoom_lib.ble_transport.asyncio.sleep", AsyncMock())

    _run(t.connect())

    assert reads["n"] >= 2
    t.client.connect.assert_not_called()


def test_connect_skips_start_notify_when_already_started(monkeypatch):
    t = _transport(monkeypatch)
    t._notifications_started = True
    t.client.is_connected = False

    async def _ok_connect():
        t.client.is_connected = True

    t.client.connect = _ok_connect
    t.use_ios_le_protocol = False
    monkeypatch.setattr("divoom_lib.ble_transport.asyncio.sleep", AsyncMock())

    _run(t.connect())

    t.client.start_notify.assert_not_called()
    assert t._notifications_started is True


# NOTE: connect()'s "No notify characteristic UUID set" warning (ble_transport.py:202)
# is unreachable via the public connect() path: the guard at ble_transport.py:140
# (`if not all([WRITE, NOTIFY, READ])`) requires NOTIFY_CHARACTERISTIC_UUID truthy
# and raises CharacteristicConfigError first. An earlier test here tried to reach
# the warning by setting NOTIFY_CHARACTERISTIC_UUID = "" and always hit the guard's
# raise instead — removed rather than kept as a test of dead code.


# ── disconnect(): both swallowed-exception paths ────────────────────────────

def test_disconnect_stop_notify_exception_is_logged_but_disconnect_still_runs(monkeypatch, caplog):
    t = _transport(monkeypatch)
    t._notifications_started = True
    t.client.is_connected = True
    t.client.stop_notify = AsyncMock(side_effect=RuntimeError("stop failed"))
    t.client.disconnect = AsyncMock()

    with caplog.at_level(logging.DEBUG):
        _run(t.disconnect())

    assert any("stop_notify" in r.message and "failed" in r.message for r in caplog.records)
    t.client.disconnect.assert_awaited_once()


def test_disconnect_generic_exception_is_logged(monkeypatch, caplog):
    t = _transport(monkeypatch)
    t._notifications_started = False
    t.client.is_connected = True
    t.client.disconnect = AsyncMock(side_effect=RuntimeError("disc failed"))

    with caplog.at_level(logging.ERROR):
        _run(t.disconnect())          # must not raise

    assert any("Error disconnecting" in r.message for r in caplog.records)


# ── send_command(): direct calls (bypasses DivoomConnection routing) ───────

def test_send_command_success_builds_payload_and_delegates(monkeypatch):
    t = _transport(monkeypatch)
    captured = {}

    async def fake_send_payload(payload_bytes, **kwargs):
        captured["payload"] = payload_bytes
        captured["kwargs"] = kwargs
        return True

    t.send_payload = fake_send_payload
    ok = _run(t.send_command(0x45, [1, 2], write_with_response=True))

    assert ok is True
    assert captured["payload"] == [0x45, 1, 2]
    assert captured["kwargs"]["write_with_response"] is True


def test_send_command_resolves_string_command_name(monkeypatch):
    t = _transport(monkeypatch)
    name, cmd_id = next(iter(models.COMMANDS.items()))
    captured = {}

    async def fake_send_payload(payload_bytes, **kwargs):
        captured["payload"] = payload_bytes
        return True

    t.send_payload = fake_send_payload
    _run(t.send_command(name))

    assert captured["payload"][0] == cmd_id


def test_send_command_exception_from_send_payload_is_caught(monkeypatch, caplog):
    t = _transport(monkeypatch)

    async def boom(*_a, **_k):
        raise RuntimeError("payload boom")

    t.send_payload = boom

    with caplog.at_level(logging.ERROR):
        ok = _run(t.send_command(0x45))

    assert ok is False
    assert any("Error calling send_payload" in r.message for r in caplog.records)


# ── _send_payload_locked(): reconnect / retry branches ──────────────────────

def test_send_payload_reconnects_via_self_when_no_divoom(monkeypatch):
    """When self._divoom is falsy the retry loop reconnects via self.connect()
    directly (the else branch of `if self._divoom: ... else: await self.connect()`)."""
    t = _transport(monkeypatch)
    t._divoom = None
    t.client.is_connected = False
    reconnects = {"n": 0}

    async def fake_connect():
        reconnects["n"] += 1
        t.client.is_connected = True

    monkeypatch.setattr(t, "connect", fake_connect)
    t.use_ios_le_protocol = False
    t.client.write_gatt_char = AsyncMock(return_value=None)

    ok = _run(t.send_payload([0x01], max_retries=2, retry_delay=0.001))

    assert ok is True
    assert reconnects["n"] == 1


def test_send_payload_continues_after_reconnect_failure(monkeypatch):
    """A failed reconnect on a non-final attempt must `continue` to the next
    attempt rather than giving up immediately."""
    t = _transport(monkeypatch)
    t.client.is_connected = False
    calls = {"n": 0}

    async def flaky_connect():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("reconnect fail")
        t.client.is_connected = True

    t._divoom = MagicMock()
    t._divoom.connect = flaky_connect
    t._divoom._send_basic_protocol_payload = AsyncMock(return_value=True)
    t.use_ios_le_protocol = False
    t.client.write_gatt_char = AsyncMock(return_value=None)

    ok = _run(t.send_payload([0x01], max_retries=3, retry_delay=0.001))

    assert ok is True
    assert calls["n"] == 2


def test_send_payload_ios_le_retries_before_success(monkeypatch):
    t = _transport(monkeypatch)
    t.client.is_connected = True
    t._connection_likely_broken = False
    t.use_ios_le_protocol = True
    attempts = {"n": 0}

    async def flaky_send(_payload_bytes, _write_with_response):
        attempts["n"] += 1
        return attempts["n"] >= 2

    t._send_ios_le_payload = flaky_send
    t._divoom = None  # force the transport's own _send_ios_le_payload to be used
    monkeypatch.setattr("divoom_lib.ble_transport.asyncio.sleep", AsyncMock())

    ok = _run(t.send_payload([0x01], max_retries=3, retry_delay=0.001))

    assert ok is True
    assert attempts["n"] == 2


# ── _send_basic_protocol_payload(): chunking (never hit — 200-byte chunks) ──

def test_send_basic_protocol_payload_splits_large_message_into_chunks(monkeypatch):
    t = _transport(monkeypatch)
    write_calls = []

    async def fake_write(_uuid, chunk, response=False):
        write_calls.append((bytes(chunk), response))

    t.client.write_gatt_char = fake_write
    monkeypatch.setattr("divoom_lib.ble_transport.asyncio.sleep", AsyncMock())

    # DEFAULT_CHUNK_SIZE is 200 bytes; a 250-byte payload framed with the
    # basic protocol (payload + 6 bytes of framing) comfortably exceeds it.
    big_payload = [0x04] + [0x01] * 250
    ok = _run(t._send_basic_protocol_payload(big_payload, write_with_response=True))

    assert ok is True
    assert len(write_calls) >= 2
    # Only the LAST chunk should carry response=write_with_response=True.
    assert [r for (_c, r) in write_calls] == [False] * (len(write_calls) - 1) + [True]


def test_send_basic_protocol_payload_chunk_error_stops_and_flags_broken(monkeypatch):
    t = _transport(monkeypatch)
    call_count = {"n": 0}

    async def failing_write(_uuid, _chunk, response=False):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("disconnected mid-chunk")

    t.client.write_gatt_char = failing_write
    monkeypatch.setattr("divoom_lib.ble_transport.asyncio.sleep", AsyncMock())

    big_payload = [0x04] + [0x01] * 250
    ok = _run(t._send_basic_protocol_payload(big_payload, write_with_response=False))

    assert ok is False
    assert call_count["n"] == 2                 # stopped after the failing chunk
    assert t._connection_likely_broken is True
