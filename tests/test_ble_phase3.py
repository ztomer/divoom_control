"""BLE Hardening Phase 3 — concurrency safety + wall self-heal.

The fragile connect handshake is serialized so a wall (N devices) + per-device
live jobs don't connect-storm CoreBluetooth; the wall reports per-slot typed
results (which screen failed and why) and self-heals a dropped slot before
pushing instead of freezing its content.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import ble_connection
from divoom_lib.ble_connection import (
    connect_devices, ensure_connected, FailureReason,
)
from tests.support.fake_ble import FakeBleDevice


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── connect serialization ──────────────────────────────────────────────────

def test_connect_handshake_is_serialized_across_devices():
    """Two devices connecting at once must never overlap inside the handshake —
    the per-loop connect lock funnels them one at a time."""
    overlap = {"now": 0, "max": 0}

    class _Tracking(FakeBleDevice):
        async def connect(self):
            overlap["now"] += 1
            overlap["max"] = max(overlap["max"], overlap["now"])
            await asyncio.sleep(0.02)          # hold the "handshake" open
            overlap["now"] -= 1
            await super().connect()

    async def _drive():
        devs = [_Tracking(), _Tracking(), _Tracking()]
        await asyncio.gather(*(ensure_connected(d) for d in devs))
        return devs

    devs = _run(_drive())
    assert overlap["max"] == 1                  # never two handshakes at once
    assert all(d.is_connected for d in devs)


def test_connect_lock_is_per_loop_not_cross_loop_bound():
    """A fresh event loop gets its own lock (no 'bound to a different loop')."""
    _run(ensure_connected(FakeBleDevice()))
    _run(ensure_connected(FakeBleDevice()))     # would raise if the lock leaked
    assert len(ble_connection._connect_locks) >= 1


# ── bounded-concurrency multi-connect with per-key typed results ────────────

def test_connect_devices_returns_per_key_results():
    good = FakeBleDevice()
    bad = FakeBleDevice(raise_on_connect=Exception("was not found"))
    res = _run(connect_devices([("a", good), ("b", bad)], attempts=1))
    assert res["a"].ok is True
    assert res["b"].ok is False
    assert res["b"].reason is FailureReason.NOT_ADVERTISING


def test_connect_devices_bounds_concurrency():
    inflight = {"now": 0, "max": 0}

    class _Tracking(FakeBleDevice):
        async def connect(self):
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
            await asyncio.sleep(0.01)
            inflight["now"] -= 1
            await super().connect()

    items = [(i, _Tracking()) for i in range(6)]
    # The connect lock already serializes the handshake to 1, so to observe the
    # SEMAPHORE bound we count coroutines admitted past it via a no-op verify
    # that holds the slot. Simpler: assert the helper never admits more than the
    # configured concurrency by tracking sem-guarded section via verify.
    seen = {"now": 0, "max": 0}

    async def _verify(dev):
        seen["now"] += 1
        seen["max"] = max(seen["max"], seen["now"])
        await asyncio.sleep(0.01)
        seen["now"] -= 1
        return True

    _run(connect_devices(items, concurrency=2, attempts=1, verify=_verify))
    assert seen["max"] <= 2


# ── wall: per-slot results + partial-ok + total-failure reason ──────────────

def _make_wall(devices):
    """Build a DivoomWall but swap its real Divooms for fakes (no BLE)."""
    from divoom_lib.wall import DivoomWall
    from divoom_lib.models import DeviceSlot
    configs = [{"mac": f"AA:{i}", "x": i, "y": 0, "size": 16} for i in range(len(devices))]
    wall = DivoomWall(configs)
    wall.devices = []
    for i, dev in enumerate(devices):
        dev.mac = f"AA:{i}"
        wall.devices.append(DeviceSlot(device=dev, x=i, y=0, size=16))
    return wall


def test_wall_connect_reports_which_slot_failed():
    good = FakeBleDevice()
    bad = FakeBleDevice(raise_on_connect=Exception("was not found"))
    wall = _make_wall([good, bad])
    results = _run(wall.connect())
    assert results["AA:0"].ok is True
    assert results["AA:1"].ok is False
    assert results["AA:1"].reason is FailureReason.NOT_ADVERTISING
    # Partial wall stays usable for the screen that came up.
    assert wall.connect_results["AA:0"].ok is True


def test_wall_connect_raises_only_on_total_failure():
    from divoom_lib.ble_connection import BleConnectionError
    a = FakeBleDevice(raise_on_connect=Exception("bluetooth is off"))
    b = FakeBleDevice(raise_on_connect=Exception("bluetooth is off"))
    wall = _make_wall([a, b])
    with pytest.raises(BleConnectionError):
        _run(wall.connect())


# ── wall: show_image self-heals a dropped slot before pushing ───────────────

class _PushDevice(FakeBleDevice):
    """A fake slot with a .display.show_image that records pushes."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pushes = 0
        outer = self

        class _Display:
            async def show_image(self, path, time=None):
                outer.pushes += 1
                return True
        self.display = _Display()


def test_wall_show_image_reconnects_dropped_slot(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    from PIL import Image
    Image.new("RGB", (16, 16), (10, 20, 30)).save(img)

    alive = _PushDevice()
    _run(alive.connect())
    dropped = _PushDevice()
    _run(dropped.connect())
    dropped.drop()                      # OS-level drop → is_alive False

    wall = _make_wall([alive, dropped])
    ok = _run(wall.show_image(str(img)))
    assert ok is True
    assert dropped.is_alive             # self-healed
    assert dropped.connect_calls == 2   # reconnected before pushing
    assert alive.pushes == 1 and dropped.pushes == 1


def test_wall_show_image_reports_unrecoverable_slot(tmp_path):
    img = tmp_path / "x.png"
    from PIL import Image
    Image.new("RGB", (16, 16), (10, 20, 30)).save(img)

    alive = _PushDevice()
    _run(alive.connect())
    dead = _PushDevice(connect_results=[True])
    _run(dead.connect())
    dead.drop()
    dead._raise = Exception("was not found")   # can't be revived

    wall = _make_wall([alive, dead])
    ok = _run(wall.show_image(str(img)))
    assert ok is False                  # partial — one slot couldn't be revived
    assert alive.pushes == 1            # the healthy slot still updated
    assert dead.pushes == 0
