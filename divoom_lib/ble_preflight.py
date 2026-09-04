"""BLE Hardening Phase 4 — adapter / permission preflight.

Before a scan or connect, answer the question an empty scan / failed connect
can't: *why*. macOS CoreBluetooth exposes two orthogonal facts —

  * ``CBCentralManager.authorization()`` — has the user granted Bluetooth to
    THIS process? (synchronous class method, always reliable)
  * the central's ``state`` (``CBManagerState``) — is the adapter actually
    powered on? (delegate-driven; needs a brief run-loop pump to settle)

— and we map them to the SAME typed ``FailureReason`` the connect path uses, so
the GUI/menubar can say "Bluetooth is off" or "grant Bluetooth permission"
instead of silently returning zero devices (weakness W10).

Design: best-effort and NON-blocking. The readers are injectable so the logic
is unit-tested without CoreBluetooth, and any inability to read the state (not
macOS, PyObjC missing, adapter state never settles) returns ``ok`` rather than
blocking a scan that might have worked.
"""
from __future__ import annotations

import logging

from .ble_connection import ConnectResult, ConnectionState, FailureReason

logger = logging.getLogger("divoom_lib.ble_preflight")

# CBManagerAuthorization (the process's TCC grant for Bluetooth):
#   0 notDetermined · 1 restricted · 2 denied · 3 allowed
AUTH_NOT_DETERMINED = 0
AUTH_RESTRICTED = 1
AUTH_DENIED = 2
AUTH_ALLOWED = 3

# CBManagerState (the adapter's power/availability):
#   0 unknown · 1 resetting · 2 unsupported · 3 unauthorized · 4 poweredOff · 5 poweredOn
STATE_UNKNOWN = 0
STATE_RESETTING = 1
STATE_UNSUPPORTED = 2
STATE_UNAUTHORIZED = 3
STATE_POWERED_OFF = 4
STATE_POWERED_ON = 5


def _read_authorization() -> int:
    """The process's Bluetooth TCC grant (CBManagerAuthorization). Raises if
    CoreBluetooth isn't available (non-macOS) — the caller treats that as
    'can't check, don't block'."""
    from CoreBluetooth import CBCentralManager
    return int(CBCentralManager.authorization())


def _read_power_state(timeout: float = 0.6) -> int | None:
    """The adapter's CBManagerState, pumping the run loop briefly so the
    delegate-driven ``state`` settles past UNKNOWN. Returns ``None`` if it never
    settles (so the caller doesn't block on an indeterminate reading).

    WARNING — OPT-IN ONLY, NOT the default power reader. Creating a CBCentralManager
    and pumping NSRunLoop is unsafe off the main thread (the daemon dispatches
    command handlers on socket-accept worker threads, where this crashes
    libdispatch). Only call this from a process that owns a main run loop (e.g.
    the GUI). The daemon relies on the connect path's typed ADAPTER_OFF reason
    (``classify_connect_error`` maps bleak's "powered off") for the radio-off
    case instead."""
    from CoreBluetooth import CBCentralManager
    from Foundation import NSRunLoop, NSDate, NSDefaultRunLoopMode

    mgr = CBCentralManager.alloc().initWithDelegate_queue_(None, None)
    deadline = NSDate.dateWithTimeIntervalSinceNow_(timeout)
    state = int(mgr.state())
    while state == STATE_UNKNOWN and NSDate.date().compare_(deadline) < 0:
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.05))
        state = int(mgr.state())
    return state if state != STATE_UNKNOWN else None


def _no_power_probe(**_kw) -> int | None:
    """Default power reader: a SAFE no-op. The live CBManagerState probe
    (:func:`_read_power_state`) crashes off the main thread, so the default
    preflight does only the synchronous, thread-safe ``authorization()`` check;
    radio-off is caught by the connect path's typed reason. Callers on the main
    thread may pass ``read_power=_read_power_state`` to opt in."""
    return None


def preflight_bluetooth(*, read_auth=_read_authorization,
                        read_power=_no_power_probe) -> ConnectResult:
    """Return an ``ok`` ConnectResult when Bluetooth is usable, or a typed
    ``PERMISSION`` / ``ADAPTER_OFF`` reason (with an actionable ``message``)
    when it definitively isn't. Indeterminate / unreadable → ``ok`` (never block
    a scan that might work).

    The default does only the synchronous ``authorization()`` check (safe on any
    thread). Pass ``read_power=_read_power_state`` from a main-thread/GUI caller
    to additionally diagnose a powered-off adapter."""
    try:
        auth = read_auth()
    except Exception as e:  # not macOS / PyObjC missing — can't check, proceed.
        logger.debug("preflight: authorization unreadable (%s); proceeding", e)
        return ConnectResult(True, ConnectionState.CONNECTED)

    if auth in (AUTH_DENIED, AUTH_RESTRICTED):
        logger.warning("preflight: Bluetooth permission denied (auth=%s)", auth)
        return ConnectResult(False, ConnectionState.FAILED,
                             reason=FailureReason.PERMISSION,
                             detail=f"CBManagerAuthorization={auth}")

    # auth is allowed or not-yet-determined (a scan will prompt) — check power.
    try:
        power = read_power()
    except Exception as e:
        logger.debug("preflight: power state unreadable (%s); proceeding", e)
        return ConnectResult(True, ConnectionState.CONNECTED)

    if power == STATE_POWERED_OFF:
        logger.warning("preflight: Bluetooth adapter is powered off")
        return ConnectResult(False, ConnectionState.FAILED,
                             reason=FailureReason.ADAPTER_OFF,
                             detail="CBManagerState=poweredOff")
    if power == STATE_UNSUPPORTED:
        return ConnectResult(False, ConnectionState.FAILED,
                             reason=FailureReason.ADAPTER_OFF,
                             detail="CBManagerState=unsupported")
    if power == STATE_UNAUTHORIZED:
        return ConnectResult(False, ConnectionState.FAILED,
                             reason=FailureReason.PERMISSION,
                             detail="CBManagerState=unauthorized")

    # poweredOn, resetting, or indeterminate (None) → don't block.
    return ConnectResult(True, ConnectionState.CONNECTED)
