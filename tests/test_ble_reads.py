"""BLE Hardening Phase 5 — get_* read-back resilience.

A flaky device read retries with a short timeout and degrades to the last-good
value (or a typed unknown) instead of returning a bare ``None`` the UI can't
distinguish from a real value.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.ble_reads import read_with_retry, ReadCache, ReadResult
from divoom_lib.ble_connection import FailureReason


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── read_with_retry primitive ──────────────────────────────────────────────

def test_fresh_value_is_returned_and_cached():
    cache = ReadCache()

    async def _read():
        return 42

    res = _run(read_with_retry(_read, cache=cache, cache_key="b"))
    assert res.ok and res.value == 42 and res.from_cache is False
    assert cache.get("b") == 42


def test_retries_then_succeeds():
    calls = {"n": 0}

    async def _read():
        calls["n"] += 1
        if calls["n"] < 2:
            return None          # first reply lost
        return 7

    res = _run(read_with_retry(_read, attempts=3, sleep=_nosleep, cache=ReadCache(),
                               cache_key="b"))
    assert res.ok and res.value == 7 and calls["n"] == 2


def test_exhausted_with_cache_serves_last_good():
    cache = ReadCache()
    cache.put("name", "Ditoo")

    async def _read():
        return None              # always unanswered now

    res = _run(read_with_retry(_read, attempts=2, sleep=_nosleep,
                               cache=cache, cache_key="name"))
    assert res.ok is True
    assert res.value == "Ditoo"
    assert res.from_cache is True
    assert res.known is True


def test_exhausted_without_cache_is_typed_unknown():
    async def _read():
        return None

    res = _run(read_with_retry(_read, attempts=2, sleep=_nosleep,
                               cache=ReadCache(), cache_key="name"))
    assert res.ok is False
    assert res.known is False            # UI renders a dash, not a wrong value
    assert res.reason is FailureReason.DROPPED   # replied empty → invalid


def test_timeout_is_retried_then_typed():
    async def _read():
        await asyncio.sleep(1.0)         # exceeds the per-attempt timeout
        return 1

    res = _run(read_with_retry(_read, attempts=2, timeout=0.01, sleep=_nosleep,
                               cache=ReadCache(), cache_key="b"))
    assert res.ok is False and res.reason is FailureReason.TIMEOUT


def test_validate_rejects_junk_and_retries():
    calls = {"n": 0}

    async def _read():
        calls["n"] += 1
        return -1 if calls["n"] == 1 else 99

    res = _run(read_with_retry(_read, attempts=3, sleep=_nosleep,
                               validate=lambda v: v >= 0,
                               cache=ReadCache(), cache_key="b"))
    assert res.ok and res.value == 99 and calls["n"] == 2


def test_exception_in_read_does_not_propagate():
    async def _read():
        raise RuntimeError("ble write blew up")

    res = _run(read_with_retry(_read, attempts=2, sleep=_nosleep,
                               cache=ReadCache(), cache_key="b"))
    assert res.ok is False and res.reason is FailureReason.UNKNOWN


async def _nosleep(_d):
    return None


# ── wired into Device.get_brightness / get_device_name ─────────────────────

class _FakeComm:
    """Minimal communicator the Device read methods use."""
    def __init__(self, *, name_response=None, brightness_payload=None,
                 use_ios_le_protocol=True):
        self.logger = logging.getLogger("fakecomm")
        self.use_ios_le_protocol = use_ios_le_protocol
        self._expected_response_command = None
        self._name_response = name_response
        self._brightness_payload = brightness_payload
        self.device_name = ""        # no advertised name → reads go to the device
        self.fail = False

    def drain_notifications(self):
        return 0

    @asynccontextmanager
    async def _framing_context(self, **kw):
        yield

    async def send_command(self, *a, **k):
        return True

    async def wait_for_response(self, *a, **k):
        if self.fail:
            return None
        return self._brightness_payload

    async def send_command_and_wait_for_response(self, *a, **k):
        if self.fail:
            return None
        return self._name_response


def _device(comm):
    from divoom_lib.system.device import Device
    return Device(comm)


def test_get_brightness_fresh_then_cached_on_drop():
    # payload[6] is the brightness byte.
    comm = _FakeComm(brightness_payload=[0, 0, 0, 0, 0, 0, 80])
    dev = _device(comm)
    assert _run(dev.get_brightness()) == 80      # fresh
    comm.fail = True                              # device stops answering
    assert _run(dev.get_brightness()) == 80       # served from last-good cache


def test_get_brightness_unknown_when_never_read():
    comm = _FakeComm(brightness_payload=None)
    comm.fail = True
    dev = _device(comm)
    assert _run(dev.get_brightness()) is None     # no value, nothing cached → unknown


def test_get_device_name_fresh_then_cached_on_drop():
    # response[0]=length, name bytes start at index 1 (GDN constants).
    name = "Ditoo-7"
    resp = [len(name)] + list(name.encode("utf-8"))
    comm = _FakeComm(name_response=resp)
    dev = _device(comm)
    assert _run(dev.get_device_name()) == name
    comm.fail = True
    assert _run(dev.get_device_name()) == name    # last-good
