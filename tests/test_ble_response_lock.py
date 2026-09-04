"""R53.11: the BLE response path is serialized by a lock.

`send_command_and_wait_for_response` mutates shared state — it drains the
notification_queue and sets the scalar `_expected_response_command`, then waits.
Two concurrent callers would drain each other's frames and clobber the scalar
(cross-talk). Today the command queue serializes device ops so it's uncontended,
but nothing ENFORCED that; `_response_lock` makes the invariant explicit so a
future off-queue caller can't silently corrupt an in-flight wait.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.ble_notify import BleNotifyMixin


class _T(BleNotifyMixin):
    """Minimal host for the mixin: a real lock + queue, a stub send_command that
    simulates the device replying with a frame matching the expected scalar."""
    def __init__(self):
        self.logger = logging.getLogger("test_response_lock")
        self.notification_queue = asyncio.Queue()
        self._expected_response_command = None
        self._response_lock = asyncio.Lock()
        self.use_ios_le_protocol = True
        self.is_connected = True
        self.lock_states = []

    async def send_command(self, command, args=None, write_with_response=False):
        # the lock must be held while we send + wait
        self.lock_states.append(self._response_lock.locked())
        # device replies with the frame the caller is waiting for
        self.notification_queue.put_nowait(
            {"command_id": self._expected_response_command, "payload": bytes([command & 0xFF])})
        return True


def test_lock_held_across_send_and_wait():
    t = _T()
    r = asyncio.run(t.send_command_and_wait_for_response(0x44, timeout=1.0))
    assert r == b"\x44"
    assert t.lock_states == [True]      # lock was held during send+wait


def test_concurrent_waits_serialize_without_crosstalk():
    """Two overlapping waits must each get THEIR OWN response. Without the lock the
    second caller's queue-drain would eat the first's reply (→ timeout)."""
    t = _T()

    async def main():
        return await asyncio.gather(
            t.send_command_and_wait_for_response(0x10, timeout=1.0),
            t.send_command_and_wait_for_response(0x20, timeout=1.0),
        )

    a, b = asyncio.run(main())
    assert a == b"\x10" and b == b"\x20"   # no cross-talk; each its own payload


def test_not_connected_returns_none_without_touching_lock():
    t = _T()
    t.is_connected = False
    r = asyncio.run(t.send_command_and_wait_for_response(0x44, timeout=1.0))
    assert r is None
    assert t._response_lock.locked() is False
