# divoom_lib/connection.py

import asyncio
import logging
import os
from typing import Optional, Any

from . import models
from .transport_interface import DeviceTransport
from .ble_transport import BLETransport
from . import bt_spp_transport

class DivoomConnection(DeviceTransport):
    """
    Acts as a transport router implementing the DeviceTransport interface.
    Instantiates and delegates to either BLETransport or BTSppTransport
    based on the device properties and automatic discovery.
    """
    def __init__(self, divoom: Any, cfg: models.DivoomConfig):
        self._divoom = divoom
        self.cfg = cfg
        self.logger = divoom.logger
        self._use_spp = False
        # R53.34: the router (this class) is the single entry point for
        # send_command_and_wait_for_response on the live path — it shadows the
        # transport's own lock-protected version, so the R53.11 cross-talk lock
        # was effectively bypassed. Serialize the drain→set-scalar→send→wait
        # sequence here too, so two concurrent waiters on one device can't drain
        # each other's frames or clobber _expected_response_command.
        self._response_lock = asyncio.Lock()

        # Instantiate BLETransport as the initial default
        self._active_transport = BLETransport(cfg, self.logger, divoom=self._divoom)

    @property
    def is_connected(self) -> bool:
        return self._active_transport.is_connected

    @property
    def is_alive(self) -> bool:
        """BLE Hardening P2: honest liveness (OS-connected AND no pending drop).
        Falls back to is_connected on transports that don't track it (LAN/SPP)."""
        return getattr(self._active_transport, "is_alive", self._active_transport.is_connected)

    @property
    def use_spp(self) -> bool:
        return self._use_spp

    async def connect(self) -> None:
        mac = self.mac
        device_name = self.device_name
        is_mock = (self.client and "MockBleakClient" in self.client.__class__.__name__) or os.environ.get("DIVOOM_MOCK_BLE") in ("1", "true", "yes")

        # 1. Resolve device name dynamically if not set
        if not is_mock and not device_name and mac:
            if len(mac) == 17 and ("-" in mac or ":" in mac):
                try:
                    from IOBluetooth import IOBluetoothDevice
                    dev = IOBluetoothDevice.deviceWithAddressString_(mac.replace(":", "-"))
                    if dev:
                        device_name = dev.getName()
                        self.device_name = device_name
                except Exception:
                    pass
            if not device_name:
                try:
                    import json
                    from pathlib import Path
                    cache_file = Path.home() / ".config" / "divoom-control" / "discovered_devices.json"
                    if cache_file.exists():
                        devices = json.loads(cache_file.read_text(encoding="utf-8"))
                        for d in devices:
                            if d.get("address") == mac:
                                device_name = d.get("name")
                                self.device_name = device_name
                                break
                except Exception as e:
                    self.logger.debug(f"Failed to load device name from cache: {e}")

        # 2. Check if device kind suggests Bluetooth Classic SPP transport
        use_spp = False
        # Only route to SPP when protocol is explicitly set to Basic (False).
        # When use_ios_le_protocol is None (unknown/unprobed), the autoprobe in
        # BLETransport.connect() determines it dynamically — don't pre-empt it
        # with an SPP redirect for a device that may be BLE-only.
        if not is_mock and device_name and self.use_ios_le_protocol is False:
            name_lower = device_name.lower()
            if any(kw in name_lower for kw in ["timoo", "tivoo", "ditoo", "pixoo", "timebox", "divoom"]):
                if "pixoo 64" not in name_lower and "pixoo-64" not in name_lower:
                    use_spp = True

        # 3. Instantiate and switch transport if needed
        if use_spp:
            # NB: qualify via the imported module — bare `BTSppTransport` is NOT bound
            # in this module, so on an SPP *reconnect* (_use_spp already True, so the
            # `not self._use_spp` short-circuit no longer saves us) the isinstance()
            # raised NameError and crashed every second connect to an SPP device.
            if not self._use_spp or not isinstance(self._active_transport, bt_spp_transport.BTSppTransport):
                from . import spp_connection
                classic_mac = spp_connection.resolve_classic_mac(device_name, mac, log=self.logger)
                if classic_mac:
                    name_lower = device_name.lower()
                    device_kind = "default"
                    if "pixoo" in name_lower:
                        device_kind = "pixoo"
                    elif "timoo" in name_lower:
                        device_kind = "timoo"
                    elif "ditoo" in name_lower:
                        device_kind = "ditoo"
                    elif "tivoo" in name_lower:
                        device_kind = "tivoo"
                    
                    self.logger.info(f"Switching transport to BTSppTransport for {device_name}...")
                    await self._teardown_outgoing_transport()
                    self._active_transport = bt_spp_transport.BTSppTransport(
                        mac_address=classic_mac,
                        device_kind=device_kind,
                        logger=self.logger,
                        device_name=device_name
                    )
                    self._use_spp = True
                else:
                    self.logger.warning(f"Could not resolve Bluetooth Classic MAC for {device_name}. Falling back to BLE.")
                    use_spp = False

        if not use_spp:
            if self._use_spp or not isinstance(self._active_transport, BLETransport):
                self.logger.info("Switching transport to BLETransport...")
                await self._teardown_outgoing_transport()
                self._active_transport = BLETransport(self.cfg, self.logger, divoom=self._divoom)
                self._use_spp = False

        await self._active_transport.connect()

    async def _teardown_outgoing_transport(self) -> None:
        """R53: cleanly disconnect (and unregister) the outgoing transport BEFORE
        a transport-type swap. Without this the old transport leaks in the BLE
        registry and — on a BLE→SPP switch — keeps the CoreBluetooth link open
        while the new transport tries to reach the same device, causing the
        contention the registry exists to prevent. Only fires on a genuine type
        change (a same-type reconnect reuses the transport, so this is a no-op)."""
        old = getattr(self, "_active_transport", None)
        if old is None:
            return
        try:
            await old.disconnect()
        except Exception as e:
            self.logger.debug("outgoing transport teardown failed (continuing): %s", e)

    async def disconnect(self) -> None:
        await self._active_transport.disconnect()

    def notification_handler(self, sender: int, data: bytearray) -> None:
        if hasattr(self._active_transport, "notification_handler"):
            self._active_transport.notification_handler(sender, data)

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
            return await self._divoom._send_payload(payload_bytes, write_with_response=write_with_response)
        except Exception as e:
            self.logger.error(f"Error calling send_payload for command {command_name}: {e}")
            return False

    async def send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        return await self._active_transport.send_payload(payload_bytes, max_retries, **kwargs)

    async def send_command_and_wait_for_response(self, command: int | str, args: list | None = None, timeout: float = 10.0) -> bytes | None:
        command_id = models.COMMANDS.get(command, command) if isinstance(command, str) else command
        if self._response_lock.locked():
            self.logger.warning(
                "send_command_and_wait_for_response(0x%02x) contended — another "
                "response wait is in flight; serializing to avoid cross-talk",
                command_id if isinstance(command_id, int) else 0)
        # Hold the lock across drain→set-scalar→send→wait. We keep delegating the
        # actual send/wait to self._divoom (the HW-tuned path) rather than the
        # transport's send_command_and_wait_for_response, so routing is unchanged.
        async with self._response_lock:
            while not self.notification_queue.empty():
                self.notification_queue.get_nowait()
            self._expected_response_command = command_id
            await self._divoom.send_command(command, args, write_with_response=True)
            return await self._divoom._wait_for_response(command_id, timeout)

    async def wait_for_response(self, command_id: int, timeout: float = 10.0) -> Optional[bytes]:
        return await self._active_transport.wait_for_response(command_id, timeout)

    async def wait_for_any_response(self, command_ids: list, timeout: float = 10.0):
        """R36b: multi-command wait for device-driven protocols (hot update).
        Only transports that implement it participate; returns None elsewhere."""
        wait = getattr(self._active_transport, "wait_for_any_response", None)
        if wait is None:
            return None
        return await wait(command_ids, timeout)

    @property
    def _listen_commands(self):
        """R36b: the active transport's unsolicited-frame listen set (or None)."""
        return getattr(self._active_transport, "_listen_commands", None)

    @property
    def _spp_client(self) -> Any:
        return self._active_transport if self._use_spp else None

    @_spp_client.setter
    def _spp_client(self, val: Any) -> None:
        if val is not None:
            self._active_transport = val
            self._use_spp = True

    @property
    def mac(self) -> str | None:
        if self._use_spp:
            return self._active_transport.mac_address
        return self._active_transport.mac

    @mac.setter
    def mac(self, val: str | None) -> None:
        self.cfg.mac = val
        if self._use_spp:
            self._active_transport.mac_address = val
        else:
            self._active_transport.mac = val

    @property
    def device_name(self) -> str | None:
        return self._active_transport.device_name

    @device_name.setter
    def device_name(self, val: str | None) -> None:
        self.cfg.device_name = val
        self._active_transport.device_name = val

    @property
    def WRITE_CHARACTERISTIC_UUID(self) -> str:
        return getattr(self._active_transport, "WRITE_CHARACTERISTIC_UUID", "")

    @WRITE_CHARACTERISTIC_UUID.setter
    def WRITE_CHARACTERISTIC_UUID(self, val: str) -> None:
        self.cfg.write_characteristic_uuid = val
        if hasattr(self._active_transport, "WRITE_CHARACTERISTIC_UUID"):
            self._active_transport.WRITE_CHARACTERISTIC_UUID = val

    @property
    def NOTIFY_CHARACTERISTIC_UUID(self) -> str:
        return getattr(self._active_transport, "NOTIFY_CHARACTERISTIC_UUID", "")

    @NOTIFY_CHARACTERISTIC_UUID.setter
    def NOTIFY_CHARACTERISTIC_UUID(self, val: str) -> None:
        self.cfg.notify_characteristic_uuid = val
        if hasattr(self._active_transport, "NOTIFY_CHARACTERISTIC_UUID"):
            self._active_transport.NOTIFY_CHARACTERISTIC_UUID = val

    @property
    def READ_CHARACTERISTIC_UUID(self) -> str:
        return getattr(self._active_transport, "READ_CHARACTERISTIC_UUID", "")

    @READ_CHARACTERISTIC_UUID.setter
    def READ_CHARACTERISTIC_UUID(self, val: str) -> None:
        self.cfg.read_characteristic_uuid = val
        if hasattr(self._active_transport, "READ_CHARACTERISTIC_UUID"):
            self._active_transport.READ_CHARACTERISTIC_UUID = val

    @property
    def SPP_CHARACTERISTIC_UUID(self) -> str:
        return getattr(self._active_transport, "SPP_CHARACTERISTIC_UUID", "")

    @SPP_CHARACTERISTIC_UUID.setter
    def SPP_CHARACTERISTIC_UUID(self, val: str) -> None:
        self.cfg.spp_characteristic_uuid = val
        if hasattr(self._active_transport, "SPP_CHARACTERISTIC_UUID"):
            self._active_transport.SPP_CHARACTERISTIC_UUID = val

    @property
    def escapePayload(self) -> bool:
        return getattr(self._active_transport, "escapePayload", True)

    @escapePayload.setter
    def escapePayload(self, val: bool) -> None:
        self.cfg.escapePayload = val
        if hasattr(self._active_transport, "escapePayload"):
            self._active_transport.escapePayload = val

    @property
    def use_ios_le_protocol(self) -> bool:
        return getattr(self._active_transport, "use_ios_le_protocol", False)

    @use_ios_le_protocol.setter
    def use_ios_le_protocol(self, val: bool) -> None:
        self.cfg.use_ios_le_protocol = val
        if hasattr(self._active_transport, "use_ios_le_protocol"):
            self._active_transport.use_ios_le_protocol = val

    @property
    def client(self) -> Any:
        return getattr(self._active_transport, "client", None)

    @client.setter
    def client(self, val: Any) -> None:
        self.cfg.client = val
        if hasattr(self._active_transport, "client"):
            self._active_transport.client = val

    @property
    def notification_queue(self) -> asyncio.Queue:
        return self._active_transport.notification_queue

    @notification_queue.setter
    def notification_queue(self, val: asyncio.Queue) -> None:
        self._active_transport.notification_queue = val

    @property
    def message_buf(self) -> bytearray:
        return getattr(self._active_transport, "message_buf", bytearray())

    @message_buf.setter
    def message_buf(self, val: bytearray) -> None:
        if hasattr(self._active_transport, "message_buf"):
            self._active_transport.message_buf = val

    @property
    def _expected_response_command(self) -> Any:
        return getattr(self._active_transport, "_expected_response_command", None)

    @_expected_response_command.setter
    def _expected_response_command(self, val: Any) -> None:
        if hasattr(self._active_transport, "_expected_response_command"):
            self._active_transport._expected_response_command = val

    # ── Diagnostic / Probing API Forwards ─────────────────────────────────────

    async def probe_write_characteristics_and_try_channel_switch(self, write_chars: list, notify_chars: list, read_chars: list, cached_data: dict, cache_dir: str, device_id: str, colors: list = None, cache_mod: Any = None):
        if hasattr(self._active_transport, "probe_write_characteristics_and_try_channel_switch"):
            return await self._active_transport.probe_write_characteristics_and_try_channel_switch(write_chars, notify_chars, read_chars, cached_data, cache_dir, device_id, colors, cache_mod)
        from . import probing
        return await probing.probe_write_characteristics_and_try_channel_switch(self, write_chars, notify_chars, read_chars, cached_data, cache_dir, device_id, colors, cache_mod)

    async def set_canonical_light(self, cache_dir: str, device_id: str, cache_mod: Any = None, rgb: list = None):
        if hasattr(self._active_transport, "set_canonical_light"):
            return await self._active_transport.set_canonical_light(cache_dir, device_id, cache_mod, rgb)
        from . import probing
        return await probing.set_canonical_light(self, cache_dir, device_id, cache_mod, rgb)

    async def _try_send_command_with_framing(self, command_id: int, payload: list, timeout: float = 3.0, use_ios: bool = False, escape: bool = False):
        if hasattr(self._active_transport, "_try_send_command_with_framing"):
            return await self._active_transport._try_send_command_with_framing(command_id, payload, timeout, use_ios, escape)
        from . import probing
        return await probing._try_send_command_with_framing(self, command_id, payload, timeout=timeout, use_ios=use_ios, escape=escape)

    async def _send_diagnostic_payload(self, write_uuid: str, args_payload: list, cache_data: dict, cache_dir: str, device_id: str, cache_mod: Any = None):
        if hasattr(self._active_transport, "_send_diagnostic_payload"):
            return await self._active_transport._send_diagnostic_payload(write_uuid, args_payload, cache_data, cache_dir, device_id, cache_mod)
        from . import probing
        return await probing._send_diagnostic_payload(self, write_uuid, args_payload, cache_data, cache_dir, device_id, cache_mod)

    async def _handle_cached_payload(self, write_uuid: str, cached_data: dict, cache_dir: str, device_id: str, cache_mod: Any = None):
        if hasattr(self._active_transport, "_handle_cached_payload"):
            return await self._active_transport._handle_cached_payload(write_uuid, cached_data, cache_dir, device_id, cache_mod)
        from . import probing
        return await probing._handle_cached_payload(self, write_uuid, cached_data, cache_dir, device_id, cache_mod)

    # ── Lower-level compatibility hooks ───────────────────────────────────────

    def _handle_ios_le_notification(self, data: bytes) -> bool:
        if hasattr(self._active_transport, "_handle_ios_le_notification"):
            return self._active_transport._handle_ios_le_notification(data)
        return False

    def _handle_basic_protocol_notification(self, new_data: bytearray) -> bool:
        if hasattr(self._active_transport, "_handle_basic_protocol_notification"):
            return self._active_transport._handle_basic_protocol_notification(new_data)
        return False

    async def _send_basic_protocol_payload(self, payload_bytes: list, write_with_response: bool) -> bool:
        if self._use_spp:
            try:
                await self._active_transport.send(payload_bytes, framing=self._active_transport.FRAMING_BASIC)
                return True
            except Exception as e:
                self.logger.error(f"Error sending Basic SPP payload: {e}")
                return False
        if hasattr(self._active_transport, "_send_basic_protocol_payload"):
            return await self._active_transport._send_basic_protocol_payload(payload_bytes, write_with_response)
        return await self.send_payload(payload_bytes, write_with_response=write_with_response)

    async def _send_ios_le_payload(self, payload_bytes: list, write_with_response: bool) -> bool:
        if self._use_spp:
            try:
                await self._active_transport.send(payload_bytes, framing=self._active_transport.FRAMING_IOS_LE)
                return True
            except Exception as e:
                self.logger.error(f"Error sending iOS LE SPP payload: {e}")
                return False
        if hasattr(self._active_transport, "_send_ios_le_payload"):
            return await self._active_transport._send_ios_le_payload(payload_bytes, write_with_response)
        return await self.send_payload(payload_bytes, write_with_response=write_with_response)

    async def _send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        if self._use_spp:
            return await self._send_basic_protocol_payload(payload_bytes, write_with_response=kwargs.get("write_with_response", False))
        return await self._active_transport.send_payload(payload_bytes, max_retries, **kwargs)

    async def _wait_for_response(self, command_id: int, timeout: float = 10.0) -> bytes | None:
        if hasattr(self._active_transport, "_wait_for_response"):
            return await self._active_transport._wait_for_response(command_id, timeout)
        return await self.wait_for_response(command_id, timeout)
