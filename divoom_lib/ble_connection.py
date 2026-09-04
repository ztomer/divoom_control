"""BLE Hardening Phase 1 — honest connect/reconnect.

A typed connection result + a retrying ``ensure_connected`` helper so the rest
of the stack stops returning dead device handles and starts surfacing
ACTIONABLE reasons (device asleep, BT off, held by the phone app, …) instead of
a bare "timed out".

The helper operates on any object with an async ``connect()`` and an
``is_connected`` property (the real ``Divoom``/transport, or the fake in
``tests/support/fake_ble.py``), so every path is unit-testable without hardware.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("divoom_lib.ble_connection")


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"      # connected but a write/verify just failed
    FAILED = "failed"


class FailureReason(str, Enum):
    NONE = "none"
    NOT_ADVERTISING = "not_advertising"   # asleep / out of range / not found
    TIMEOUT = "timeout"
    DROPPED = "dropped"                    # connected then lost / GATT race
    PERMISSION = "permission"              # TCC / not authorized
    ADAPTER_OFF = "adapter_off"            # Bluetooth powered off
    BUSY = "busy"                          # likely held by another central (phone)
    UNKNOWN = "unknown"


# Human-actionable messages keyed by reason (shown in the GUI / menubar).
REASON_MESSAGE = {
    FailureReason.NOT_ADVERTISING:
        "Device not found — wake it (press a button) or move it closer, then retry.",
    FailureReason.TIMEOUT:
        "Connection timed out — the device may be asleep or busy. Retry in a moment.",
    FailureReason.DROPPED:
        "The Bluetooth link dropped during connect. Retrying usually fixes it.",
    FailureReason.PERMISSION:
        "Bluetooth permission is missing — grant it to this app and restart.",
    FailureReason.ADAPTER_OFF:
        "Bluetooth is turned off — enable it and retry.",
    FailureReason.BUSY:
        "The device looks connected to another app (e.g. the Divoom phone app). "
        "Disconnect it there, then retry.",
    FailureReason.UNKNOWN: "Could not connect to the device.",
    FailureReason.NONE: "",
}


class BleConnectionError(RuntimeError):
    """Raised when a connect/reconnect genuinely fails, carrying the typed
    ConnectResult so callers can surface an actionable reason."""
    def __init__(self, result: "ConnectResult"):
        super().__init__(result.message or result.detail or "connect failed")
        self.result = result


@dataclass
class ConnectResult:
    ok: bool
    state: ConnectionState
    reason: FailureReason = FailureReason.NONE
    detail: str = ""           # the raw exception text, for logs

    @property
    def message(self) -> str:
        return REASON_MESSAGE.get(self.reason, REASON_MESSAGE[FailureReason.UNKNOWN])


def derive_connection_state(active) -> ConnectionState:
    """BLE Hardening P6: map a device/wall's HONEST liveness to one
    ConnectionState for the UI dot. DEGRADED = reports connected but a write/
    drop just failed (``is_alive`` False) — surfaced instead of a misleading
    solid 'connected'. ``active`` is the owned device, wall, or None."""
    if active is None or not getattr(active, "is_connected", False):
        return ConnectionState.DISCONNECTED
    if getattr(active, "is_alive", True):
        return ConnectionState.CONNECTED
    return ConnectionState.DEGRADED


def classify_connect_error(exc: BaseException) -> FailureReason:
    """Map a connect/verify exception to a typed, actionable reason."""
    if isinstance(exc, asyncio.TimeoutError):
        return FailureReason.TIMEOUT
    text = str(exc).lower()
    if "was not found" in text or "not found" in text or "no device" in text:
        return FailureReason.NOT_ADVERTISING
    if "timed out" in text or "timeout" in text:
        return FailureReason.TIMEOUT
    if "powered off" in text or "is off" in text or "turn on bluetooth" in text:
        return FailureReason.ADAPTER_OFF
    if "not authorized" in text or "unauthorized" in text or "permission" in text \
            or "denied" in text:
        return FailureReason.PERMISSION
    if "already" in text and "connect" in text:
        return FailureReason.BUSY
    if "disconnect" in text or "not connected" in text or "gatt" in text:
        return FailureReason.DROPPED
    return FailureReason.UNKNOWN


# Tunables (overridable per call; defaults are sane for Divoom BLE).
DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.4       # seconds; grows 0.4, 0.8, 1.6 …
DEFAULT_MAX_DELAY = 4.0
DEFAULT_ATTEMPT_TIMEOUT = 12.0  # per-attempt connect timeout
WALL_CONNECT_CONCURRENCY = 2    # P3: how many wall slots may connect at once


# BLE Hardening P3 — serialize the *connect* handshake. The CoreBluetooth
# central is fragile under a connect-storm (wall = N devices + per-device live
# jobs all calling connect() at once), so the actual handshake is funnelled
# through a single lock while backoff waits / writes still overlap freely.
# Lazily per running loop so the daemon's device loop and each test's fresh
# loop get their own lock (an import-time asyncio.Lock would bind to the first
# loop that awaited it and then raise "bound to a different event loop").
_connect_locks: "dict[int, asyncio.Lock]" = {}


def _connect_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _connect_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _connect_locks[id(loop)] = lock
    return lock


def forget_loop(loop) -> None:
    """Drop the per-loop connect lock when a device loop is torn down. The dict is
    keyed by id(loop); CPython REUSES ids, so without this a fresh loop could be
    handed a stale Lock bound to the dead loop → "bound to a different event loop"."""
    if loop is not None:
        _connect_locks.pop(id(loop), None)


async def ensure_connected(
    device,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
    verify=None,
    sleep=asyncio.sleep,
) -> ConnectResult:
    """Connect ``device`` with bounded retries + backoff + jitter, verifying the
    link before declaring success. NEVER leaves the caller with a dead handle:
    on success the device is genuinely connected; on failure the result carries
    a typed, actionable ``reason`` and the device is left disconnected.

    ``verify`` is an optional async callable run after connect to prove the link
    works (a cheap round-trip); raising or returning False marks the attempt
    failed. ``sleep`` is injectable so tests don't actually wait.
    """
    # R53: trust the HONEST liveness signal, not the cached is_connected. After an
    # OS-level drop CoreBluetooth's is_connected lags True, but is_alive reflects
    # the disconnect-callback flag — so this fast-path no longer hands back a dead
    # handle. is_alive falls back to is_connected on transports that don't track it.
    if getattr(device, "is_alive", getattr(device, "is_connected", False)):
        return ConnectResult(True, ConnectionState.CONNECTED)

    last = FailureReason.UNKNOWN
    detail = ""
    for attempt in range(attempts):
        try:
            # P3: only the fragile handshake is serialized; verify + backoff
            # run outside the lock so other devices aren't blocked by our waits.
            async with _connect_lock():
                await asyncio.wait_for(device.connect(), timeout=attempt_timeout)
            if not getattr(device, "is_connected", False):
                # The OS lied (CoreBluetooth race) — treat as a drop and retry.
                raise ConnectionError("connect returned but is_connected is False")
            if verify is not None:
                ok = await verify(device)
                if ok is False:
                    raise ConnectionError("post-connect verify failed")
            return ConnectResult(True, ConnectionState.CONNECTED)
        except BaseException as e:  # noqa: BLE001 — classify everything
            # asyncio.CancelledError is a BaseException (not Exception) since 3.8.
            # Swallowing it here treated a cancellation (daemon teardown cancelling
            # the device-loop worker, or a wait_for timeout) as an ordinary connect
            # failure → the retry loop kept running, defeating cooperative
            # cancellation and delaying stop() by wasted connect attempts. Re-raise.
            if isinstance(e, asyncio.CancelledError):
                raise
            last = classify_connect_error(e)
            detail = str(e)
            logger.warning("connect attempt %d/%d failed: %s (%s)",
                           attempt + 1, attempts, last.value, detail)
            # A wedged half-open handle must be torn down before the next try.
            try:
                if hasattr(device, "disconnect"):
                    await device.disconnect()
            except Exception:
                pass
            if attempt < attempts - 1:
                delay = min(max_delay, base_delay * (2 ** attempt))
                delay += random.uniform(0, delay * 0.25)  # jitter
                await sleep(delay)

    return ConnectResult(False, ConnectionState.FAILED, reason=last, detail=detail)


async def connect_devices(
    items,
    *,
    concurrency: int = WALL_CONNECT_CONCURRENCY,
    **kw,
) -> "dict[object, ConnectResult]":
    """BLE Hardening P3: connect many devices with BOUNDED concurrency, returning
    a ``{key: ConnectResult}`` map so a partial wall reports WHICH slot failed and
    why (instead of a bare ``gather`` connect-storm that fails opaquely). ``items``
    is an iterable of ``(key, device)``. The semaphore bounds how many
    ``ensure_connected`` coroutines run at once; the global connect lock inside
    ``ensure_connected`` still serializes the actual handshakes underneath."""
    sem = asyncio.Semaphore(max(1, concurrency))
    results: "dict[object, ConnectResult]" = {}

    async def _one(key, dev):
        async with sem:
            results[key] = await ensure_connected(dev, **kw)

    await asyncio.gather(*(_one(k, d) for k, d in items))
    return results
