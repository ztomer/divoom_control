"""R53.34: DivoomConnection (the transport router) is the single live-path entry
for send_command_and_wait_for_response — it shadows the transport's own
lock-protected version, so the R53.11 cross-talk lock was effectively bypassed.
The router must serialize its own drain→set-scalar→send→wait sequence so two
concurrent waiters on one device can't clobber each other's
_expected_response_command.

Teeth: drop the `async with self._response_lock` in
connection.py:send_command_and_wait_for_response and the two coroutines
interleave — one sees the other's command id in the scalar → assertion fails.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import divoom_lib.divoom  # noqa: F401  - import first to resolve the import cycle
from divoom_lib.connection import DivoomConnection


class _FakeTransport:
    def __init__(self):
        self.notification_queue = asyncio.Queue()
        self._expected_response_command = None


class _FakeDivoom:
    def __init__(self):
        self.conn = None
        self.observed = []

    async def send_command(self, command, args, write_with_response=False):
        # Widen the window so a second, unserialized caller would interleave here.
        await asyncio.sleep(0.02)

    async def _wait_for_response(self, command_id, timeout):
        await asyncio.sleep(0.01)
        # The scalar must STILL be ours; if a concurrent call clobbered it while
        # we were mid-flight, this captures the mismatch.
        self.observed.append((command_id, self.conn._expected_response_command))
        return command_id


def _make_conn():
    conn = object.__new__(DivoomConnection)
    conn.logger = logging.getLogger("test_router_lock")
    conn._use_spp = False
    conn._response_lock = asyncio.Lock()
    conn._active_transport = _FakeTransport()
    divoom = _FakeDivoom()
    divoom.conn = conn
    conn._divoom = divoom
    return conn, divoom


def test_concurrent_waiters_do_not_clobber_expected_command():
    async def run():
        conn, divoom = _make_conn()
        results = await asyncio.gather(
            conn.send_command_and_wait_for_response(0xAA, [], timeout=5.0),
            conn.send_command_and_wait_for_response(0xBB, [], timeout=5.0),
        )
        return results, divoom.observed

    results, observed = asyncio.run(run())

    assert sorted(results) == [0xAA, 0xBB]
    # Each call must have seen ITS OWN command id in the scalar at wait time.
    for cid, scalar_at_wait in observed:
        assert cid == scalar_at_wait, (
            f"cross-talk: command 0x{cid:02x} saw _expected_response_command="
            f"{scalar_at_wait!r} — a concurrent call clobbered the scalar"
        )
