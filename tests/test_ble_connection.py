"""BLE Hardening Phase 1 — ensure_connected + error classification.

Every path is driven by the fault-injecting FakeBleDevice (no hardware, no
real waiting — sleep is stubbed).
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.ble_connection import (
    ConnectionState, FailureReason, ConnectResult,
    classify_connect_error, ensure_connected,
)
from tests.support.fake_ble import FakeBleDevice


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _nosleep(_):
    return None


# ── classification ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,reason", [
    ("Device with address AA was not found", FailureReason.NOT_ADVERTISING),
    ("Operation timed out", FailureReason.TIMEOUT),
    ("Bluetooth device is powered off", FailureReason.ADAPTER_OFF),
    ("Not authorized to use Bluetooth", FailureReason.PERMISSION),
    ("Device already connected", FailureReason.BUSY),
    ("Disconnected during operation", FailureReason.DROPPED),
    ("some weird CoreBluetooth thing", FailureReason.UNKNOWN),
])
def test_classify_connect_error(text, reason):
    assert classify_connect_error(Exception(text)) is reason


def test_classify_timeout_type():
    assert classify_connect_error(asyncio.TimeoutError()) is FailureReason.TIMEOUT


# ── ensure_connected ───────────────────────────────────────────────────────

def test_connects_first_try():
    dev = FakeBleDevice()
    res = _run(ensure_connected(dev, sleep=_nosleep))
    assert res.ok and res.state is ConnectionState.CONNECTED
    assert dev.connect_calls == 1
    assert dev.is_connected


def test_already_connected_is_a_noop():
    dev = FakeBleDevice(connect_results=[True])
    _run(dev.connect())
    res = _run(ensure_connected(dev, sleep=_nosleep))
    assert res.ok and dev.connect_calls == 1  # ensure_connected didn't reconnect


def test_fast_path_uses_is_alive_not_lying_is_connected():
    """R53: a device whose link dropped but whose cached is_connected still reads
    True (the CoreBluetooth lag) must NOT short-circuit the fast-path — the honest
    is_alive signal forces a real reconnect instead of handing back a dead handle."""
    dev = FakeBleDevice(lie_connected=True)   # is_connected=True, is_alive=False
    assert dev.is_connected is True and dev.is_alive is False
    res = _run(ensure_connected(dev, sleep=_nosleep))
    assert res.ok and dev.connect_calls == 1  # it actually reconnected, not a no-op


def test_retries_then_succeeds():
    # fail twice (not-found), then succeed
    dev = FakeBleDevice(connect_results=[
        Exception("was not found"), Exception("was not found"), True])
    res = _run(ensure_connected(dev, attempts=3, sleep=_nosleep))
    assert res.ok and dev.connect_calls == 3


def test_exhausts_and_returns_typed_reason_not_dead_handle():
    dev = FakeBleDevice(raise_on_connect=Exception("was not found"))
    res = _run(ensure_connected(dev, attempts=3, sleep=_nosleep))
    assert res.ok is False
    assert res.state is ConnectionState.FAILED
    assert res.reason is FailureReason.NOT_ADVERTISING
    assert res.message  # actionable text present
    assert dev.is_connected is False        # NOT a live-looking dead handle
    assert dev.connect_calls == 3


def test_corebluetooth_lie_is_treated_as_failure():
    # connect() "succeeds" but is_connected stays False (the macOS race)
    dev = FakeBleDevice(connect_results=[False, False, False])
    res = _run(ensure_connected(dev, attempts=3, sleep=_nosleep))
    assert res.ok is False
    assert dev.connect_calls == 3
    assert dev.is_connected is False


def test_verify_failure_retries():
    dev = FakeBleDevice()
    calls = {"n": 0}

    async def verify(_):
        calls["n"] += 1
        return calls["n"] >= 2   # first verify fails, second passes

    res = _run(ensure_connected(dev, attempts=3, verify=verify, sleep=_nosleep))
    assert res.ok and calls["n"] == 2 and dev.connect_calls == 2


def test_tears_down_half_open_handle_between_attempts():
    dev = FakeBleDevice(connect_results=[Exception("disconnected"), True])
    _run(ensure_connected(dev, attempts=2, sleep=_nosleep))
    assert dev.disconnect_calls >= 1   # cleaned up before the retry
