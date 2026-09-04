"""macOS IOBluetooth RFCOMM backend for the SPP transport.

Split out of bt_spp_transport.py (R53.12): the PyObjC/IOBluetooth run-loop, SDP
channel discovery, the blocking RFCOMM open + delegate, and the shared inbound
framer (`_on_data`, used by both the IOBluetooth delegate and the pyserial read
loop). `BTSppTransport` mixes this in; the methods rely on its instance attributes
(`mac_address`, `channel_id`, `logger`, `_runloop*`, `_open_event`, `_close_event`,
`_rx_queue`, `_rx_buf`, `_last_error`, `_device`, `_delegate`, `_channel`) and its
`FRAMING_*` class constants.

`BtSppNotification` lives here (not in bt_spp_transport) so this module needs no
import back into bt_spp_transport — bt_spp_transport re-exports it for callers.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field

from . import models
from .framing import parse_basic_protocol_frames, parse_ios_le_notification


@dataclass
class BtSppNotification:
    command_id: int
    payload: bytes
    framing: str
    packet_number: int = 0
    raw: bytes = field(default=b"")


class _SppRfcommMixin:
    # Upper bound on a single iOS-LE frame length decoded from bytes 4-5. Real
    # device notifications are tiny (acks, page lists); anything beyond this is a
    # corrupt length field, not a real frame — used to resync the RX parser.
    _MAX_IOS_LE_FRAME = 8192

    def _start_runloop(self) -> None:
        if self._runloop_thread is not None and self._runloop_thread.is_alive():
            return
        self._open_event.clear()
        self._close_event.clear()
        self._rx_queue = queue.Queue()
        self._rx_buf = bytearray()
        self._runloop_thread = threading.Thread(
            target=self._runloop_main, name="bt-spp-runloop", daemon=True
        )
        self._runloop_thread.start()
        for _ in range(50):
            if self._runloop is not None:
                return
            import time as _t
            _t.sleep(0.02)

    def _runloop_main(self) -> None:
        from Foundation import NSDate, NSRunLoop, NSRunLoopCommonModes
        self._runloop = NSRunLoop.currentRunLoop()
        while not self._close_event.is_set():
            self._runloop.runMode_beforeDate_(
                NSRunLoopCommonModes,
                NSDate.dateWithTimeIntervalSinceNow_(0.05),
            )

    def _discover_rfcomm_channel(self, device) -> int | None:
        try:
            self.logger.debug(f"Performing SDP query for {self.mac_address}...")
            device.performSDPQuery_(None)
            import time
            for _ in range(30):
                services = device.services() or []
                if services:
                    break
                time.sleep(0.1)

            def _get_chan(s):
                try:
                    rc, chan = s.getRFCOMMChannelID_(None)
                    if rc == 0: return chan
                except Exception:
                    try:
                        return s.getRFCOMMChannelID()
                    except Exception:
                        pass
                return -1

            for s in services:
                name = getattr(s, "getServiceName", lambda: None)()
                if name and "serial" in name.lower():
                    c = _get_chan(s)
                    if c > 0: return c
            for s in services:
                c = _get_chan(s)
                if c > 0: return c
        except Exception as e:
            self.logger.warning(f"SDP query failed: {e}")
        return None

    def _open_blocking(self) -> None:
        import objc
        from IOBluetooth import IOBluetoothDevice
        from Foundation import NSObject

        outer = self

        class _Delegate(NSObject):
            def init(self):
                self = objc.super(_Delegate, self).init()
                self._self_ref = self
                return self

            def rfcommChannelOpenComplete_status_(self, ch, status):
                status = int(status)
                if status != 0:
                    outer._last_error = f"open status={status} (0x{status & 0xFFFFFFFF:08X})"
                outer._open_event.set()

            def rfcommChannelData_data_length_(self, ch, data, length):
                n = int(length) if length else 0
                if n > 0:
                    outer._on_data(bytes(data[:n]))

            def rfcommChannelClosed_(self, ch):
                outer._close_event.set()

        try:
            device = IOBluetoothDevice.deviceWithAddressString_(self.mac_address)
            if device is None:
                self._last_error = f"IOBluetoothDevice nil for {self.mac_address}"
                self._open_event.set()
                return
            self._device = device

            discovered_channel = self._discover_rfcomm_channel(device)
            if discovered_channel is not None and discovered_channel != self.channel_id:
                self.logger.info(f"SDP Query: Overriding RFCOMM channel {self.channel_id} with {discovered_channel}")
                self.channel_id = discovered_channel

            delegate = _Delegate.alloc().init()
            delegate.retain()
            self._delegate = delegate

            rc, channel = device.openRFCOMMChannelAsync_withChannelID_delegate_(
                None, self.channel_id, delegate
            )
            rc = int(rc)
            if rc != 0:
                self._last_error = f"openRFCOMMChannelAsync_ returned {rc}"
                self._open_event.set()
                return
            self._channel = channel
        except Exception as e:
            self._last_error = f"exception in _open_blocking: {e!r}"
            self._open_event.set()

    def _on_data(self, chunk: bytes) -> None:
        self._rx_buf.extend(chunk)
        while (
            len(self._rx_buf) >= models.IOS_LE_MIN_DATA_LENGTH
            and bytes(self._rx_buf[:4]) == bytes(models.IOS_LE_HEADER)
        ):
            length_field = int.from_bytes(self._rx_buf[4:6], "little")
            frame_len = length_field + 7
            # A corrupt length (line noise in bytes 4-5) would otherwise make us
            # wait FOREVER for bytes that never arrive — stalling all RX behind it.
            # Bound it: an impossibly long frame means the "header" is bogus, so
            # resync by dropping one byte (same recovery as a parse failure).
            if frame_len > self._MAX_IOS_LE_FRAME:
                del self._rx_buf[0]
                continue
            if len(self._rx_buf) < frame_len:
                break
            parsed = parse_ios_le_notification(bytes(self._rx_buf[:frame_len]))
            if parsed is None:
                del self._rx_buf[0]
                continue
            raw = bytes(self._rx_buf[:frame_len])
            del self._rx_buf[:frame_len]
            self._rx_queue.put(BtSppNotification(
                command_id=parsed["command_id"], payload=parsed["payload"],
                framing=self.FRAMING_IOS_LE, packet_number=parsed["packet_number"], raw=raw
            ))
        if self._rx_buf and (
            len(self._rx_buf) < 4
            or bytes(self._rx_buf[:4]) != bytes(models.IOS_LE_HEADER)
        ):
            msgs, remaining = parse_basic_protocol_frames(bytearray(self._rx_buf))
            self._rx_buf = bytearray(remaining)
            for m in msgs:
                self._rx_queue.put(BtSppNotification(
                    command_id=m["command_id"], payload=bytes(m["payload"]),
                    framing=self.FRAMING_BASIC, raw=b""
                ))
