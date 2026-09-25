"""
Tests for divoom_lib.bt_spp_transport.

These tests are unit tests for the transport's framing, validation, and
state-machine logic. They do NOT exercise real BT hardware. Hardware
integration tests live in tests/test_bt_spp_transport_integration.py and
require the macOS SPP daemon to be functional (see docs/CODE_REVIEW.md
Phase 8).
"""

import logging
import struct

import pytest

from tests.support.framing_fixtures import basic_frame, ios_le_frame, longest_recorded

from divoom_lib import framing
from divoom_lib.bt_spp_transport import (
    DEFAULT_RFCOMM_CHANNEL_IDS,
    BtSppNotification,
    BtSppTransportError,
    BTSppTransport,
)


# ── Channel-ID map ───────────────────────────────────────────────────────────


class TestChannelIdMap:
    def test_known_devices_have_expected_channels(self):
        assert DEFAULT_RFCOMM_CHANNEL_IDS["pixoo"] == 1
        assert DEFAULT_RFCOMM_CHANNEL_IDS["timoo"] == 2
        assert DEFAULT_RFCOMM_CHANNEL_IDS["ditoo"] == 2
        assert DEFAULT_RFCOMM_CHANNEL_IDS["tivoo"] == 2
        assert DEFAULT_RFCOMM_CHANNEL_IDS["tivoo_max"] == 2

    def test_default_channel_is_2(self):
        assert DEFAULT_RFCOMM_CHANNEL_IDS["default"] == 2

    def test_unknown_kind_falls_back_to_2(self):
        # Mimics the lookup in __init__ when kind isn't in the map.
        assert DEFAULT_RFCOMM_CHANNEL_IDS.get("gibberish", 2) == 2


# ── Construction ─────────────────────────────────────────────────────────────


class TestConstruction:
    def test_basic_construction_uses_explicit_channel(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=1)
        assert t.mac_address == "11-75-58-54-b9-13"
        assert t.channel_id == 1
        assert t.is_connected is False
        assert t.mtu == 0

    def test_default_construction_uses_device_kind_lookup(self):
        # No channel_id passed → look up via device_kind, default → 2
        t = BTSppTransport(mac_address="11-75-58-54-b9-13")
        assert t.channel_id == 2

    def test_construction_with_device_kind_looks_up_channel(self):
        t = BTSppTransport(mac_address="11-75-58-3f-fd-aa", device_kind="pixoo")
        assert t.channel_id == 1
        t2 = BTSppTransport(
            mac_address="11-75-58-54-b9-13", device_kind="timoo"
        )
        assert t2.channel_id == 2

    def test_explicit_channel_overrides_device_kind(self):
        t = BTSppTransport(
            mac_address="11-75-58-3f-fd-aa",
            channel_id=5,
            device_kind="pixoo",
        )
        assert t.channel_id == 5

    def test_explicit_channel_zero_overrides_lookup(self):
        # channel_id=0 is an explicit choice — we don't trigger the lookup.
        # (If callers want lookup, they pass channel_id=None.)
        t = BTSppTransport(
            mac_address="11-75-58-54-b9-13",
            channel_id=0,
            device_kind="pixoo",
        )
        assert t.channel_id == 0

    def test_logger_default_is_named(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13")
        assert t.logger.name == "divoom.bt_spp"

    def test_custom_logger_is_respected(self):
        log = logging.getLogger("custom.test.logger")
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", logger=log)
        assert t.logger is log


# ── Internal data parser (the part we can unit-test without a real channel) ─


class TestDataParser:
    """Drive the private _on_data() method and inspect what lands on the queue."""

    def _make_transport(self):
        return BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)

    def test_parses_basic_spp_frame(self):
        t = self._make_transport()
        # Use the encoder to build a known-good basic SPP frame
        frame = basic_frame(0x46)
        t._on_data(frame)
        assert t._rx_queue.qsize() == 1
        notif: BtSppNotification = t._rx_queue.get_nowait()
        assert notif.command_id == 0x46
        assert notif.payload == b""
        assert notif.framing == BTSppTransport.FRAMING_BASIC

    def test_parses_ios_le_frame(self):
        t = self._make_transport()
        # Use the encoder to build a known-good iOS-LE frame for [0x46]
        frame = ios_le_frame(0x46)
        t._on_data(frame)
        assert t._rx_queue.qsize() == 1
        notif = t._rx_queue.get_nowait()
        assert notif.command_id == 0x46
        assert notif.framing == BTSppTransport.FRAMING_IOS_LE
        assert notif.packet_number == 0

    def test_parses_ios_le_frame_with_data(self):
        t = self._make_transport()
        # A recorded frame WITH a payload, and its expectations derived from that
        # payload rather than typed. The obvious choice -- a 0x08 set_volume with
        # one byte -- is not in the C library's record, and the fixture refuses to
        # invent it, which is the right answer: bytes no device was observed to
        # send are a guess wearing a test's clothes.
        frame, payload = longest_recorded("encode_ios_le")
        assert len(payload) > 1, "this test is about a frame that carries data"
        t._on_data(frame)
        notif = t._rx_queue.get_nowait()
        assert notif.command_id == payload[0]
        assert notif.payload == bytes(payload[1:])

    def test_buffers_partial_ios_le_frame(self):
        t = self._make_transport()
        frame = ios_le_frame(0x46)
        # Send only the first half — should NOT emit a notification
        t._on_data(frame[:6])
        assert t._rx_queue.qsize() == 0
        # Send the rest — should emit one
        t._on_data(frame[6:])
        assert t._rx_queue.qsize() == 1
        notif = t._rx_queue.get_nowait()
        assert notif.command_id == 0x46

    def test_mixed_ios_le_then_basic(self):
        t = self._make_transport()
        ios_le = ios_le_frame(0x46)
        basic = basic_frame(0x46)
        t._on_data(ios_le + basic)
        assert t._rx_queue.qsize() == 2
        n1 = t._rx_queue.get_nowait()
        n2 = t._rx_queue.get_nowait()
        assert n1.framing == BTSppTransport.FRAMING_IOS_LE
        assert n2.framing == BTSppTransport.FRAMING_BASIC


# ── Send framing (uses the public send() with a stub channel) ───────────────


class _StubChannel:
    def __init__(self):
        self.written: list[bytes] = []
        self.next_rc: int = 0

    def getMTU(self) -> int:
        return 672

    def writeSync_length_(self, data, length):
        if self.next_rc != 0:
            return self.next_rc
        self.written.append(bytes(data[: int(length)]))
        return 0

    def close(self):
        pass


class TestSendFrame:
    """The transport writes bytes; the daemon frames them (L4).

    There is deliberately no framing test here any more. `send(payload,
    framing=...)` is gone, and a test that reconstructed a frame to check the
    transport "frames correctly" would be testing an encoder this process no
    longer has. What is left to prove is that the frame arrives untouched --
    which is the whole contract now -- and that the bytes the daemon sends for a
    given command are the C library's, which `divoomd`'s
    `spp_bridge_protocol` tests assert against 550 committed vectors.
    """

    @pytest.mark.asyncio
    async def test_send_frame_writes_the_bytes_it_was_given(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        t._channel = _StubChannel()
        t._open_event.set()
        # The C library's own bytes for a bare 0x45 in basic framing.
        frame = bytes.fromhex("01030046490002")
        await t.send_frame(frame)
        assert len(t._channel.written) == 1
        assert t._channel.written[0] == frame

    @pytest.mark.asyncio
    async def test_send_frame_writes_every_byte_value_untouched(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        t._channel = _StubChannel()
        t._open_event.set()
        frame = bytes(range(256))
        await t.send_frame(frame)
        assert t._channel.written[0] == frame

    @pytest.mark.asyncio
    async def test_send_frame_raises_when_not_connected(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        with pytest.raises(BtSppTransportError, match="not connected"):
            await t.send_frame(b"\x01\x03\x00\x46\x49\x00\x02")

    @pytest.mark.asyncio
    async def test_send_frame_refuses_an_empty_frame(self):
        # An empty write is a caller bug that would otherwise reach the device
        # as a zero-length SPP write, which some stacks answer with a silent
        # disconnect.
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        t._channel = _StubChannel()
        t._open_event.set()
        with pytest.raises(ValueError, match="empty frame"):
            await t.send_frame(b"")

    @pytest.mark.asyncio
    async def test_failed_open_tears_down(self, monkeypatch):
        """R53: a failed IOBluetooth open must NOT leak the runloop thread — connect
        tears everything down (disconnect) before propagating."""
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        t.OPEN_TIMEOUT_S = 0.05
        monkeypatch.setattr(t, "_find_serial_port", lambda: None)   # skip serial path
        monkeypatch.setattr(t, "_start_runloop", lambda: None)
        monkeypatch.setattr(t, "_open_blocking", lambda: None)
        disc = {"n": 0}
        real = t.disconnect

        async def _disc():
            disc["n"] += 1
            await real()
        monkeypatch.setattr(t, "disconnect", _disc)

        with pytest.raises(BtSppTransportError, match="timed out"):
            await t.connect()
        assert disc["n"] == 1   # failed connect cleaned up

    @pytest.mark.asyncio
    async def test_send_translates_non_zero_write_rc(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        stub = _StubChannel()
        stub.next_rc = -536870195  # kIOReturnNotOpen
        t._channel = stub
        t._open_event.set()
        with pytest.raises(BtSppTransportError, match="writeSync_length_ returned"):
            await t.send_frame(bytes.fromhex("01030046490002"))

    @pytest.mark.asyncio
    async def test_send_raises_if_channel_closes_during_write(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        # Pre-set the channel to None to simulate it being closed between
        # the precondition check and the actual write. The race-condition
        # check inside the write_lock block is what we're exercising.
        t._channel = None
        t._open_event.set()
        with pytest.raises(BtSppTransportError, match="not connected"):
            await t.send_frame(bytes.fromhex("01030046490002"))


# ── Error type ───────────────────────────────────────────────────────────────


class TestErrorType:
    def test_error_is_runtime_error_subclass(self):
        assert issubclass(BtSppTransportError, RuntimeError)

    def test_error_can_carry_message(self):
        err = BtSppTransportError("boom")
        assert str(err) == "boom"
        assert isinstance(err, RuntimeError)


# ── Disconnect on unconnected transport is a no-op ──────────────────────────


class TestDisconnectNoOp:
    @pytest.mark.asyncio
    async def test_disconnect_when_never_connected(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", channel_id=2)
        # Should not raise even though nothing was opened
        await t.disconnect()
        assert t.is_connected is False


# ── Notification dataclass ───────────────────────────────────────────────────


class TestNotificationDataclass:
    def test_construction(self):
        n = BtSppNotification(
            command_id=0x46, payload=b"\x01\x02", framing="basic"
        )
        assert n.command_id == 0x46
        assert n.payload == b"\x01\x02"
        assert n.framing == "basic"
        assert n.packet_number == 0  # default
        assert n.raw == b""  # default

    def test_construction_with_all_fields(self):
        n = BtSppNotification(
            command_id=0x46,
            payload=b"\x01",
            framing="ios_le",
            packet_number=3,
            raw=b"\xfe\xef\xaa\x55",
        )
        assert n.packet_number == 3
        assert n.raw == b"\xfe\xef\xaa\x55"


# ── Serial Port Fallback Tests ───────────────────────────────────────────────

class TestSerialFallback:
    @pytest.mark.asyncio
    async def test_find_serial_port(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", device_name="Timoo-audio-4")
        
        from unittest.mock import patch
        with patch("glob.glob") as mock_glob:
            mock_glob.return_value = [
                "/dev/cu.Bluetooth-Incoming-Port",
                "/dev/cu.Timoo-audio-4",
                "/dev/cu.Adv360Pro-SerialPort"
            ]
            port = t._find_serial_port()
            assert port == "/dev/cu.Timoo-audio-4"

    @pytest.mark.asyncio
    async def test_find_serial_port_prefix_match(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", device_name="Ditoo-light-2")
        
        from unittest.mock import patch
        with patch("glob.glob") as mock_glob:
            mock_glob.return_value = [
                "/dev/cu.Ditoo-audio-2",
                "/dev/cu.Bluetooth-Incoming"
            ]
            port = t._find_serial_port()
            assert port == "/dev/cu.Ditoo-audio-2"

    @pytest.mark.asyncio
    async def test_serial_connect_send_disconnect(self):
        t = BTSppTransport(mac_address="11-75-58-54-b9-13", device_name="Timoo-audio-4")
        
        from unittest.mock import MagicMock, AsyncMock, patch
        mock_serial = MagicMock()
        mock_port = MagicMock()
        mock_port.is_open = True
        mock_serial.Serial.return_value = mock_port
        
        with patch("glob.glob", return_value=["/dev/cu.Timoo-audio-4"]), \
             patch("sys.platform", "darwin"), \
             patch.dict("sys.modules", {"serial": mock_serial, "IOBluetooth": MagicMock()}):
            
            # Mock sleep locally in the transport module to run instantly
            with patch("divoom_lib.bt_spp_transport.asyncio.sleep", new_callable=AsyncMock):
                await t.connect()
            
            assert t._serial_port is mock_port
            assert t.is_connected is True
            assert t.mtu == 200
            
            # Test send: the frame arrives already framed (L4), and the serial
            # fallback must write those exact bytes.
            frame = bytes.fromhex("01030046490002")
            await t.send_frame(frame)
            mock_port.write.assert_called_once_with(frame)
            
            # Test disconnect
            await t.disconnect()
            assert t._serial_port is None
            assert t.is_connected is False
            mock_port.close.assert_called_once()
