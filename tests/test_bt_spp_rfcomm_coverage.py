"""Coverage push (R61 #1) for divoom_lib/bt_spp_rfcomm.py.

This module is the macOS IOBluetooth RFCOMM backend: run-loop thread management,
SDP channel discovery, the blocking RFCOMM open (+ its nested delegate), and the
shared inbound framer (`_on_data`). None of it may touch real CoreBluetooth /
IOBluetooth — that SIGABRTs (TCC violation) under a shell without Bluetooth
authorization and aborts the whole pytest process (see commit e26fc6d, and
tests/test_spp_integration.py). Every objc/IOBluetooth/Foundation import is a
call-time `import` *inside* the method under test, so we inject fakes into
sys.modules for the duration of each test via patch.dict, and never let the
real modules (if actually installed) get touched.
"""
from __future__ import annotations

import queue
import sys
import threading
import time as real_time
import types
from unittest.mock import MagicMock, patch

import pytest

from divoom_lib import models
from divoom_lib.framing import encode_basic_payload, encode_ios_le_payload
from divoom_lib.bt_spp_transport import BTSppTransport


def _t():
    return BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)


# ── _discover_rfcomm_channel — no objc/IOBluetooth needed, `device` is generic ──


class _FakeService:
    def __init__(self, name, chan, raise_on_none_arg=False, raise_on_noarg_too=False):
        self._name = name
        self._chan = chan
        self._raise_on_none_arg = raise_on_none_arg
        self._raise_on_noarg_too = raise_on_noarg_too

    def getServiceName(self):
        return self._name

    def getRFCOMMChannelID_(self, _none):
        if self._raise_on_none_arg:
            raise Exception("no such selector")
        return (0, self._chan) if self._chan is not None else (-1, None)

    def getRFCOMMChannelID(self):
        # no-arg fallback used when the two-arg selector isn't available
        if self._raise_on_noarg_too:
            raise Exception("no-arg selector missing too")
        return self._chan if self._chan is not None else -1


class TestDiscoverRfcommChannel:
    def test_finds_serial_named_service_first(self):
        t = _t()
        dev = MagicMock()
        dev.services.return_value = [
            _FakeService("Generic", 7),
            _FakeService("Serial Port", 3),
        ]
        chan = t._discover_rfcomm_channel(dev)
        assert chan == 3
        dev.performSDPQuery_.assert_called_once_with(None)

    def test_falls_back_to_first_valid_channel_when_no_serial_name(self):
        t = _t()
        dev = MagicMock()
        dev.services.return_value = [
            _FakeService("Generic", None),  # -1, skipped
            _FakeService("Other", 9),
        ]
        chan = t._discover_rfcomm_channel(dev)
        assert chan == 9

    def test_returns_none_when_all_channels_invalid(self):
        t = _t()
        dev = MagicMock()
        dev.services.return_value = [_FakeService("A", None), _FakeService("B", None)]
        assert t._discover_rfcomm_channel(dev) is None

    def test_returns_none_when_no_services_ever_appear(self, monkeypatch):
        t = _t()
        dev = MagicMock()
        dev.services.return_value = []
        monkeypatch.setattr(real_time, "sleep", lambda *_a, **_k: None)
        assert t._discover_rfcomm_channel(dev) is None
        # Polled up to 30 times per the method's retry bound.
        assert dev.services.call_count >= 1

    def test_getrfcommchannelid_falls_back_to_noarg_selector(self):
        t = _t()
        dev = MagicMock()
        dev.services.return_value = [_FakeService("Serial", 4, raise_on_none_arg=True)]
        assert t._discover_rfcomm_channel(dev) == 4

    def test_exception_during_sdp_query_is_caught_and_logged(self, caplog):
        t = _t()
        dev = MagicMock()
        dev.performSDPQuery_.side_effect = RuntimeError("sdp boom")
        with caplog.at_level("WARNING"):
            assert t._discover_rfcomm_channel(dev) is None
        assert any("SDP query failed" in r.message for r in caplog.records)

    def test_both_channel_id_selectors_raise_treated_as_invalid(self):
        """_get_chan's inner except (no-arg selector also missing) must swallow
        the second exception and report the channel as invalid (-1), not crash."""
        t = _t()
        dev = MagicMock()
        # Named "serial" so the first loop tries it via _get_chan; both selectors
        # raise, so it must fall through the second loop too and land on None.
        dev.services.return_value = [
            _FakeService("Serial Port", 1, raise_on_none_arg=True, raise_on_noarg_too=True)
        ]
        assert t._discover_rfcomm_channel(dev) is None

    def test_serial_named_service_with_invalid_channel_continues_to_next(self):
        """A 'serial'-named service with an invalid channel must not stop the
        first loop (91->87) — a later serial-named service (or the fallback
        loop) must still be tried."""
        t = _t()
        dev = MagicMock()
        dev.services.return_value = [
            _FakeService("Serial Port A", None),   # named 'serial' but c <= 0
            _FakeService("Serial Port B", 6),      # named 'serial', valid
        ]
        assert t._discover_rfcomm_channel(dev) == 6


# ── Fake objc / IOBluetooth / Foundation modules for _open_blocking ─────────


class _FakeSuperResult:
    """objc.super(cls, obj).init() must return `obj` unchanged (real PyObjC
    semantics for a trivial override)."""

    def __init__(self, obj):
        self._obj = obj

    def init(self):
        return self._obj


class _FakeNSObject:
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    def retain(self):
        pass


def _install_fake_objc_stack(monkeypatch, device):
    """Install fakes for `objc`, `IOBluetooth`, `Foundation` so `_open_blocking`'s
    call-time imports resolve to controllable doubles instead of touching real
    CoreBluetooth. Returns the fake IOBluetoothDevice class-level mock so tests
    can assert on `deviceWithAddressString_`."""
    fake_objc = types.ModuleType("objc")
    fake_objc.super = lambda cls, obj: _FakeSuperResult(obj)

    fake_iobt = types.ModuleType("IOBluetooth")
    fake_iobt.IOBluetoothDevice = MagicMock()
    fake_iobt.IOBluetoothDevice.deviceWithAddressString_.return_value = device

    fake_foundation = types.ModuleType("Foundation")
    fake_foundation.NSObject = _FakeNSObject

    monkeypatch.setitem(sys.modules, "objc", fake_objc)
    monkeypatch.setitem(sys.modules, "IOBluetooth", fake_iobt)
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    return fake_iobt


class _FakeDevice:
    def __init__(self):
        self.open_rc = 0
        self.open_channel = MagicMock(name="channel")

    def openRFCOMMChannelAsync_withChannelID_delegate_(self, _none, _channel_id, _delegate):
        return (self.open_rc, self.open_channel)


class TestOpenBlocking:
    def test_device_none_sets_error_and_open_event(self, monkeypatch):
        t = _t()
        _install_fake_objc_stack(monkeypatch, device=None)
        t._open_blocking()
        assert t._device is None
        assert "nil for" in t._last_error
        assert t._open_event.is_set()
        assert t._channel is None

    def test_successful_open_uses_discovered_channel_override(self, monkeypatch):
        t = _t()
        assert t.channel_id == 2
        dev = _FakeDevice()
        dev.open_rc = 0
        _install_fake_objc_stack(monkeypatch, device=dev)
        monkeypatch.setattr(t, "_discover_rfcomm_channel", lambda _d: 9)

        t._open_blocking()

        assert t.channel_id == 9  # overridden by SDP discovery
        assert t._channel is dev.open_channel
        assert t._last_error is None
        assert t._delegate is not None
        # Success path does not itself set _open_event — that happens later via
        # the IOBluetooth delegate's rfcommChannelOpenComplete_status_ callback.
        assert not t._open_event.is_set()

    def test_nonzero_open_rc_sets_error_and_event(self, monkeypatch):
        t = _t()
        dev = _FakeDevice()
        dev.open_rc = -536870212  # arbitrary nonzero IOReturn
        _install_fake_objc_stack(monkeypatch, device=dev)
        monkeypatch.setattr(t, "_discover_rfcomm_channel", lambda _d: None)

        t._open_blocking()

        assert "openRFCOMMChannelAsync_ returned" in t._last_error
        assert t._open_event.is_set()
        assert t._channel is None  # never assigned on failure

    def test_exception_in_open_blocking_is_caught(self, monkeypatch):
        t = _t()
        fake_iobt = types.ModuleType("IOBluetooth")
        fake_iobt.IOBluetoothDevice = MagicMock()
        fake_iobt.IOBluetoothDevice.deviceWithAddressString_.side_effect = RuntimeError("boom")
        fake_objc = types.ModuleType("objc")
        fake_objc.super = lambda cls, obj: _FakeSuperResult(obj)
        fake_foundation = types.ModuleType("Foundation")
        fake_foundation.NSObject = _FakeNSObject
        monkeypatch.setitem(sys.modules, "objc", fake_objc)
        monkeypatch.setitem(sys.modules, "IOBluetooth", fake_iobt)
        monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)

        t._open_blocking()

        assert "exception in _open_blocking" in t._last_error
        assert t._open_event.is_set()

    def test_delegate_callbacks_drive_outer_state(self, monkeypatch):
        """After a successful open, the delegate instance IOBluetooth would call
        back into is captured on `self._delegate` — drive its three callbacks
        directly (this is the only way to exercise that nested class's body)."""
        t = _t()
        dev = _FakeDevice()
        _install_fake_objc_stack(monkeypatch, device=dev)
        monkeypatch.setattr(t, "_discover_rfcomm_channel", lambda _d: None)
        t._open_blocking()
        delegate = t._delegate
        assert delegate is not None

        # status == 0 → no error recorded, but the open event fires.
        delegate.rfcommChannelOpenComplete_status_(dev.open_channel, 0)
        assert t._last_error is None
        assert t._open_event.is_set()

        # status != 0 → error recorded (still sets the event again, harmlessly).
        t._open_event.clear()
        delegate.rfcommChannelOpenComplete_status_(dev.open_channel, 5)
        assert "open status=5" in t._last_error
        assert t._open_event.is_set()

        # Inbound data is routed through outer._on_data and lands on the rx queue.
        frame = encode_basic_payload([0x46])
        delegate.rfcommChannelData_data_length_(dev.open_channel, frame, len(frame))
        assert t._rx_queue.qsize() == 1

        # Zero-length data callback must be a no-op (guarded by `if n > 0`).
        delegate.rfcommChannelData_data_length_(dev.open_channel, b"", 0)
        assert t._rx_queue.qsize() == 1

        # Channel-closed callback sets the close event.
        assert not t._close_event.is_set()
        delegate.rfcommChannelClosed_(dev.open_channel)
        assert t._close_event.is_set()


# ── _start_runloop / _runloop_main ──────────────────────────────────────────


class TestRunloop:
    def test_already_alive_thread_short_circuits(self, monkeypatch):
        t = _t()

        class _AliveThread:
            def is_alive(self):
                return True

        t._runloop_thread = _AliveThread()
        called = {"n": 0}
        monkeypatch.setattr(
            threading, "Thread", lambda *a, **k: called.__setitem__("n", called["n"] + 1)
        )
        t._start_runloop()
        assert called["n"] == 0  # never spawned a new thread

    def test_spawns_thread_and_runloop_main_uses_fake_foundation(self, monkeypatch):
        t = _t()

        class _FakeRunLoop:
            def runMode_beforeDate_(self, _mode, _date):
                real_time.sleep(0.01)

        fake_foundation = types.ModuleType("Foundation")
        fake_foundation.NSRunLoop = MagicMock()
        fake_foundation.NSRunLoop.currentRunLoop.return_value = _FakeRunLoop()
        fake_foundation.NSDate = MagicMock()
        fake_foundation.NSDate.dateWithTimeIntervalSinceNow_.return_value = object()
        fake_foundation.NSRunLoopCommonModes = object()
        monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)

        t._start_runloop()
        # _start_runloop polls until self._runloop is set by the background thread.
        assert t._runloop is not None
        assert t._runloop_thread is not None and t._runloop_thread.is_alive()

        t._close_event.set()  # let the background loop exit
        t._runloop_thread.join(timeout=2.0)
        assert not t._runloop_thread.is_alive()

    def test_polls_until_timeout_when_runloop_never_appears(self, monkeypatch):
        """If the background thread never gets around to setting self._runloop
        (e.g. it's still inside the Foundation import), _start_runloop must poll
        all 50 iterations and return anyway rather than block forever."""
        t = _t()

        class _NeverStartsThread:
            def start(self):
                pass  # deliberately never runs the target, so _runloop stays None

            def is_alive(self):
                return False

        monkeypatch.setattr(threading, "Thread", lambda *a, **k: _NeverStartsThread())
        sleep_calls = {"n": 0}

        def _fast_sleep(_seconds):
            sleep_calls["n"] += 1

        monkeypatch.setattr(real_time, "sleep", _fast_sleep)

        t._start_runloop()

        assert t._runloop is None
        assert sleep_calls["n"] == 50  # exhausted the whole poll bound


# ── _on_data edge cases not already covered by test_bt_spp_transport.py ─────


class TestOnDataEdgeCases:
    def _make(self):
        return BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)

    def test_buffers_partial_frame_above_min_length(self):
        """Existing test_buffers_partial_ios_le_frame sends < IOS_LE_MIN_DATA_LENGTH
        bytes, which never even enters the while loop. This drives the *other*
        partial-frame branch: len(rx_buf) >= MIN_DATA_LENGTH but still < frame_len
        (line 172's `break`)."""
        t = self._make()
        frame = encode_ios_le_payload([0x08, 0x01, 0x02, 0x03, 0x04, 0x05])
        assert len(frame) >= models.IOS_LE_MIN_DATA_LENGTH + 4
        # Feed enough to pass the MIN_DATA_LENGTH gate but not the whole frame.
        partial = frame[: models.IOS_LE_MIN_DATA_LENGTH + 1]
        assert len(partial) < len(frame)
        t._on_data(partial)
        assert t._rx_queue.qsize() == 0
        assert bytes(t._rx_buf[:4]) == bytes(models.IOS_LE_HEADER)  # still parked, not dropped

        t._on_data(frame[len(partial):])
        assert t._rx_queue.qsize() == 1
        notif = t._rx_queue.get_nowait()
        assert notif.command_id == 0x08

    def test_parse_failure_resyncs_by_dropping_one_byte(self):
        """A full-length frame with a valid header/length but a corrupted end
        marker makes parse_ios_le_notification return None (not a length overrun,
        which is the case test_spp_robustness.py already covers) — must resync by
        dropping a single byte, not stall."""
        t = self._make()
        header = bytes(models.IOS_LE_HEADER)
        frame_len = 12
        length_field = (frame_len - 7).to_bytes(2, "little")
        # 6 filler bytes total (packet#, command, data..., checksum lo/hi), last
        # byte deliberately wrong (must be MESSAGE_END_BYTE=0x02 to parse).
        body = bytes([0, 0x46, 0, 0, 0, 0x99])
        bogus = header + length_field + body
        assert len(bogus) == frame_len
        good = encode_basic_payload([0x44])

        t._on_data(bogus + good)

        msgs = []
        while not t._rx_queue.empty():
            msgs.append(t._rx_queue.get_nowait())
        assert any(m.command_id == 0x44 for m in msgs), "real frame lost after bad end-marker"
