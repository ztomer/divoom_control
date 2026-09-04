# divoom_lib/bt_spp_transport.py

from __future__ import annotations
import asyncio
import logging
import queue
import threading
from typing import Optional, Any

from . import models, framing
from .transport_interface import DeviceTransport
from .framing import encode_basic_payload, encode_ios_le_payload
# BtSppNotification + the IOBluetooth RFCOMM backend live in bt_spp_rfcomm (R53.12);
# re-export BtSppNotification so existing `from .bt_spp_transport import ...` keeps working.
from .bt_spp_rfcomm import _SppRfcommMixin, BtSppNotification

DEFAULT_RFCOMM_CHANNEL_IDS: dict[str, int] = {
    "pixoo": 1,
    "timoo": 2,
    "ditoo": 2,
    "tivoo": 2,
    "tivoo_max": 2,
    "default": 2,
}

class BtSppTransportError(RuntimeError):
    pass

class BTSppTransport(_SppRfcommMixin, DeviceTransport):
    """
    Async wrapper around macOS IOBluetooth RFCOMM SPP for Divoom devices.
    Implements the DeviceTransport interface.
    """
    OPEN_TIMEOUT_S: float = 8.0
    DEFAULT_READ_TIMEOUT_S: float = 3.0
    FRAMING_BASIC: str = "basic"
    FRAMING_IOS_LE: str = "ios_le"

    def __init__(
        self,
        mac_address: str,
        channel_id: int | None = None,
        device_kind: str = "default",
        logger: logging.Logger | None = None,
        device_name: str | None = None,
    ) -> None:
        self.mac_address = mac_address
        self.device_name = device_name
        self.channel_id = (
            channel_id
            if channel_id is not None
            else DEFAULT_RFCOMM_CHANNEL_IDS.get(device_kind, 2)
        )
        self.logger = logger or logging.getLogger("divoom.bt_spp")

        self._device = None
        self._channel = None
        self._delegate = None
        self._runloop_thread: Optional[threading.Thread] = None
        self._runloop = None
        self._open_event = threading.Event()
        self._close_event = threading.Event()
        self._rx_queue: queue.Queue[BtSppNotification] = queue.Queue()
        self._rx_buf = bytearray()
        self._write_lock = threading.Lock()
        self._last_error: Optional[str] = None

        self._serial_port = None
        self._serial_read_thread: Optional[threading.Thread] = None
        
        # DeviceTransport interface compliance
        self.notification_queue = asyncio.Queue()
        self._rx_task: Optional[asyncio.Task] = None
        self._expected_response_command = None

    @property
    def is_connected(self) -> bool:
        if self._serial_port is not None:
            return self._serial_port.is_open and not self._close_event.is_set()
        return self._channel is not None and not self._close_event.is_set()

    @property
    def is_alive(self) -> bool:
        """Honest liveness (parity with BLE's is_alive). `is_connected` lags True
        after the serial read thread dies silently — the port stays `.is_open`
        though no data will ever arrive again. On the serial path, also require the
        reader thread to be alive; on the IOBluetooth path the channel (closed via
        the rfcommChannelClosed_ delegate → _close_event) is the signal."""
        if not self.is_connected:
            return False
        t = self._serial_read_thread
        if self._serial_port is not None and t is not None:
            return t.is_alive()
        return True

    @property
    def mtu(self) -> int:
        if self._serial_port is not None:
            return 200
        return int(self._channel.getMTU()) if self._channel else 0

    def _find_serial_port(self) -> str | None:
        if not self.device_name:
            return None
        import glob
        ports = glob.glob("/dev/cu.*")
        sanitized_target = self.device_name.lower().replace("-", "").replace(" ", "").replace("_", "")
        for p in ports:
            sanitized_p = p.lower().replace("-", "").replace(" ", "").replace("_", "")
            if sanitized_target in sanitized_p or sanitized_p in sanitized_target:
                return p
        
        parts = self.device_name.split("-")
        prefix = parts[0].strip()
        if len(prefix) >= 3:
            for p in ports:
                if prefix.lower() in p.lower():
                    return p
        return None

    def _serial_read_loop(self) -> None:
        # On exit (port closed OR read error) the thread dies; is_alive then reports
        # False even while is_connected still lags True (the port stays .is_open).
        while not self._close_event.is_set():
            port = self._serial_port
            if not port or not port.is_open:
                break
            try:
                chunk = port.read(32)
                if chunk:
                    self._on_data(chunk)
            except Exception as e:
                # Was swallowed silently — log so a dead reader is diagnosable.
                self.logger.warning("SPP serial read loop exiting on error: %s", e)
                break

    async def connect(self) -> None:
        if self.is_connected:
            self.logger.debug("BTSppTransport already connected")
            return

        self._close_event.clear()
        self._rx_queue = queue.Queue()
        self._rx_buf = bytearray()
        while not self.notification_queue.empty():
            self.notification_queue.get_nowait()

        import sys
        if sys.platform == "darwin":
            try:
                import serial
                port = self._find_serial_port()
                if port:
                    self.logger.info(f"macOS: Found virtual serial port: {port}. Connecting...")
                    self._serial_port = serial.Serial(port, 115200, timeout=1.0)
                    self.logger.info("macOS: Connected. Stabilizing serial link...")
                    await asyncio.sleep(2.0)
                    
                    self._serial_read_thread = threading.Thread(
                        target=self._serial_read_loop, name="bt-spp-serial-read", daemon=True
                    )
                    self._serial_read_thread.start()
                    self.logger.info(f"macOS: Serial transport connected successfully on {port}!")
                    self._rx_task = asyncio.create_task(self._rx_loop())
                    return
            except Exception as e:
                self.logger.warning(f"macOS: Serial connection failed: {e}. Trying IOBluetooth...")
                if self._serial_port:
                    try:
                        self._serial_port.close()   # makes the read loop exit
                    except Exception:
                        pass
                    self._serial_port = None
                self._serial_read_thread = None   # R53: closing the port exits it

        # R53: tear everything down on ANY failure here, so a failed IOBluetooth
        # open doesn't leak the runloop thread (only disconnect() sets _close_event).
        try:
            self._start_runloop()
            await asyncio.to_thread(self._open_blocking)
            # R53.2: the RFCOMM-open completion is a threading.Event set from the
            # IOBluetooth delegate thread — wait off-loop so it can't freeze the
            # whole asyncio loop for up to OPEN_TIMEOUT_S on every connect.
            opened = await asyncio.to_thread(self._open_event.wait, self.OPEN_TIMEOUT_S)
            if not opened:
                raise BtSppTransportError(
                    f"RFCOMM open to {self.mac_address} channel {self.channel_id} timed out. "
                    "Known macOS Tahoe SPP reconnection bug."
                )
            if self._last_error:
                raise BtSppTransportError(f"RFCOMM open failed: {self._last_error}")

            self.logger.info(f"BT Classic SPP open: {self.mac_address} channel {self.channel_id}")
            self._rx_task = asyncio.create_task(self._rx_loop())
        except BaseException:
            await self.disconnect()   # stop the runloop thread + close the channel
            raise

    async def disconnect(self) -> None:
        self._close_event.set()
        if self._rx_task:
            self._rx_task.cancel()
            try:
                await self._rx_task
            except asyncio.CancelledError:
                pass
            self._rx_task = None

        if self._serial_port:
            try:
                self._serial_port.close()
            except Exception:
                pass
            self._serial_port = None
        if self._serial_read_thread is not None:
            await asyncio.to_thread(self._serial_read_thread.join, 2.0)
            self._serial_read_thread = None

        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
            self._channel = None
        if self._runloop_thread is not None:
            await asyncio.to_thread(self._runloop_thread.join, 2.0)
            self._runloop_thread = None
            
        self._device = None
        self._delegate = None
        self._runloop = None
        self._open_event.clear()

    async def send(
        self,
        payload: list[int],
        framing: str = FRAMING_BASIC,
        packet_number: int = 0,
    ) -> None:
        if not self.is_connected:
            raise BtSppTransportError("not connected; call connect() first")
        
        if framing == self.FRAMING_BASIC:
            frame = encode_basic_payload(payload)
        elif framing == self.FRAMING_IOS_LE:
            frame = encode_ios_le_payload(payload, packet_number=packet_number)
        else:
            raise ValueError(f"unknown framing: {framing!r}")

        if self._serial_port and self._serial_port.is_open:
            def _do_serial_write():
                with self._write_lock:
                    if self._serial_port is None:
                        raise BtSppTransportError("serial port closed during write")
                    self._serial_port.write(frame)
                    self._serial_port.flush()

            await asyncio.to_thread(_do_serial_write)
            self.logger.debug(f"[BT-SPP-Serial ] sent ({framing}): {frame.hex()}")
            return

        def _do_write():
            with self._write_lock:
                if self._channel is None:
                    raise BtSppTransportError("channel closed during write")
                rc = self._channel.writeSync_length_(frame, len(frame))
                if rc != 0:
                    raise BtSppTransportError(f"writeSync_length_ returned {rc}")

        await asyncio.to_thread(_do_write)
        self.logger.debug(f"[BT-SPP ] sent ({framing}): {frame.hex()}")

    async def read_notification(
        self, timeout: float = DEFAULT_READ_TIMEOUT_S
    ) -> BtSppNotification:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._rx_queue.get, True, timeout),
                timeout=timeout + 0.5,
            )
        except queue.Empty:
            raise asyncio.TimeoutError(f"no notification within {timeout}s on {self.mac_address}")

    async def _rx_loop(self) -> None:
        while self.is_connected:
            try:
                notif = await self.read_notification(timeout=1.0)
                response_payload = {
                    'command_id': notif.command_id,
                    'payload': bytearray(notif.payload)
                }
                self.notification_queue.put_nowait(response_payload)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in SPP notification loop: {e}")
                break

    # DeviceTransport methods mapping
    async def send_command(self, command: int | str, args: list | None = None, write_with_response: bool = False) -> bool:
        if args is None:
            args = []
        if isinstance(command, str):
            command = models.COMMANDS[command]
        payload_bytes = [command] + args
        return await self.send_payload(payload_bytes)

    async def send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        # max_retries was accepted but ignored — a single transient write failure
        # (busy channel, momentary EAGAIN) failed the whole op. Retry with a short
        # backoff; bail early once disconnected (no point retrying a dead link).
        attempts = max(1, int(max_retries))
        for attempt in range(1, attempts + 1):
            try:
                await self.send(payload_bytes, framing=self.FRAMING_BASIC)
                return True
            except Exception as e:
                if attempt >= attempts or not self.is_connected:
                    self.logger.error(
                        "SPP send_payload failed after %d attempt(s): %s", attempt, e)
                    return False
                self.logger.warning(
                    "SPP send_payload attempt %d/%d failed: %s; retrying",
                    attempt, attempts, e)
                await asyncio.sleep(0.1 * attempt)
        return False

    async def send_command_and_wait_for_response(self, command: int | str, args: list | None = None, timeout: float = 10.0) -> bytes | None:
        command_id = models.COMMANDS.get(command, command) if isinstance(command, str) else command
        while not self.notification_queue.empty():
            self.notification_queue.get_nowait()
        self._expected_response_command = command_id
        if await self.send_command(command, args):
            return await self.wait_for_response(command_id, timeout)
        return None

    async def wait_for_response(self, command_id: int, timeout: float = 10.0) -> Optional[bytes]:
        self.logger.debug(f"Waiting for SPP response to command ID 0x{command_id:02x} for {timeout}s...")
        loop = asyncio.get_running_loop()
        end_time = loop.time() + timeout
        while True:
            remaining = end_time - loop.time()
            if remaining <= 0:
                break
            try:
                response = await asyncio.wait_for(self.notification_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            response_cmd_id = response.get('command_id')
            is_expected_response = response_cmd_id == command_id
            is_generic_ack = response_cmd_id == models.GENERIC_ACK_COMMAND_ID and command_id in models.GENERIC_ACK_COMMANDS

            if is_expected_response:
                self.logger.debug(f"Got matching response for command ID 0x{command_id:02x}")
                self._expected_response_command = None
                return response.get('payload')
            elif is_generic_ack:
                self.logger.debug(f"Received generic ACK for command 0x{command_id:02x}. Continuing to wait.")
        return None

    # _start_runloop / _runloop_main / _discover_rfcomm_channel / _open_blocking /
    # _on_data (the IOBluetooth RFCOMM backend + shared RX framer) live in
    # _SppRfcommMixin (bt_spp_rfcomm.py).

    async def __aenter__(self) -> BTSppTransport:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()
