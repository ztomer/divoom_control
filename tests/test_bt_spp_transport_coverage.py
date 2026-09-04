"""Coverage push (R61 #1) for divoom_lib/bt_spp_transport.py.

Targets the connect()/disconnect() branch structure (serial-vs-IOBluetooth
fallback, teardown-on-failure, exception swallowing during cleanup),
send()'s race-condition guards, read_notification()/`_rx_loop`, the
send_command / send_command_and_wait_for_response / wait_for_response chain,
and the async context-manager methods.

Everything that could touch real hardware (serial ports, IOBluetooth) is
mocked at the object level (stub instances / monkeypatched private helpers) —
never a real BT call. `_open_blocking` / `_start_runloop` are monkeypatched
directly rather than re-faking objc/IOBluetooth here (that's covered in depth
by tests/test_bt_spp_rfcomm_coverage.py).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from divoom_lib import models
from divoom_lib.bt_spp_transport import BTSppTransport, BtSppTransportError, BtSppNotification


def _t(**kw):
    return BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2, logger=logging.getLogger("spp_cov"), **kw)


# ── _find_serial_port ────────────────────────────────────────────────────────


class TestFindSerialPort:
    def test_returns_none_without_device_name(self):
        t = _t()
        assert t.device_name is None
        assert t._find_serial_port() is None

    def test_prefix_loop_skips_non_matching_then_matches(self):
        t = _t(device_name="Ditoo-Plus-9")
        with patch("glob.glob", return_value=["/dev/cu.Bluetooth-Incoming-Port", "/dev/cu.ditoo-serial-9"]):
            # sanitized exact/substring match fails for both (different mangling),
            # but the prefix ("ditoo") loop must skip port 1 before matching port 2.
            port = t._find_serial_port()
        assert port == "/dev/cu.ditoo-serial-9"

    def test_returns_none_when_nothing_matches(self):
        t = _t(device_name="Zzz-Nomatch-1")
        with patch("glob.glob", return_value=["/dev/cu.Bluetooth-Incoming-Port"]):
            assert t._find_serial_port() is None

    def test_short_prefix_skips_prefix_loop_entirely(self):
        """A device_name whose first '-'-segment is under 3 chars must not even
        enter the prefix-matching loop (guarded by `len(prefix) >= 3`)."""
        t = _t(device_name="Ab-nomatch-device")
        assert len(t.device_name.split("-")[0]) < 3
        with patch("glob.glob", return_value=["/dev/cu.Bluetooth-Incoming-Port"]):
            assert t._find_serial_port() is None


# ── _serial_read_loop branches ──────────────────────────────────────────────


class TestSerialReadLoop:
    def test_exits_immediately_when_port_is_none(self):
        t = _t()
        t._serial_port = None
        t._serial_read_loop()  # must return without raising (no port to read)

    def test_exits_immediately_when_port_not_open(self):
        t = _t()
        port = MagicMock()
        port.is_open = False
        t._serial_port = port
        t._serial_read_loop()
        port.read.assert_not_called()

    def test_empty_chunk_does_not_call_on_data_and_loop_continues(self):
        """An empty (falsy) read must skip `_on_data` and loop back — not treat
        a zero-byte read as an error or as real data."""
        t = _t()
        port = MagicMock()
        port.is_open = True
        calls = {"n": 0}

        def _read(_n):
            calls["n"] += 1
            if calls["n"] >= 2:
                t._close_event.set()  # stop the loop after a couple of empty reads
            return b""

        port.read.side_effect = _read
        t._serial_port = port
        with patch.object(t, "_on_data") as on_data:
            t._serial_read_loop()
        on_data.assert_not_called()
        assert calls["n"] >= 2


# ── connect(): notification-queue drain + darwin/non-darwin branch ─────────


class TestConnectBranches:
    @pytest.mark.asyncio
    async def test_connect_drains_stale_notifications(self, monkeypatch):
        t = _t()
        t.notification_queue.put_nowait({"command_id": 1, "payload": bytearray()})
        assert not t.notification_queue.empty()
        monkeypatch.setattr(t, "_find_serial_port", lambda: None)
        monkeypatch.setattr(t, "_start_runloop", lambda: None)
        monkeypatch.setattr(t, "_open_blocking", lambda: None)
        t._open_event.set()  # so connect() doesn't block waiting for it
        await t.connect()
        assert t.notification_queue.empty()
        await t.disconnect()

    @pytest.mark.asyncio
    async def test_connect_on_non_darwin_skips_serial_branch_entirely(self, monkeypatch):
        t = _t()
        monkeypatch.setattr(sys, "platform", "linux")
        find_port = MagicMock(return_value="/dev/should-not-be-used")
        monkeypatch.setattr(t, "_find_serial_port", find_port)
        monkeypatch.setattr(t, "_start_runloop", lambda: None)
        monkeypatch.setattr(t, "_open_blocking", lambda: None)
        t._open_event.set()
        await t.connect()
        find_port.assert_not_called()  # the whole `if sys.platform == "darwin":` block was skipped
        assert t._last_error is None
        await t.disconnect()

    @pytest.mark.asyncio
    async def test_already_connected_is_a_noop(self, caplog):
        t = _t()
        t._channel = object()
        with caplog.at_level(logging.DEBUG):
            await t.connect()
        assert any("already connected" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_serial_exception_cleans_up_and_falls_back_to_iobluetooth(self, monkeypatch, caplog):
        """A mid-serial-connect exception must log+clean up self._serial_port
        (even when closing it also raises) then fall through to the IOBluetooth
        path rather than propagate."""
        t = _t(device_name="Timoo-audio-4")
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(t, "_find_serial_port", lambda: "/dev/cu.fake")

        bad_port = MagicMock()
        bad_port.is_open = False  # must NOT look already-connected at connect()'s top check
        bad_port.close.side_effect = Exception("close also fails")
        t._serial_port = bad_port  # pre-set so the except branch's cleanup runs

        fake_serial_module = MagicMock()
        fake_serial_module.Serial.side_effect = OSError("port busy")
        monkeypatch.setitem(sys.modules, "serial", fake_serial_module)

        monkeypatch.setattr(t, "_start_runloop", lambda: None)
        monkeypatch.setattr(t, "_open_blocking", lambda: None)
        t._open_event.set()

        with caplog.at_level(logging.WARNING):
            await t.connect()

        assert any("Serial connection failed" in r.message for r in caplog.records)
        assert t._serial_port is None
        assert t._serial_read_thread is None
        assert t._last_error is None  # classic path still succeeded afterwards
        await t.disconnect()

    @pytest.mark.asyncio
    async def test_serial_exception_before_port_ever_set_skips_close_cleanup(self, monkeypatch, caplog):
        """If the failure happens before self._serial_port is ever assigned
        (e.g. _find_serial_port() itself raises), the except's `if
        self._serial_port:` guard must skip the close/None-reset — there's
        nothing to close."""
        t = _t(device_name="Timoo-audio-4")
        monkeypatch.setattr(sys, "platform", "darwin")
        assert t._serial_port is None

        def _boom():
            raise RuntimeError("cannot enumerate ports")

        monkeypatch.setattr(t, "_find_serial_port", _boom)
        monkeypatch.setattr(t, "_start_runloop", lambda: None)
        monkeypatch.setattr(t, "_open_blocking", lambda: None)
        t._open_event.set()

        with caplog.at_level(logging.WARNING):
            await t.connect()

        assert any("Serial connection failed" in r.message for r in caplog.records)
        assert t._serial_port is None
        await t.disconnect()

    @pytest.mark.asyncio
    async def test_last_error_after_open_raises(self, monkeypatch):
        t = _t()
        monkeypatch.setattr(t, "_find_serial_port", lambda: None)
        monkeypatch.setattr(t, "_start_runloop", lambda: None)

        def _fake_open_blocking():
            t._last_error = "simulated open failure"
            t._open_event.set()

        monkeypatch.setattr(t, "_open_blocking", _fake_open_blocking)
        with pytest.raises(BtSppTransportError, match="RFCOMM open failed"):
            await t.connect()

    @pytest.mark.asyncio
    async def test_successful_classic_connect_creates_rx_task(self, monkeypatch, caplog):
        t = _t()
        monkeypatch.setattr(t, "_find_serial_port", lambda: None)
        monkeypatch.setattr(t, "_start_runloop", lambda: None)

        def _fake_open_blocking():
            t._channel = MagicMock()
            t._open_event.set()

        monkeypatch.setattr(t, "_open_blocking", _fake_open_blocking)
        with caplog.at_level(logging.INFO):
            await t.connect()
        assert any("BT Classic SPP open" in r.message for r in caplog.records)
        assert t._rx_task is not None
        await t.disconnect()


# ── disconnect(): exception-swallowing cleanup paths ────────────────────────


class TestDisconnectCleanup:
    @pytest.mark.asyncio
    async def test_serial_port_close_exception_is_swallowed(self):
        t = _t()
        bad_port = MagicMock()
        bad_port.close.side_effect = Exception("boom")
        t._serial_port = bad_port
        await t.disconnect()  # must not raise
        assert t._serial_port is None

    @pytest.mark.asyncio
    async def test_channel_close_exception_is_swallowed(self):
        t = _t()
        bad_channel = MagicMock()
        bad_channel.close.side_effect = Exception("boom")
        t._channel = bad_channel
        await t.disconnect()  # must not raise
        assert t._channel is None

    @pytest.mark.asyncio
    async def test_runloop_thread_is_joined_and_cleared(self):
        t = _t()
        thread = MagicMock()
        t._runloop_thread = thread
        await t.disconnect()
        thread.join.assert_called_once_with(2.0)
        assert t._runloop_thread is None


# ── send(): race-condition guards inside the executor closures ─────────────


class TestSendRaceGuards:
    @pytest.mark.asyncio
    async def test_serial_port_closes_during_write_raises(self, monkeypatch):
        t = _t()
        port = MagicMock()
        port.is_open = True
        t._serial_port = port

        async def _racy_to_thread(fn, *a):
            t._serial_port = None  # closed by another task between check and write
            return fn(*a)

        monkeypatch.setattr("divoom_lib.bt_spp_transport.asyncio.to_thread", _racy_to_thread)
        with pytest.raises(BtSppTransportError, match="serial port closed during write"):
            await t.send([0x45])

    @pytest.mark.asyncio
    async def test_channel_closes_during_write_raises(self, monkeypatch):
        t = _t()
        t._channel = MagicMock()  # is_connected True at the precondition check
        t._open_event.set()

        async def _racy_to_thread(fn, *a):
            t._channel = None  # closed by another task between check and write
            return fn(*a)

        monkeypatch.setattr("divoom_lib.bt_spp_transport.asyncio.to_thread", _racy_to_thread)
        with pytest.raises(BtSppTransportError, match="channel closed during write"):
            await t.send([0x45])


# ── read_notification / _rx_loop ─────────────────────────────────────────────


class TestReadNotificationAndRxLoop:
    @pytest.mark.asyncio
    async def test_read_notification_returns_queued_item(self):
        t = _t()
        notif = BtSppNotification(command_id=0x46, payload=b"", framing="basic")
        t._rx_queue.put(notif)
        result = await t.read_notification(timeout=1.0)
        assert result is notif

    @pytest.mark.asyncio
    async def test_read_notification_times_out_on_empty_queue(self):
        t = _t()
        with pytest.raises(asyncio.TimeoutError, match="no notification within"):
            await t.read_notification(timeout=0.05)

    @pytest.mark.asyncio
    async def test_rx_loop_forwards_notifications_until_disconnected(self):
        t = _t()
        t._channel = object()  # is_connected True
        notif = BtSppNotification(command_id=0x46, payload=b"\x01", framing="basic")
        t._rx_queue.put(notif)

        task = asyncio.create_task(t._rx_loop())
        # Wait for the notification to surface on the public queue.
        got = await asyncio.wait_for(t.notification_queue.get(), timeout=2.0)
        assert got["command_id"] == 0x46
        assert bytes(got["payload"]) == b"\x01"

        t._channel = None  # is_connected -> False, loop's `while` condition ends it
        await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_rx_loop_breaks_on_unexpected_exception(self, monkeypatch, caplog):
        t = _t()
        t._channel = object()

        async def _boom(timeout):
            raise RuntimeError("unexpected reader failure")

        monkeypatch.setattr(t, "read_notification", _boom)
        with caplog.at_level(logging.ERROR):
            await asyncio.wait_for(t._rx_loop(), timeout=2.0)
        assert any("Error in SPP notification loop" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_rx_loop_cancellation_breaks_cleanly(self):
        """_rx_loop catches CancelledError internally and `break`s out of the
        while loop rather than propagating — a graceful stop, not a crash."""
        t = _t()
        t._channel = object()
        task = asyncio.create_task(t._rx_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        await task  # must complete cleanly (no re-raised CancelledError)
        assert task.done() and not task.cancelled()


# ── send_command / send_command_and_wait_for_response / wait_for_response ──


class TestCommandChain:
    @pytest.mark.asyncio
    async def test_send_command_resolves_string_name_and_defaults_args(self, monkeypatch):
        t = _t()
        captured = {}

        async def _fake_send_payload(payload_bytes, **kwargs):
            captured["payload"] = payload_bytes
            return True

        monkeypatch.setattr(t, "send_payload", _fake_send_payload)
        ok = await t.send_command("set volume")
        assert ok is True
        assert captured["payload"] == [models.COMMANDS["set volume"]]

    @pytest.mark.asyncio
    async def test_send_command_accepts_int_id_and_extra_args(self, monkeypatch):
        t = _t()
        captured = {}

        async def _fake_send_payload(payload_bytes, **kwargs):
            captured["payload"] = payload_bytes
            return True

        monkeypatch.setattr(t, "send_payload", _fake_send_payload)
        ok = await t.send_command(0x08, args=[0x32])
        assert ok is True
        assert captured["payload"] == [0x08, 0x32]

    @pytest.mark.asyncio
    async def test_wait_for_response_returns_matching_payload_immediately(self):
        t = _t()
        cmd_id = models.COMMANDS["set light mode"]
        await t.notification_queue.put({"command_id": cmd_id, "payload": b"\x01"})
        result = await t.wait_for_response(cmd_id, timeout=1.0)
        assert result == b"\x01"

    @pytest.mark.asyncio
    async def test_wait_for_response_skips_generic_ack_then_matches(self):
        t = _t()
        cmd_id = models.COMMANDS["set light mode"]  # in GENERIC_ACK_COMMANDS
        assert cmd_id in models.GENERIC_ACK_COMMANDS
        await t.notification_queue.put({"command_id": models.GENERIC_ACK_COMMAND_ID, "payload": b"\x00"})
        await t.notification_queue.put({"command_id": cmd_id, "payload": b"\x02"})
        result = await t.wait_for_response(cmd_id, timeout=1.0)
        assert result == b"\x02"

    @pytest.mark.asyncio
    async def test_wait_for_response_times_out_returns_none(self):
        t = _t()
        result = await t.wait_for_response(0x99, timeout=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_response_already_expired_breaks_before_first_get(self):
        """A non-positive timeout must hit the `remaining <= 0` guard on the very
        first loop check, distinct from the asyncio.wait_for TimeoutError path
        exercised by test_wait_for_response_times_out_returns_none."""
        t = _t()
        result = await t.wait_for_response(0x99, timeout=-1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_response_ignores_stray_notification_then_matches(self):
        """A notification matching neither the expected command nor a generic
        ack must be silently ignored (loop back to the top), not treated as a
        match or an ack."""
        t = _t()
        cmd_id = models.COMMANDS["set light mode"]
        await t.notification_queue.put({"command_id": 0xFE, "payload": b"unrelated"})
        await t.notification_queue.put({"command_id": cmd_id, "payload": b"\x05"})
        result = await t.wait_for_response(cmd_id, timeout=1.0)
        assert result == b"\x05"

    @pytest.mark.asyncio
    async def test_send_command_and_wait_for_response_full_success(self, monkeypatch):
        t = _t()
        cmd_id = models.COMMANDS["set light mode"]

        async def _fake_send_command(command, args=None):
            await t.notification_queue.put({"command_id": cmd_id, "payload": b"\x07"})
            return True

        monkeypatch.setattr(t, "send_command", _fake_send_command)
        result = await t.send_command_and_wait_for_response("set light mode", timeout=1.0)
        assert result == b"\x07"
        # wait_for_response clears _expected_response_command back to None once a
        # matching response is found — it's a "waiting" marker, not a sticky record.
        assert t._expected_response_command is None

    @pytest.mark.asyncio
    async def test_send_command_and_wait_for_response_returns_none_when_send_fails(self, monkeypatch):
        t = _t()

        async def _fake_send_command(command, args=None):
            return False

        monkeypatch.setattr(t, "send_command", _fake_send_command)
        result = await t.send_command_and_wait_for_response("set light mode", timeout=1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_send_command_and_wait_for_response_drains_stale_queue(self, monkeypatch):
        t = _t()
        cmd_id = models.COMMANDS["set light mode"]
        await t.notification_queue.put({"command_id": 0xFF, "payload": b"stale"})

        async def _fake_send_command(command, args=None):
            await t.notification_queue.put({"command_id": cmd_id, "payload": b"\x09"})
            return True

        monkeypatch.setattr(t, "send_command", _fake_send_command)
        result = await t.send_command_and_wait_for_response("set light mode", timeout=1.0)
        assert result == b"\x09"
