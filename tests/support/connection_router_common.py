"""Shared fakes + connection factory for the split connection-router test
modules."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import divoom_lib.divoom  # noqa: F401  - import first to resolve the import cycle
from divoom_lib import bt_spp_transport
from divoom_lib import models
from divoom_lib.ble_transport import BLETransport
from divoom_lib.connection import DivoomConnection


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeClient:
    """Stand-in bleak client. Its class name does NOT contain
    'MockBleakClient', so `is_mock` stays False and connect()'s name
    -resolution / SPP-routing branches (the ones under test) actually run —
    without ever constructing (or needing to patch) a real BleakClient."""
    def __init__(self):
        self.is_connected = False


class _FakeDivoom:
    def __init__(self):
        self.logger = logging.getLogger("test_connection_router")


def _make_conn(monkeypatch, *, device_name=None, mac="AA:BB:CC:DD:EE:FF",
                use_ios_le_protocol=None, mock_ble_env=False):
    """A DivoomConnection wired to a real BLETransport whose `connect`/
    `disconnect` are patched to async no-ops at the class level (so any
    freshly-swapped-in BLETransport instance is safe too)."""
    if mock_ble_env:
        monkeypatch.setenv("DIVOOM_MOCK_BLE", "1")
    else:
        monkeypatch.delenv("DIVOOM_MOCK_BLE", raising=False)
    cfg = models.DivoomConfig(
        mac=mac, device_name=device_name, client=_FakeClient(),
        write_characteristic_uuid="w", notify_characteristic_uuid="n",
        read_characteristic_uuid="r", use_ios_le_protocol=use_ios_le_protocol,
    )
    divoom = _FakeDivoom()
    conn = DivoomConnection(divoom, cfg)
    monkeypatch.setattr(BLETransport, "connect", AsyncMock())
    monkeypatch.setattr(BLETransport, "disconnect", AsyncMock())
    return conn


class _FakeSpp:
    """Stand-in BTSppTransport — records constructor kwargs, never touches
    real macOS RFCOMM."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.mac_address = kwargs.get("mac_address")
        self.device_name = kwargs.get("device_name")

    async def connect(self):
        pass

    async def disconnect(self):
        pass
