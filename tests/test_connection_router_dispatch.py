"""Connection-router coverage: internal payload/response dispatch (_send_*
and _wait_for_response) (split from test_connection_router_coverage.py)."""
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


# ── _send_basic_protocol_payload(): SPP path, forward path, fallback path ───

def test_send_basic_protocol_payload_spp_path_success(monkeypatch):
    conn = _make_conn(monkeypatch)
    sent = {}

    class _SppSend:
        FRAMING_BASIC = "basic"

        async def send(self, payload, framing):
            sent["payload"] = payload
            sent["framing"] = framing

    conn._active_transport = _SppSend()
    conn._use_spp = True
    ok = _run(conn._send_basic_protocol_payload([0x01, 0x02], write_with_response=False))

    assert ok is True
    assert sent == {"payload": [0x01, 0x02], "framing": "basic"}


def test_send_basic_protocol_payload_spp_path_exception_logged(monkeypatch, caplog):
    conn = _make_conn(monkeypatch)

    class _SppBoom:
        FRAMING_BASIC = "basic"

        async def send(self, payload, framing):
            raise RuntimeError("spp send boom")

    conn._active_transport = _SppBoom()
    conn._use_spp = True
    with caplog.at_level(logging.ERROR):
        ok = _run(conn._send_basic_protocol_payload([0x01], write_with_response=False))

    assert ok is False
    assert any("Error sending Basic SPP payload" in r.message for r in caplog.records)


def test_send_basic_protocol_payload_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)
    called = {}

    async def fake(payload_bytes, write_with_response):
        called["args"] = (payload_bytes, write_with_response)
        return True

    conn._active_transport._send_basic_protocol_payload = fake
    ok = _run(conn._send_basic_protocol_payload([0x03], write_with_response=True))

    assert ok is True
    assert called["args"] == ([0x03], True)


def test_send_basic_protocol_payload_falls_back_to_send_payload(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()

    async def fake_send_payload(payload_bytes, write_with_response=False):
        return "fallback-ok"

    monkeypatch.setattr(conn, "send_payload", fake_send_payload)
    result = _run(conn._send_basic_protocol_payload([0x04], write_with_response=True))

    assert result == "fallback-ok"


# ── _send_ios_le_payload(): SPP path, forward path, fallback path ───────────

def test_send_ios_le_payload_spp_path_success(monkeypatch):
    conn = _make_conn(monkeypatch)
    sent = {}

    class _SppSend:
        FRAMING_IOS_LE = "ios_le"

        async def send(self, payload, framing):
            sent["payload"] = payload
            sent["framing"] = framing

    conn._active_transport = _SppSend()
    conn._use_spp = True
    ok = _run(conn._send_ios_le_payload([0x09], write_with_response=True))

    assert ok is True
    assert sent == {"payload": [0x09], "framing": "ios_le"}


def test_send_ios_le_payload_spp_path_exception_logged(monkeypatch, caplog):
    conn = _make_conn(monkeypatch)

    class _SppBoom:
        FRAMING_IOS_LE = "ios_le"

        async def send(self, payload, framing):
            raise RuntimeError("ios boom")

    conn._active_transport = _SppBoom()
    conn._use_spp = True
    with caplog.at_level(logging.ERROR):
        ok = _run(conn._send_ios_le_payload([0x09], write_with_response=False))

    assert ok is False
    assert any("Error sending iOS LE SPP payload" in r.message for r in caplog.records)


def test_send_ios_le_payload_forwards_to_transport_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)
    called = {}

    async def fake(payload_bytes, write_with_response):
        called["args"] = (payload_bytes, write_with_response)
        return True

    conn._active_transport._send_ios_le_payload = fake
    ok = _run(conn._send_ios_le_payload([0x0A], write_with_response=False))

    assert ok is True
    assert called["args"] == ([0x0A], False)


def test_send_ios_le_payload_falls_back_to_send_payload(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()

    async def fake_send_payload(payload_bytes, write_with_response=False):
        return "fallback-ios-ok"

    monkeypatch.setattr(conn, "send_payload", fake_send_payload)
    result = _run(conn._send_ios_le_payload([0x0B], write_with_response=True))

    assert result == "fallback-ios-ok"


# ── _send_payload() (internal router dispatch): SPP vs non-SPP ─────────────

def test_send_payload_dunder_delegates_to_basic_protocol_when_spp(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._use_spp = True
    called = {}

    async def fake_basic(payload_bytes, write_with_response=False):
        called["args"] = (payload_bytes, write_with_response)
        return True

    monkeypatch.setattr(conn, "_send_basic_protocol_payload", fake_basic)
    ok = _run(conn._send_payload([0x01], write_with_response=True))

    assert ok is True
    assert called["args"] == ([0x01], True)


def test_send_payload_dunder_delegates_to_transport_when_not_spp(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._use_spp = False
    called = {}

    async def fake_send_payload(payload_bytes, max_retries, **kwargs):
        called["args"] = (payload_bytes, max_retries, kwargs)
        return True

    conn._active_transport.send_payload = fake_send_payload
    ok = _run(conn._send_payload([0x02], max_retries=5, write_with_response=True))

    assert ok is True
    assert called["args"] == ([0x02], 5, {"write_with_response": True})


# ── _wait_for_response() (internal router dispatch) ─────────────────────────

def test_wait_for_response_dunder_forwards_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(_cmd_id, _timeout):
        return b"resp"

    conn._active_transport._wait_for_response = fake
    result = _run(conn._wait_for_response(0x01, timeout=1.0))

    assert result == b"resp"


def test_wait_for_response_dunder_falls_back_to_public_wait(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()

    async def fake_wait(_cmd_id, _timeout):
        return b"fallback"

    monkeypatch.setattr(conn, "wait_for_response", fake_wait)
    result = _run(conn._wait_for_response(0x02, timeout=2.0))

    assert result == b"fallback"
