# divoom_lib/ble_transport.py

import asyncio
import logging
import time
import os
from typing import Optional, Any
from .divoom import BleakClient
from bleak.exc import BleakError

from . import models, framing
from .ble_notify import BleNotifyMixin
from .transport_interface import DeviceTransport
from .exceptions import (
    DeviceAddressMissingError,
    CharacteristicConfigError,
    DeviceConnectionError,
)

class BLETransport(BleNotifyMixin, DeviceTransport):
    """
    Bluetooth Low Energy (BLE) transport client for Divoom devices.
    Implements the DeviceTransport interface.
    """
    # R53: bound every raw bleak await so a dead/asleep/held device can't hang the
    # connection forever. ensure_connected bounds the FIRST connect, but the
    # internal reconnect path (send_payload → connect) bypasses it — bound here.
    CONNECT_TIMEOUT = 15.0
    NOTIFY_TIMEOUT = 6.0
    STOP_NOTIFY_TIMEOUT = 3.0
    DISCONNECT_TIMEOUT = 5.0
    def __init__(self, cfg: models.DivoomConfig, logger: logging.Logger, divoom: Any = None) -> None:
        self.mac = cfg.mac
        self.device_name = cfg.device_name
        self.logger = logger
        self._divoom = divoom
        
        self.WRITE_CHARACTERISTIC_UUID = cfg.write_characteristic_uuid
        self.NOTIFY_CHARACTERISTIC_UUID = cfg.notify_characteristic_uuid
        self.READ_CHARACTERISTIC_UUID = cfg.read_characteristic_uuid
        self.SPP_CHARACTERISTIC_UUID = cfg.spp_characteristic_uuid if cfg.spp_characteristic_uuid else models.DEFAULT_SPP_CHARACTERISTIC_UUID
        self.escapePayload = cfg.escapePayload
        self.use_ios_le_protocol = cfg.use_ios_le_protocol

        if cfg.client:
            self.client = cfg.client
        elif self.mac:
            from .divoom import BleakClient
            # BLE Hardening P2: subscribe to the OS-level disconnect signal so a
            # drop flips our health state IMMEDIATELY instead of being inferred
            # from the next failed write (macOS CoreBluetooth's is_connected lags).
            self.client = BleakClient(self.mac, disconnected_callback=self._on_os_disconnect)
        else:
            self.client = None

        self.notification_queue = asyncio.Queue()
        self._expected_response_command = None
        # Serializes the shared response path (queue drain + the
        # `_expected_response_command` scalar). Two concurrent waiters would drain
        # each other's frames and clobber the scalar — cross-talk. Today the
        # command queue already serializes device ops, so this is uncontended; the
        # lock makes the invariant explicit so a future off-queue caller can't
        # silently corrupt an in-flight wait. See send_command_and_wait_for_response.
        self._response_lock = asyncio.Lock()
        self.message_buf = bytearray()
        self._write_lock = asyncio.Lock()
        self._last_write_time = 0.0
        # Track whether we've already subscribed to notifications on the
        # current OS-level GATT session. macOS CoreBluetooth raises
        # "Characteristic notifications already started" if start_notify
        # is called twice without a stop_notify in between. After a
        # transient disconnect/reconnect, is_connected may be True but
        # the OS-side subscription state can be inconsistent, so we
        # need an explicit flag to avoid re-subscribing.
        self._notifications_started = False
        # Set to True when a write fails with "disconnected" /
        # "not connected" — even if is_connected() lies and reports
        # True. The retry loop treats this as "force reconnect on
        # the next attempt". macOS CoreBluetooth has a known race
        # where is_connected flips to True before GATT services are
        # fully discovered; the first write in that window returns
        # "disconnected" while the cached state is stale.
        self._connection_likely_broken = False
        # R36b: command ids whose UNSOLICITED inbound frames should be queued
        # even when no response is expected (device-driven protocols — the hot
        # update's 0xF7 file requests / 0x9D / 0x9E acks). Set by HotUpdate
        # for the duration of its session.
        self._listen_commands: set[int] = set()

    @property
    def is_connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    @property
    def is_alive(self) -> bool:
        """BLE Hardening P2: the HONEST liveness — connected per the OS AND no
        pending drop signal (callback or inferred write failure). Live jobs /
        wall consult this before pushing so they self-heal instead of blasting
        into a dead link."""
        return self.is_connected and not self._connection_likely_broken

    def _on_os_disconnect(self, _client) -> None:
        """bleak fires this on the OS event loop when the link drops. Flag the
        link broken so is_alive() reports the truth before the next write."""
        self._connection_likely_broken = True
        self._notifications_started = False
        self.logger.warning("OS-level BLE disconnect for %s", self.mac)

    async def connect(self) -> None:
        if not self.mac:
            self.logger.error("No MAC address provided or discovered. Cannot connect.")
            raise DeviceAddressMissingError("No MAC address provided or discovered. Cannot connect.")

        is_mock = (self.client and "MockBleakClient" in self.client.__class__.__name__) or os.environ.get("DIVOOM_MOCK_BLE") in ("1", "true", "yes")

        # Resolve device name if not set
        if not is_mock and not self.device_name:
            if len(self.mac) == 17 and ("-" in self.mac or ":" in self.mac):
                try:
                    from IOBluetooth import IOBluetoothDevice
                    dev = IOBluetoothDevice.deviceWithAddressString_(self.mac.replace(":", "-"))
                    if dev:
                        self.device_name = dev.getName()
                except Exception:
                    pass
            if not self.device_name:
                try:
                    import json
                    from pathlib import Path
                    cache_file = Path.home() / ".config" / "divoom-control" / "discovered_devices.json"
                    if cache_file.exists():
                        devices = json.loads(cache_file.read_text(encoding="utf-8"))
                        for d in devices:
                            if d.get("address") == self.mac:
                                self.device_name = d.get("name")
                                break
                except Exception as e:
                    self.logger.debug(f"Failed to load device name from cache: {e}")

        if not all([self.WRITE_CHARACTERISTIC_UUID, self.NOTIFY_CHARACTERISTIC_UUID, self.READ_CHARACTERISTIC_UUID]):
            self.logger.error("Characteristic UUIDs not fully set. Cannot connect.")
            raise CharacteristicConfigError("Characteristic UUIDs not fully set. Cannot connect.")

        if self.client and self.client.is_connected:
            self.logger.info(f"Client already connected to {self.mac}. Skipping connection.")
            return

        if not is_mock:
            # One connection per address: evict any other in-process transport
            # holding this MAC first, or CoreBluetooth refuses the second connect
            # (single↔wall switch). See divoom_lib/ble_registry.
            from . import ble_registry
            await ble_registry.evict(self.mac, self)
            if not self.client or getattr(self.client, "address", None) != self.mac:
                from .divoom import BleakClient
                self.client = BleakClient(self.mac, disconnected_callback=self._on_os_disconnect)

        if not self.client.is_connected:
            try:
                # R53: bound the connect so a dead/asleep/held device can't hang
                # the (possibly write-lock-holding) reconnect path forever.
                await asyncio.wait_for(self.client.connect(), timeout=self.CONNECT_TIMEOUT)
                self.logger.info(f"Connected to Divoom device at {self.mac}")
            except asyncio.TimeoutError:
                self.logger.error(f"Connect to {self.mac} timed out after {self.CONNECT_TIMEOUT}s")
                raise DeviceConnectionError(
                    f"Connect to {self.mac} timed out after {self.CONNECT_TIMEOUT}s")
            except Exception as e:
                self.logger.error(f"Failed to connect to {self.mac}: {e}")
                raise DeviceConnectionError(f"Failed to connect to {self.mac}: {e}")
        if not is_mock:
            from . import ble_registry
            ble_registry.register(self.mac, self)

        # A freshly-(re)established OS-level link is NOT broken. Clear any stale
        # drop flag from a prior _on_os_disconnect NOW, so is_alive reports the
        # truth immediately after a reconnect — without waiting for the next
        # successful send to clear it (else the link reads DEGRADED post-reconnect
        # and live jobs treat it as dead → needless rebuild churn).
        self._connection_likely_broken = False

        if self.NOTIFY_CHARACTERISTIC_UUID:
            if self._notifications_started:
                self.logger.info(
                    f"Notifications already enabled for {self.NOTIFY_CHARACTERISTIC_UUID}; "
                    "skipping start_notify (macOS CoreBluetooth 'already started' guard)."
                )
            else:
                cb = self._divoom.notification_handler if (self._divoom and hasattr(self._divoom, "notification_handler")) else self.notification_handler
                # R53: bound start_notify too — a wedged GATT subscribe otherwise
                # hangs connect() (and any write-lock-holding reconnect) forever.
                try:
                    await asyncio.wait_for(
                        self.client.start_notify(self.NOTIFY_CHARACTERISTIC_UUID, cb),
                        timeout=self.NOTIFY_TIMEOUT)
                except asyncio.TimeoutError:
                    raise DeviceConnectionError(
                        f"start_notify timed out after {self.NOTIFY_TIMEOUT}s on {self.mac}")
                self._notifications_started = True
                self.logger.info(f"Enabled notifications for {self.NOTIFY_CHARACTERISTIC_UUID}")
        else:
            self.logger.warning("No notify characteristic UUID set. Cannot enable notifications.")

        await asyncio.sleep(1.0)

        # Dynamic auto-probe of the BLE framing (iOS-LE vs Basic) — see ble_probe.
        from .ble_probe import autoprobe_protocol
        await autoprobe_protocol(self)

    async def disconnect(self) -> None:
        from . import ble_registry
        ble_registry.unregister(self.mac, self)
        if self.client and self.client.is_connected:
            # R53: actually release the OS-side notify subscription before
            # disconnecting (the old comment claimed this happened, but no
            # stop_notify was ever called — leaking the subscription, which made
            # a later start_notify on a fresh client raise "already started").
            if self._notifications_started and self.NOTIFY_CHARACTERISTIC_UUID:
                try:
                    await asyncio.wait_for(
                        self.client.stop_notify(self.NOTIFY_CHARACTERISTIC_UUID),
                        timeout=self.STOP_NOTIFY_TIMEOUT)
                except Exception as e:
                    self.logger.debug("stop_notify on %s failed (continuing): %s", self.mac, e)
            try:
                # R53: bound the disconnect so a wedged teardown can't hang.
                await asyncio.wait_for(self.client.disconnect(), timeout=self.DISCONNECT_TIMEOUT)
                self.logger.info("Disconnected from Divoom device at %s", self.mac)
            except asyncio.TimeoutError:
                self.logger.warning("Disconnect from %s timed out after %.0fs",
                                    self.mac, self.DISCONNECT_TIMEOUT)
            except Exception as e:
                self.logger.error("Error disconnecting from %s: %s", self.mac, e)
        # Reset the notification-subscription flag so a future connect()
        # can re-subscribe cleanly.
        self._notifications_started = False
        # The "connection likely broken" flag was an inference from
        # write failures; a clean disconnect is the source of truth
        # and supersedes it.
        self._connection_likely_broken = False

    # notification_handler / _handle_ios_le_notification /
    # _handle_basic_protocol_notification / wait_for_any_response /
    # wait_for_response / send_command_and_wait_for_response live in BleNotifyMixin.

    async def send_command(self, command: int | str, args: list | None = None, write_with_response: bool = False) -> bool:
        if args is None:
            args = []
        if isinstance(command, str):
            command_name = command
            command = models.COMMANDS[command]
        else:
            command_name = f"0x{command:02x}"

        self.logger.debug(f"Sending command: {command_name} (0x{command:02x}) with args: {args}")
        payload_bytes = [command] + args

        try:
            return await self.send_payload(payload_bytes, write_with_response=write_with_response)
        except Exception as e:
            self.logger.error(f"Error calling send_payload for command {command_name}: {e}")
            return False

    async def send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        async with self._write_lock:
            now = time.time()
            elapsed = now - self._last_write_time
            if elapsed < 0.05:
                await asyncio.sleep(0.05 - elapsed)
            
            try:
                res = await self._send_payload_locked(payload_bytes, max_retries, **kwargs)
                return res
            finally:
                self._last_write_time = time.time()

    async def _send_payload_locked(self, payload_bytes: list, max_retries: int = 3, retry_delay: float = 0.1, write_with_response: bool = False) -> bool:
        for attempt in range(max_retries):
            backoff = retry_delay * (2 ** attempt)
            # Treat the connection as broken if EITHER:
            #   - self.is_connected is False (the OS-level flag is honest)
            #   - self._connection_likely_broken is True (a recent write
            #     failed with "disconnected" even though is_connected
            #     was still True at the time — the cached flag lags)
            likely_broken_triggered = self._connection_likely_broken
            if not self.is_connected or likely_broken_triggered:
                # Capture and clear the inference flag up front so the
                # reconnect itself isn't poisoned by stale state.
                self._connection_likely_broken = False
                self.logger.warning(
                    f"Attempt {attempt + 1}: Not connected to a Divoom device "
                    f"(is_connected={self.is_connected}, likely_broken={likely_broken_triggered}). "
                    f"Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                # Reconnect if EITHER:
                #   - is_connected is False (we're definitely not connected)
                #   - likely_broken_triggered is True (the OS lied; force
                #     a fresh connect to clear the stale GATT state)
                need_reconnect = (not self.is_connected) or likely_broken_triggered
                if need_reconnect:
                    try:
                        if self._divoom:
                            await self._divoom.connect()
                        else:
                            await self.connect()
                        self.logger.info(f"Attempt {attempt + 1}: Reconnected to Divoom device")
                    except Exception as e:
                        self.logger.error(f"Attempt {attempt + 1}: Failed to reconnect: {e}")
                        if attempt == max_retries - 1:
                            self.logger.error("Max retries reached. Giving up.")
                            return False
                        continue

            if self.use_ios_le_protocol:
                send_func = self._divoom._send_ios_le_payload if (self._divoom and hasattr(self._divoom, "_send_ios_le_payload")) else self._send_ios_le_payload
                if await send_func(payload_bytes, write_with_response):
                    self._connection_likely_broken = False  # success — clear
                    return True
                elif attempt == max_retries - 1:
                    return False
                await asyncio.sleep(backoff)
            else:
                send_func = self._divoom._send_basic_protocol_payload if (self._divoom and hasattr(self._divoom, "_send_basic_protocol_payload")) else self._send_basic_protocol_payload
                if await send_func(payload_bytes, write_with_response):
                    self._connection_likely_broken = False  # success — clear
                    return True
                elif attempt == max_retries - 1:
                    return False
                await asyncio.sleep(backoff)
        return False

    def _flag_connection_broken(self, exception: Exception) -> None:
        """If a write exception indicates a connection drop, flag it.

        macOS CoreBluetooth's BleakClient has a known race: the
        `is_connected` property can return True (cached) while
        `write_gatt_char` raises "disconnected" or "not connected"
        because the GATT services haven't finished discovering yet.
        This method inspects the exception and sets
        `_connection_likely_broken` so the next attempt in
        `_send_payload_locked` will force a full reconnect.
        """
        err_str = str(exception).lower()
        if "disconnected" in err_str or "not connected" in err_str or "not connected to" in err_str:
            self._connection_likely_broken = True

    async def _send_ios_le_payload(self, payload_bytes: list, write_with_response: bool) -> bool:
        message_bytes = framing.encode_ios_le_payload(payload_bytes)
        try:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug("PAYLOAD OUT (iOS LE): %s", message_bytes.hex())
            await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, message_bytes, response=write_with_response)
            return True
        except Exception as e:
            self.logger.error(f"Error sending iOS LE payload: {e}")
            self._flag_connection_broken(e)
            return False

    async def _send_basic_protocol_payload(self, payload_bytes: list, write_with_response: bool) -> bool:
        full_message = framing.encode_basic_payload(payload_bytes, escape=self.escapePayload)
        chunk_size = models.DEFAULT_CHUNK_SIZE

        if len(full_message) > chunk_size:
            self.logger.debug(f"Message too long ({len(full_message)} bytes), splitting into chunks of {chunk_size} bytes.")
            chunks = [full_message[i:i + chunk_size] for i in range(0, len(full_message), chunk_size)]

            success = True
            for i, chunk in enumerate(chunks):
                try:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("PAYLOAD OUT (Chunk %d/%d): %s", i + 1, len(chunks), chunk.hex())
                    chunk_response = write_with_response and (i == len(chunks) - 1)
                    await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, chunk, response=chunk_response)
                    await asyncio.sleep(0.05)
                except Exception as e:
                    self.logger.error(f"Error sending chunk {i+1}: {e}")
                    self._flag_connection_broken(e)
                    success = False
                    break
            return success
        else:
            try:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug("PAYLOAD OUT: %s (char %s)", full_message.hex(), self.WRITE_CHARACTERISTIC_UUID)
                await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, full_message, response=write_with_response)
                return True
            except Exception as e:
                self.logger.error(f"Error sending payload: {e}")
                self._flag_connection_broken(e)
                return False
