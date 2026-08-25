"""Connection-router coverage: forwarding properties, public delegation and
notification-handler plumbing (split from
test_connection_router_coverage.py)."""
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


# ── is_connected / is_alive / use_spp properties ────────────────────────────

def test_is_connected_delegates_to_active_transport(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport.client.is_connected = True
    assert conn.is_connected is True


def test_is_alive_uses_transport_is_alive_when_present(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport.client.is_connected = True
    conn._active_transport._connection_likely_broken = True
    assert conn.is_alive is False    # connected per OS, but a drop is pending


def test_is_alive_falls_back_to_is_connected_when_unsupported(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _NoAlive:
        is_connected = True

    conn._active_transport = _NoAlive()
    assert conn.is_alive is True


def test_use_spp_property(monkeypatch):
    conn = _make_conn(monkeypatch)
    assert conn.use_spp is False
    conn._use_spp = True
    assert conn.use_spp is True


# ── notification_handler() ──────────────────────────────────────────────────

def test_notification_handler_forwards_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)
    seen = {}
    conn._active_transport.notification_handler = lambda sender, data: seen.update(sender=sender, data=data)

    conn.notification_handler(5, bytearray(b"abc"))

    assert seen == {"sender": 5, "data": bytearray(b"abc")}


def test_notification_handler_noop_when_unsupported(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _NoHandler:
        pass

    conn._active_transport = _NoHandler()
    conn.notification_handler(1, bytearray(b"x"))   # must not raise


# ── send_command() (public router method — bypasses transport routing) ─────

def test_send_command_success_builds_payload_and_delegates(monkeypatch):
    conn = _make_conn(monkeypatch)
    captured = {}

    async def fake_send_payload(payload_bytes, write_with_response=False):
        captured["payload"] = payload_bytes
        captured["wwr"] = write_with_response
        return True

    conn._divoom._send_payload = fake_send_payload
    ok = _run(conn.send_command(0x45, [1, 2], write_with_response=True))

    assert ok is True
    assert captured["payload"] == [0x45, 1, 2]
    assert captured["wwr"] is True


def test_send_command_resolves_string_command_name(monkeypatch):
    conn = _make_conn(monkeypatch)
    name, cmd_id = next(iter(models.COMMANDS.items()))
    captured = {}

    async def fake_send_payload(payload_bytes, write_with_response=False):
        captured["payload"] = payload_bytes
        return True

    conn._divoom._send_payload = fake_send_payload
    _run(conn.send_command(name))

    assert captured["payload"][0] == cmd_id


def test_send_command_exception_is_caught(monkeypatch, caplog):
    conn = _make_conn(monkeypatch)

    async def boom(*_a, **_k):
        raise RuntimeError("boom")

    conn._divoom._send_payload = boom
    with caplog.at_level(logging.ERROR):
        ok = _run(conn.send_command(0x45))

    assert ok is False
    assert any("Error calling send_payload" in r.message for r in caplog.records)


# ── send_payload() / wait_for_response() (public delegation) ───────────────

def test_send_payload_public_delegates_to_active_transport(monkeypatch):
    conn = _make_conn(monkeypatch)
    called = {}

    async def fake(payload_bytes, max_retries, **kwargs):
        called["args"] = (payload_bytes, max_retries, kwargs)
        return "ok"

    conn._active_transport.send_payload = fake
    result = _run(conn.send_payload([0x01], max_retries=2, foo="bar"))

    assert result == "ok"
    assert called["args"] == ([0x01], 2, {"foo": "bar"})


def test_wait_for_response_public_delegates(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake(cmd_id, timeout):
        return (cmd_id, timeout)

    conn._active_transport.wait_for_response = fake
    result = _run(conn.wait_for_response(0x5, timeout=3.0))

    assert result == (0x5, 3.0)


def test_disconnect_public_delegates(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport.disconnect = AsyncMock()

    _run(conn.disconnect())

    conn._active_transport.disconnect.assert_awaited_once()


# ── send_command_and_wait_for_response(): string command + contention log ──

def test_send_command_and_wait_for_response_resolves_string_command(monkeypatch):
    conn = _make_conn(monkeypatch)
    name, cmd_id = next(iter(models.COMMANDS.items()))

    class _FakeDivoomSend:
        async def send_command(self, command, args, write_with_response=False):
            pass

        async def _wait_for_response(self, command_id, timeout):
            assert command_id == cmd_id
            return b"resp"

    conn._divoom = _FakeDivoomSend()
    result = _run(conn.send_command_and_wait_for_response(name, timeout=1.0))

    assert result == b"resp"
    assert conn._expected_response_command == cmd_id


def test_send_command_and_wait_for_response_drains_stale_notification_queue(monkeypatch):
    """Stale frames left in the notification_queue from a prior exchange must
    be drained before the new wait is set up."""
    conn = _make_conn(monkeypatch)

    class _FakeDivoomSend:
        async def send_command(self, command, args, write_with_response=False):
            pass

        async def _wait_for_response(self, command_id, timeout):
            return b"resp"

    conn._divoom = _FakeDivoomSend()
    conn.notification_queue.put_nowait(b"stale-1")
    conn.notification_queue.put_nowait(b"stale-2")

    result = _run(conn.send_command_and_wait_for_response(0x01, timeout=1.0))

    assert result == b"resp"
    assert conn.notification_queue.empty()


def test_send_command_and_wait_for_response_logs_when_lock_contended(monkeypatch, caplog):
    conn = _make_conn(monkeypatch)

    class _SlowDivoom:
        async def send_command(self, command, args, write_with_response=False):
            await asyncio.sleep(0.05)

        async def _wait_for_response(self, command_id, timeout):
            return command_id

    conn._divoom = _SlowDivoom()

    async def run():
        return await asyncio.gather(
            conn.send_command_and_wait_for_response(0xAA, timeout=5.0),
            conn.send_command_and_wait_for_response(0xBB, timeout=5.0),
        )

    with caplog.at_level(logging.WARNING):
        results = _run(run())

    assert sorted(results) == [0xAA, 0xBB]
    assert any("contended" in r.message for r in caplog.records)


# ── wait_for_any_response() / _listen_commands ──────────────────────────────

def test_wait_for_any_response_returns_none_when_unsupported(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _NoWaitAny:
        pass

    conn._active_transport = _NoWaitAny()
    result = _run(conn.wait_for_any_response([1, 2], timeout=0.01))

    assert result is None


def test_wait_for_any_response_forwards_to_transport(monkeypatch):
    conn = _make_conn(monkeypatch)

    async def fake_wait_any(command_ids, timeout):
        return (command_ids, timeout)

    conn._active_transport.wait_for_any_response = fake_wait_any
    result = _run(conn.wait_for_any_response([1, 2], timeout=5.0))

    assert result == ([1, 2], 5.0)


def test_listen_commands_property_forwards(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._active_transport._listen_commands = {1, 2}
    assert conn._listen_commands == {1, 2}


def test_listen_commands_property_defaults_none_when_unsupported(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _NoListen:
        pass

    conn._active_transport = _NoListen()
    assert conn._listen_commands is None


# ── _spp_client property/setter ─────────────────────────────────────────────

def test_spp_client_getter_returns_active_transport_when_use_spp(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._use_spp = True
    assert conn._spp_client is conn._active_transport


def test_spp_client_getter_returns_none_when_not_spp(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._use_spp = False
    assert conn._spp_client is None


def test_spp_client_setter_switches_active_transport(monkeypatch):
    conn = _make_conn(monkeypatch)
    fake = object()
    conn._spp_client = fake

    assert conn._active_transport is fake
    assert conn._use_spp is True


def test_spp_client_setter_ignores_none(monkeypatch):
    conn = _make_conn(monkeypatch)
    original = conn._active_transport
    conn._spp_client = None

    assert conn._active_transport is original


# ── mac / device_name properties (both SPP and BLE branches) ───────────────

def test_mac_property_ble_branch(monkeypatch):
    conn = _make_conn(monkeypatch)
    assert conn.mac == conn._active_transport.mac

    conn.mac = "22-33-44-55-66-77"
    assert conn._active_transport.mac == "22-33-44-55-66-77"
    assert conn.cfg.mac == "22-33-44-55-66-77"


def test_mac_property_spp_branch(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._use_spp = True
    conn._active_transport.mac_address = "11-22-33"
    assert conn.mac == "11-22-33"

    conn.mac = "44-55-66"
    assert conn._active_transport.mac_address == "44-55-66"
    assert conn.cfg.mac == "44-55-66"


def test_device_name_property_roundtrip(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn.device_name = "New-Name"

    assert conn.device_name == "New-Name"
    assert conn.cfg.device_name == "New-Name"


# ── characteristic UUID / escapePayload / use_ios_le_protocol / client /
#    notification_queue / message_buf setters — both hasattr branches ───────

def test_characteristic_and_misc_setters_forward_when_supported(monkeypatch):
    conn = _make_conn(monkeypatch)

    conn.WRITE_CHARACTERISTIC_UUID = "www"
    conn.NOTIFY_CHARACTERISTIC_UUID = "nnn"
    conn.READ_CHARACTERISTIC_UUID = "rrr"
    conn.SPP_CHARACTERISTIC_UUID = "sss"
    conn.escapePayload = True
    conn.use_ios_le_protocol = True
    conn.client = "new-client"
    conn.message_buf = bytearray(b"hi")

    t = conn._active_transport
    assert t.WRITE_CHARACTERISTIC_UUID == "www" and conn.WRITE_CHARACTERISTIC_UUID == "www"
    assert t.NOTIFY_CHARACTERISTIC_UUID == "nnn" and conn.NOTIFY_CHARACTERISTIC_UUID == "nnn"
    assert t.READ_CHARACTERISTIC_UUID == "rrr" and conn.READ_CHARACTERISTIC_UUID == "rrr"
    assert t.SPP_CHARACTERISTIC_UUID == "sss" and conn.SPP_CHARACTERISTIC_UUID == "sss"
    assert t.escapePayload is True and conn.escapePayload is True
    assert t.use_ios_le_protocol is True and conn.use_ios_le_protocol is True
    assert t.client == "new-client" and conn.client == "new-client"
    assert t.message_buf == bytearray(b"hi") and conn.message_buf == bytearray(b"hi")


def test_characteristic_and_misc_setters_noop_when_unsupported(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()

    conn.WRITE_CHARACTERISTIC_UUID = "x"
    conn.NOTIFY_CHARACTERISTIC_UUID = "y"
    conn.READ_CHARACTERISTIC_UUID = "z"
    conn.SPP_CHARACTERISTIC_UUID = "s"
    conn.escapePayload = False
    conn.use_ios_le_protocol = True
    conn.client = "fake-client"
    conn.message_buf = bytearray(b"x")

    # cfg is captured regardless of transport support...
    assert conn.cfg.write_characteristic_uuid == "x"
    assert conn.cfg.notify_characteristic_uuid == "y"
    assert conn.cfg.read_characteristic_uuid == "z"
    assert conn.cfg.spp_characteristic_uuid == "s"
    assert conn.cfg.escapePayload is False
    assert conn.cfg.use_ios_le_protocol is True
    assert conn.cfg.client == "fake-client"
    # ...but the bare transport has none of these attrs, so getters fall back
    # to their defaults instead of reflecting what was "set".
    assert conn.WRITE_CHARACTERISTIC_UUID == ""
    assert conn.NOTIFY_CHARACTERISTIC_UUID == ""
    assert conn.READ_CHARACTERISTIC_UUID == ""
    assert conn.SPP_CHARACTERISTIC_UUID == ""
    assert conn.escapePayload is True   # default per getattr(..., True)
    assert conn.use_ios_le_protocol is False   # default per getattr(..., False)
    assert conn.client is None
    assert conn.message_buf == bytearray()


def test_notification_queue_roundtrip(monkeypatch):
    conn = _make_conn(monkeypatch)
    q = asyncio.Queue()
    conn.notification_queue = q
    assert conn.notification_queue is q


def test_expected_response_command_roundtrip(monkeypatch):
    conn = _make_conn(monkeypatch)
    conn._expected_response_command = 0x99
    assert conn._expected_response_command == 0x99


def test_expected_response_command_noop_when_unsupported(monkeypatch):
    conn = _make_conn(monkeypatch)

    class _Bare:
        pass

    conn._active_transport = _Bare()
    conn._expected_response_command = 0x11    # setter no-ops (no such attr)
    assert conn._expected_response_command is None   # getter default
