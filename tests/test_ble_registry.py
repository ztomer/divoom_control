"""BLE connection registry — one live connection per address (R45 #6).

CoreBluetooth allows one connection per peripheral per central, so a MAC used
standalone and as a wall slot must not be double-connected. The registry evicts
the prior in-process owner before a new connect to the same address.
"""
import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import ble_registry


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _T:
    """A minimal transport stand-in: an address + async disconnect()."""
    def __init__(self, mac="AA:BB:CC"):
        self.mac = mac
        self.disconnects = 0

    async def disconnect(self):
        self.disconnects += 1
        ble_registry.unregister(self.mac, self)   # mirror the real transport


def setup_function(_):
    ble_registry._reset()


def test_register_and_owner_case_insensitive():
    t = _T("aa:bb")
    ble_registry.register("aa:bb", t)
    assert ble_registry.owner("AA:BB") is t      # normalized to upper


def test_evict_disconnects_and_drops_prior_owner():
    old, new = _T("AA"), _T("AA")
    ble_registry.register("AA", old)
    _run(ble_registry.evict("AA", new))
    assert old.disconnects == 1
    assert ble_registry.owner("AA") is None       # evicted, registry cleared


def test_evict_noop_when_keep_is_current_owner():
    t = _T("AA")
    ble_registry.register("AA", t)
    _run(ble_registry.evict("AA", t))
    assert t.disconnects == 0 and ble_registry.owner("AA") is t


def test_evict_noop_when_nothing_registered():
    _run(ble_registry.evict("AA", _T("AA")))      # must not raise


def test_unregister_only_drops_the_current_owner():
    t1, t2 = _T("AA"), _T("AA")
    ble_registry.register("AA", t1)
    ble_registry.unregister("AA", t2)             # t2 isn't the owner — no-op
    assert ble_registry.owner("AA") is t1
    ble_registry.unregister("AA", t1)
    assert ble_registry.owner("AA") is None


def test_evict_swallows_disconnect_errors():
    class _Bad:
        mac = "AA"
        async def disconnect(self):
            raise RuntimeError("BLE gone")
    bad = _Bad()
    ble_registry.register("AA", bad)
    _run(ble_registry.evict("AA", _T("AA")))      # error logged, not raised
    assert ble_registry.owner("AA") is None        # still dropped


def test_blank_address_is_ignored():
    t = _T(None)
    ble_registry.register(None, t)
    assert ble_registry.owner(None) is None
    _run(ble_registry.evict(None, t))              # no-op, no raise


def test_failed_eviction_warns(caplog):
    """R53.14: a disconnect failure during eviction must be a WARNING (the OS link
    may survive and stall the next connect), not a silent debug."""
    import logging

    class _Bad:
        mac = "AA"
        async def disconnect(self):
            raise RuntimeError("BLE gone")
    ble_registry.register("AA", _Bad())
    with caplog.at_level(logging.WARNING, logger="divoom_lib.ble_registry"):
        _run(ble_registry.evict("AA", _T("AA")))
    assert any("FAILED" in r.message for r in caplog.records)
    assert ble_registry.owner("AA") is None        # still dropped (best-effort)


def test_reset_clears_all_entries():
    """R53.14: device-loop teardown drops ALL registered transports (they were
    bound to the dying loop)."""
    ble_registry.register("AA", _T("AA"))
    ble_registry.register("BB", _T("BB"))
    ble_registry.reset()
    assert ble_registry.owner("AA") is None and ble_registry.owner("BB") is None


def test_forget_loop_drops_per_loop_connect_lock():
    """R53.14: forget_loop pops the id(loop)-keyed lock so a reused id can't hand a
    fresh loop a Lock bound to the dead loop."""
    from divoom_lib import ble_connection

    async def _make_lock():
        return ble_connection._connect_lock()       # creates + registers for this loop

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_make_lock())
        assert id(loop) in ble_connection._connect_locks
        ble_connection.forget_loop(loop)
        assert id(loop) not in ble_connection._connect_locks
    finally:
        loop.close()
    ble_connection.forget_loop(None)                 # tolerates None
