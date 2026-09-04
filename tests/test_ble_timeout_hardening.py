"""R53 BLE hardening — every raw bleak await in BLETransport is bounded.

A dead / asleep / phone-held device must never hang connect/notify/disconnect
forever (the reconnect path holds the write lock, so an unbounded connect there
would wedge the whole transport). These drive a hanging fake bleak client and
assert the bounded calls fail/return fast instead of blocking.
"""
import asyncio
import os

import pytest

from divoom_lib.protocol import DivoomProtocol
from divoom_lib.exceptions import DeviceConnectionError


def _transport(monkeypatch):
    """A BLETransport with a controllable AsyncMock bleak client, registry/IO
    paths disabled (DIVOOM_MOCK_BLE), and tiny timeouts so tests are fast."""
    monkeypatch.setenv("DIVOOM_MOCK_BLE", "1")
    from unittest.mock import AsyncMock, patch
    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = AsyncMock()
        proto = DivoomProtocol(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
    proto.WRITE_CHARACTERISTIC_UUID = "w"
    proto.NOTIFY_CHARACTERISTIC_UUID = "n"
    proto.READ_CHARACTERISTIC_UUID = "r"
    t = proto._conn._active_transport
    # tiny timeouts so a "hang" resolves in well under a second
    t.CONNECT_TIMEOUT = 0.05
    t.NOTIFY_TIMEOUT = 0.05
    t.STOP_NOTIFY_TIMEOUT = 0.05
    t.DISCONNECT_TIMEOUT = 0.05
    return t


async def _hang(*_a, **_k):
    await asyncio.sleep(30)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_connect_is_bounded(monkeypatch):
    t = _transport(monkeypatch)
    t.client.is_connected = False
    t.client.connect = _hang  # never completes
    with pytest.raises(DeviceConnectionError) as ei:
        _run(t.connect())
    assert "timed out" in str(ei.value).lower()


def test_start_notify_is_bounded(monkeypatch):
    t = _transport(monkeypatch)
    # connect succeeds, then start_notify hangs
    state = {"connected": False}

    async def _ok_connect():
        state["connected"] = True

    def _is_conn():
        return state["connected"]

    t.client.connect = _ok_connect
    type(t.client).is_connected = property(lambda self: state["connected"])
    t.client.start_notify = _hang
    t.use_ios_le_protocol = False  # skip the probe path
    with pytest.raises(DeviceConnectionError) as ei:
        _run(t.connect())
    assert "start_notify" in str(ei.value).lower()


def test_disconnect_calls_stop_notify(monkeypatch):
    t = _transport(monkeypatch)
    t._notifications_started = True
    t.client.is_connected = True
    calls = []
    t.client.stop_notify = lambda *a, **k: calls.append(("stop", a)) or _done()
    t.client.disconnect = lambda *a, **k: calls.append(("disc", a)) or _done()

    async def _done():
        return None

    _run(t.disconnect())
    assert [c[0] for c in calls] == ["stop", "disc"]   # stop_notify BEFORE disconnect
    assert t._notifications_started is False


def test_disconnect_is_bounded(monkeypatch):
    t = _transport(monkeypatch)
    t._notifications_started = False  # skip stop_notify, test the disconnect bound
    t.client.is_connected = True
    t.client.disconnect = _hang
    # must return (not hang, not raise) within the bound
    _run(asyncio.wait_for(t.disconnect(), timeout=2.0))
    assert t._notifications_started is False


def test_transport_swap_tears_down_old(monkeypatch):
    """R53: switching transport type must disconnect (and thus unregister) the
    outgoing transport, so it doesn't leak in the BLE registry or keep the
    CoreBluetooth link open while the new transport connects to the same device."""
    monkeypatch.setenv("DIVOOM_MOCK_BLE", "1")
    from unittest.mock import AsyncMock, patch
    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = AsyncMock()
        proto = DivoomProtocol(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
    conn = proto._conn
    old = AsyncMock()
    conn._active_transport = old
    _run(conn._teardown_outgoing_transport())
    old.disconnect.assert_awaited_once()


def test_teardown_swallows_old_transport_error(monkeypatch):
    """A failing teardown must not block the swap to the new transport."""
    monkeypatch.setenv("DIVOOM_MOCK_BLE", "1")
    from unittest.mock import AsyncMock, patch
    with patch("divoom_lib.divoom.BleakClient") as mk:
        mk.return_value = AsyncMock()
        proto = DivoomProtocol(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice")
    conn = proto._conn
    bad = AsyncMock()
    bad.disconnect.side_effect = RuntimeError("boom")
    conn._active_transport = bad
    _run(conn._teardown_outgoing_transport())   # must not raise


def test_reconnect_clears_stale_os_drop_flag(monkeypatch):
    """R53.17: after an OS drop sets _connection_likely_broken, a successful
    RECONNECT must clear it so is_alive reports the truth immediately. On reconnect
    `use_ios_le_protocol` is already known, so autoprobe is a no-op and never sends
    — nothing else would clear the flag until the next successful payload."""
    from unittest.mock import AsyncMock
    t = _transport(monkeypatch)
    # no real 1s settle wait
    monkeypatch.setattr("divoom_lib.ble_transport.asyncio.sleep", AsyncMock())

    state = {"connected": False}

    async def _ok_connect():
        state["connected"] = True

    t.client.connect = _ok_connect
    type(t.client).is_connected = property(lambda s: state["connected"])
    t.client.start_notify = AsyncMock()
    t.use_ios_le_protocol = False        # already known → autoprobe no-op (reconnect)

    t._on_os_disconnect(None)            # simulate the OS drop
    assert t._connection_likely_broken is True
    assert t.is_alive is False           # honestly degraded while down

    _run(t.connect())                    # reconnect
    assert t._connection_likely_broken is False
    assert t.is_alive is True            # truth restored without waiting for a send
