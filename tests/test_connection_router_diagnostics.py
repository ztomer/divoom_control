"""Connection-router coverage: diagnostic/probing forwards and compatibility
hooks (split from test_connection_router_coverage.py)."""
import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import divoom_lib.divoom  # noqa: F401  - import first to resolve the import cycle
from divoom_lib import bt_spp_transport
from divoom_lib import models
from divoom_lib import spp_connection
from divoom_lib.ble_transport import BLETransport
from divoom_lib.connection import DivoomConnection
from tests.support.connection_router_common import (  # noqa: F401
    _FakeClient,
    _FakeDivoom,
    _FakeSpp,
    _make_conn,
    _run,
)


# ── Diagnostic / probing forwards: hasattr(transport) True vs fall back ────

def test_probe_write_characteristics_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(*_a, **_k):
        return "transport-result"

    conn._active_transport.probe_write_characteristics_and_try_channel_switch = fake
    result = _run(conn.probe_write_characteristics_and_try_channel_switch(
        ["w1"], ["n1"], ["r1"], {}, "/tmp/cache", "dev1"))

    assert result == "transport-result"


def test_probe_write_characteristics_falls_back_to_probing_module(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()
    from divoom_lib import probing

    async def fake_probe(*_a, **_k):
        return "probing-module-result"

    monkeypatch.setattr(probing, "probe_write_characteristics_and_try_channel_switch", fake_probe)
    result = _run(conn.probe_write_characteristics_and_try_channel_switch(
        ["w1"], ["n1"], ["r1"], {}, "/tmp/cache", "dev1"))

    assert result == "probing-module-result"


def test_set_canonical_light_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(*_a, **_k):
        return "transport-light"

    conn._active_transport.set_canonical_light = fake
    result = _run(conn.set_canonical_light("/tmp/cache", "dev1"))

    assert result == "transport-light"


def test_set_canonical_light_falls_back_to_probing_module(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()
    from divoom_lib import probing

    async def fake_probe(*_a, **_k):
        return "probing-light"

    monkeypatch.setattr(probing, "set_canonical_light", fake_probe)
    result = _run(conn.set_canonical_light("/tmp/cache", "dev1"))

    assert result == "probing-light"


def test_try_send_command_with_framing_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(*_a, **_k):
        return "transport-framing"

    conn._active_transport._try_send_command_with_framing = fake
    result = _run(conn._try_send_command_with_framing(0x01, [1, 2]))

    assert result == "transport-framing"


def test_try_send_command_with_framing_falls_back_to_probing_module(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()
    from divoom_lib import probing

    async def fake_probe(*_a, **_k):
        return "probing-framing"

    monkeypatch.setattr(probing, "_try_send_command_with_framing", fake_probe)
    result = _run(conn._try_send_command_with_framing(0x01, [1, 2]))

    assert result == "probing-framing"


def test_send_diagnostic_payload_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(*_a, **_k):
        return "transport-diag"

    conn._active_transport._send_diagnostic_payload = fake
    result = _run(conn._send_diagnostic_payload("w", [1], {}, "/tmp/cache", "dev1"))

    assert result == "transport-diag"


def test_send_diagnostic_payload_falls_back_to_probing_module(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()
    from divoom_lib import probing

    async def fake_probe(*_a, **_k):
        return "probing-diag"

    monkeypatch.setattr(probing, "_send_diagnostic_payload", fake_probe)
    result = _run(conn._send_diagnostic_payload("w", [1], {}, "/tmp/cache", "dev1"))

    assert result == "probing-diag"


def test_handle_cached_payload_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(*_a, **_k):
        return "transport-cached"

    conn._active_transport._handle_cached_payload = fake
    result = _run(conn._handle_cached_payload("w", {}, "/tmp/cache", "dev1"))

    assert result == "transport-cached"


def test_handle_cached_payload_falls_back_to_probing_module(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()
    from divoom_lib import probing

    async def fake_probe(*_a, **_k):
        return "probing-cached"

    monkeypatch.setattr(probing, "_handle_cached_payload", fake_probe)
    result = _run(conn._handle_cached_payload("w", {}, "/tmp/cache", "dev1"))

    assert result == "probing-cached"


# ── Lower-level compatibility hooks ─────────────────────────────────────────

def test_handle_ios_le_notification_forwards_and_falls_back(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport._handle_ios_le_notification = lambda data: True
    assert conn._handle_ios_le_notification(b"x") is True

    class _Bare:
        pass

    conn._active_transport = _Bare()
    assert conn._handle_ios_le_notification(b"x") is False


def test_handle_basic_protocol_notification_forwards_and_falls_back(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport._handle_basic_protocol_notification = lambda data: True
    assert conn._handle_basic_protocol_notification(bytearray(b"x")) is True

    class _Bare:
        pass

    conn._active_transport = _Bare()
    assert conn._handle_basic_protocol_notification(bytearray(b"x")) is False
