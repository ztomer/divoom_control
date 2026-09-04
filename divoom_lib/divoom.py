# divoom_lib/divoom.py

import logging
from contextlib import asynccontextmanager
from typing import Optional, Any
from bleak import BleakClient

from .transport import Transport, COMMAND_TRANSPORT_MAP


from . import models
from .connection import DivoomConnection
from .models.capabilities import capabilities_for
from .display.light import Light
from .display.animation import Animation
from .display.drawing import Drawing
from .display.text import Text
from .system.device import Device
from .system.time import Time
from .system.bluetooth import Bluetooth
from .media.music import Music
from .media.radio import Radio
from .scheduling.alarm import Alarm
from .scheduling.sleep import Sleep
from .scheduling.timeplan import Timeplan
from .tools.scoreboard import Scoreboard
from .tools.timer import Timer
from .tools.countdown import Countdown
from .tools.noise import Noise
from .tools.notification import Notification
from .tools.hot_update import HotUpdate
from .tools.aid_sleep import AidSleep
from .display import Display
from .display.design import Design
from .system import System
from .system.sound import SoundControl
from .system.control import Control
from .system.weather import Weather
from .tool import Tool
from .game import Game

class Divoom:
    """
    A class to interact with a Divoom device over Bluetooth Low Energy (BLE).
    Acts as the high-level facade orchestrator, registering submodules and
    delegating BLE transport tasks to DivoomConnection.
    """
    def __init__(self, config: Optional[models.DivoomConfig] = None, mac: Optional[str] = None, logger: Optional[object] = None, **kwargs) -> None:
        if config is not None and isinstance(config, models.DivoomConfig):
            cfg = config
        else:
            mac_addr = mac
            if mac_addr is None and isinstance(config, str):
                mac_addr = config
            
            cfg = models.DivoomConfig(
                mac=mac_addr,
                logger=logger or kwargs.get('logger'),
                write_characteristic_uuid=kwargs.get('write_characteristic_uuid', "49535343-8841-43f4-a8d4-ecbe34729bb3"),
                notify_characteristic_uuid=kwargs.get('notify_characteristic_uuid', "49535343-1e4d-4bd9-ba61-23c647249616"),
                read_characteristic_uuid=kwargs.get('read_characteristic_uuid', "49535343-1e4d-4bd9-ba61-23c647249616"),
                spp_characteristic_uuid=kwargs.get('spp_characteristic_uuid'),
                escapePayload=kwargs.get('escapePayload', False),
                use_ios_le_protocol=kwargs.get('use_ios_le_protocol', None),
                device_name=kwargs.get('device_name'),
                client=kwargs.get('client'),
                screensize=kwargs.get('screensize'),
                device_type=kwargs.get('device_type'),
            )

        # Optional LAN transport (WiFi-capable devices only)
        lan_ip = kwargs.get('lan_ip') or (cfg.lan_ip if hasattr(cfg, 'lan_ip') else None)
        lan_token = kwargs.get('lan_token', 0)
        self._lan = None
        if lan_ip:
            from .lan_transport import LanTransport
            self._lan = LanTransport(device_ip=lan_ip, local_token=lan_token)

        self._mac = cfg.mac
        self._device_name = cfg.device_name
        self._device_type = kwargs.get('device_type')  # R13 §1 — explicit override; else registry/manufacturer_data
        self._advertisement_data = kwargs.get('advertisement_data')  # bleak AdvertisementData or None

        if cfg.logger is None:
            log = logging.getLogger(self.mac or "divoom")
            log.setLevel(logging.DEBUG)
            if not log.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
                handler.setFormatter(formatter)
                log.addHandler(handler)
            self.logger = log
        else:
            self.logger = cfg.logger

        # Instantiate modular Connection Manager
        self._conn = DivoomConnection(self, cfg)

        # Register functional submodules
        self.light = Light(self)
        self.animation = Animation(self)
        self.drawing = Drawing(self)
        self.text = Text(self)

        self.device = Device(self)
        self.time = Time(self)
        self.bluetooth = Bluetooth(self)

        self.music = Music(self)
        self.radio = Radio(self)

        self.alarm = Alarm(self)
        self.sleep = Sleep(self)
        self.timeplan = Timeplan(self)
        self.weather = Weather(self)

        self.scoreboard = Scoreboard(self)
        self.timer = Timer(self)
        self.countdown = Countdown(self)
        self.noise = Noise(self)
        self.notification = Notification(self)
        self.hot_update = HotUpdate(self)
        self.aid_sleep = AidSleep(self)

        self.display = Display(self)
        self.system = System(self)
        self.sound = SoundControl(self)
        self.control = Control(self)
        self.tool = Tool(self)
        self.game = Game(self)
        self.design = Design(self)

        # Frame-push chunk size (Kare: matches the original DivoomProtocol
        # default). Used by display.show_image for image/animation splitting.
        self.chunksize = kwargs.get('chunksize', models.DEFAULT_CHUNK_SIZE)

        self.logger.debug("Divoom.__init__ completed facade registration.")

    @classmethod
    def from_config(cls, config: models.DivoomConfig) -> "Divoom":
        return cls(config=config)

    @classmethod
    def from_mac(cls, mac: str, logger: Optional[object] = None, **kwargs) -> "Divoom":
        return cls(mac=mac, logger=logger, **kwargs)

    @property
    def mac(self) -> str | None:
        return self._conn.mac if hasattr(self, '_conn') else self._mac

    @mac.setter
    def mac(self, val: str | None) -> None:
        if hasattr(self, '_conn'):
            self._conn.mac = val
        self._mac = val

    @property
    def device_name(self) -> str | None:
        return self._conn.device_name if hasattr(self, '_conn') else self._device_name

    @device_name.setter
    def device_name(self, val: str | None) -> None:
        if hasattr(self, '_conn'):
            self._conn.device_name = val
        self._device_name = val

    # ── Backward Compatible Utility Methods (Mock targets & internal helpers) ────

    def _int2hexlittle(self, value: int) -> str:
        from . import framing
        return framing.int2hexlittle(value)

    def _escape_payload(self, payload_bytes: list) -> list:
        from . import framing
        return framing.escape_payload(payload_bytes)

    def _getCRC(self, data_bytes: list) -> str:
        from . import framing
        return framing.get_checksum(data_bytes)

    def _make_message(self, payload_bytes: list) -> bytes:
        from . import framing
        return framing.encode_basic_payload(payload_bytes, escape=self.escapePayload)

    def _make_message_ios_le(self, payload_bytes: list, packet_number: int = 0x00000000) -> bytes:
        from . import framing
        return framing.encode_ios_le_payload(payload_bytes, packet_number=packet_number)

    def _handle_ios_le_notification(self, data: bytes) -> bool:
        return self._conn._handle_ios_le_notification(data)

    def _handle_basic_protocol_notification(self, new_data: bytearray) -> bool:
        return self._conn._handle_basic_protocol_notification(new_data)

    async def _send_basic_protocol_payload(self, payload_bytes: list, write_with_response: bool) -> bool:
        return await self._conn._send_basic_protocol_payload(payload_bytes, write_with_response)

    async def _send_ios_le_payload(self, payload_bytes: list, write_with_response: bool) -> bool:
        return await self._conn._send_ios_le_payload(payload_bytes, write_with_response)

    async def _send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        return await self._conn._send_payload(payload_bytes, max_retries=max_retries, **kwargs)

    async def _wait_for_response(self, command_id: int, timeout: float = 10.0) -> bytes | None:
        return await self._conn._wait_for_response(command_id, timeout)

    # ── Backwards Compatible Client Properties ───────────────────────────────────

    @property
    def client(self) -> Any:
        return self._conn.client
    @client.setter
    def client(self, val: Any) -> None:
        self._conn.client = val

    @property
    def notification_queue(self) -> Any:
        return self._conn.notification_queue
    @notification_queue.setter
    def notification_queue(self, val: Any) -> None:
        self._conn.notification_queue = val

    def drain_notifications(self) -> int:
        """Discard any queued (stale/unsolicited) notification frames so the next
        query reads its OWN fresh response. The device sends unsolicited frames
        on state change (e.g. a 0x46 when brightness changes), which otherwise
        make manual read-back methods lag one step behind. Returns the count
        drained. Mirrors the drain in send_command_and_wait_for_response."""
        q = self._conn.notification_queue
        n = 0
        while not q.empty():
            try:
                q.get_nowait()
                n += 1
            except Exception:
                break
        return n

    @property
    def use_ios_le_protocol(self) -> bool:
        return self._conn.use_ios_le_protocol
    @use_ios_le_protocol.setter
    def use_ios_le_protocol(self, val: bool) -> None:
        self._conn.use_ios_le_protocol = val

    @property
    def message_buf(self) -> bytearray:
        return self._conn.message_buf
    @message_buf.setter
    def message_buf(self, val: bytearray) -> None:
        self._conn.message_buf = val

    @property
    def WRITE_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.WRITE_CHARACTERISTIC_UUID
    @WRITE_CHARACTERISTIC_UUID.setter
    def WRITE_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.WRITE_CHARACTERISTIC_UUID = val

    @property
    def NOTIFY_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.NOTIFY_CHARACTERISTIC_UUID
    @NOTIFY_CHARACTERISTIC_UUID.setter
    def NOTIFY_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.NOTIFY_CHARACTERISTIC_UUID = val

    @property
    def READ_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.READ_CHARACTERISTIC_UUID
    @READ_CHARACTERISTIC_UUID.setter
    def READ_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.READ_CHARACTERISTIC_UUID = val

    @property
    def SPP_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.SPP_CHARACTERISTIC_UUID
    @SPP_CHARACTERISTIC_UUID.setter
    def SPP_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.SPP_CHARACTERISTIC_UUID = val

    @property
    def escapePayload(self) -> bool:
        return self._conn.escapePayload
    @escapePayload.setter
    def escapePayload(self, val: bool) -> None:
        self._conn.escapePayload = val

    @property
    def max_reconnect_attempts(self) -> int:
        return self._conn.max_reconnect_attempts
    @max_reconnect_attempts.setter
    def max_reconnect_attempts(self, val: int) -> None:
        self._conn.max_reconnect_attempts = val

    @property
    def reconnect_delay(self) -> float:
        return self._conn.reconnect_delay
    @reconnect_delay.setter
    def reconnect_delay(self, val: float) -> None:
        self._conn.reconnect_delay = val

    @property
    def is_connected(self) -> bool:
        return self._conn.is_connected

    @property
    def is_alive(self) -> bool:
        """BLE Hardening P2: honest liveness — connected AND no pending drop."""
        return getattr(self._conn, "is_alive", self._conn.is_connected)

    # ── Transport Layer Awareness ─────────────────────────────────────────────

    @property
    def transport_status(self) -> dict:
        """
        Return the live status of all four transport layers.

        Used by the GUI bridge (``get_transport_status()``) to drive the
        4-badge panel in the sidebar.

        Returns a dict with keys ``ble``, ``lan``, ``cloud``, ``external``
        and boolean/string values describing availability.

        Usage::

            status = divoom.transport_status
            # {'ble': True, 'lan': False, 'cloud': False, 'external': True}
        """
        return {
            "ble":      self._conn.is_connected,
            "lan":      self._lan is not None,
            "lan_ip":   self._lan.device_ip if self._lan else None,
            "cloud":    False,   # set True after successful cloud auth
            "external": True,    # assume internet unless proven otherwise
        }

    @property
    def capabilities(self):
        """R13 §1 — return the Capabilities for the connected device.

        Lookup order (R13 review — name heuristic removed, hardware-derived
        paths preferred):
          1. ``device_type`` kwarg passed to the constructor (explicit
             override; requires the caller to know the model)
          2. ``DeviceRegistry`` lookup by MAC (per-install
             ``~/.config/divoom-control/devices.json``)
          3. ``capabilities_from_manufacturer_data`` — if the caller
             has passed an ``AdvertisementData`` via the
             ``advertisement_data`` kwarg
          4. Baseline (most-limited Pixoo defaults)

        Source: ``divoom_lib.models.capabilities.DEVICE_CAPABILITIES``
        (filled from the decompiled APK's ``DeviceTypeEnum`` + reference repos).
        """
        # 1. Explicit override.
        if self._device_type:
            return capabilities_for(self._device_type)
        # 2. MAC registry.
        if self._mac:
            from .models.capabilities import DeviceRegistry
            caps = DeviceRegistry().lookup(self._mac)
            if caps is not None:
                return caps
        # 3. Manufacturer-data fingerprint (if the caller provided it).
        if self._advertisement_data is not None:
            from .models.capabilities import capabilities_from_manufacturer_data
            caps = capabilities_from_manufacturer_data(self._advertisement_data)
            if caps is not None:
                return caps
        # 4. Baseline.
        return capabilities_for(None)

    @property
    def device_type(self) -> str | None:
        return self._device_type
    @device_type.setter
    def device_type(self, val: str | None) -> None:
        self._device_type = val

    @property
    def lan(self):
        """
        The LAN transport for this device, or None if not configured.

        Transport:  LAN — configure via ``lan_ip`` kwarg or TOML config.
        """
        return self._lan

    @property
    def available_transports(self) -> list[Transport]:
        """List of currently available transports for this device."""
        available = [Transport.EXT]   # always
        if self._conn.is_connected:
            available.append(Transport.BLE)
        if self._lan is not None:
            available.append(Transport.LAN)
        return available

    @property
    def protocol(self) -> "Divoom":
        return self

    @property
    def _expected_response_command(self) -> Any:
        return self._conn._expected_response_command
    @_expected_response_command.setter
    def _expected_response_command(self, val: Any) -> None:
        self._conn._expected_response_command = val

    # ── Context Managers and Converters ──────────────────────────────────────────

    @asynccontextmanager
    async def _framing_context(self, use_ios: bool, escape: bool):
        prev_use_ios = self._conn.use_ios_le_protocol
        prev_escape = getattr(self._conn, "escapePayload", False)

        self._conn.use_ios_le_protocol = use_ios
        self._conn.escapePayload = escape
        try:
            yield
        finally:
            self._conn.use_ios_le_protocol = prev_use_ios
            self._conn.escapePayload = prev_escape

    def convert_color(self, color_input: str | tuple | list) -> list:
        from .utils.converters import color_to_rgb_list
        return color_to_rgb_list(color_input)

    # ── Delegated BLE and Diagnostic Transport Methods ───────────────────────────

    async def connect(self) -> None:
        await self._conn.connect()

    async def disconnect(self) -> None:
        await self._conn.disconnect()

    def notification_handler(self, sender: int, data: bytearray) -> None:
        self._conn.notification_handler(sender, data)

    async def wait_for_response(self, command_id: int, timeout: float = 3.0) -> bytes | None:
        return await self._conn.wait_for_response(command_id, timeout)

    async def wait_for_any_response(self, command_ids: list, timeout: float = 10.0):
        return await self._conn.wait_for_any_response(command_ids, timeout)

    async def send_command_and_wait_for_response(self, command: int | str, args: list | None = None, timeout: float = 10.0) -> bytes | None:
        return await self._conn.send_command_and_wait_for_response(command, args, timeout=timeout)

    async def send_command(self, command: int | str, args: list | None = None, write_with_response: bool = False) -> bool:
        return await self._conn.send_command(command, args, write_with_response=write_with_response)

    async def send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        return await self._conn.send_payload(payload_bytes, max_retries=max_retries, **kwargs)

    async def probe_write_characteristics_and_try_channel_switch(self, write_chars: list, notify_chars: list, read_chars: list, cached_data: dict, cache_dir: str, device_id: str, colors: list = None, cache_mod: Any = None):
        return await self._conn.probe_write_characteristics_and_try_channel_switch(
            write_chars, notify_chars, read_chars, cached_data, cache_dir, device_id, colors=colors, cache_mod=cache_mod
        )

    async def set_canonical_light(self, cache_dir: str, device_id: str, cache_mod: Any = None, rgb: list = None):
        return await self._conn.set_canonical_light(cache_dir, device_id, cache_mod=cache_mod, rgb=rgb)

    async def _try_send_command_with_framing(self, command_id: int, payload: list, timeout: float = 3.0, use_ios: bool = False, escape: bool = False):
        return await self._conn._try_send_command_with_framing(command_id, payload, timeout=timeout, use_ios=use_ios, escape=escape)

    async def _send_diagnostic_payload(self, write_uuid: str, args_payload: list, cache_data: dict, cache_dir: str, device_id: str, cache_mod: Any = None):
        return await self._conn._send_diagnostic_payload(write_uuid, args_payload, cache_data, cache_dir, device_id, cache_mod=cache_mod)

    async def _handle_cached_payload(self, write_uuid: str, cached_data: dict, cache_dir: str, device_id: str, cache_mod: Any = None):
        return await self._conn._handle_cached_payload(write_uuid, cached_data, cache_dir, device_id, cache_mod=cache_mod)