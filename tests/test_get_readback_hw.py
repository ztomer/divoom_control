"""get_* read-back correctness (task #20, HW-confirmed on 4 models).

Two real bugs the hardware probe exposed:
  1. manual read-back methods (get_brightness, get_light_mode) skipped the
     queue drain, so an UNSOLICITED frame the device emits on state change was
     consumed instead of the query's own response — reads lagged one step
     behind (set 60 → read 25). Fixed by draining first.
  2. the 0x76 "get name" query returns a 2-char suffix ("-2"), not the full
     advertised name, on every tested model — so get_device_name now prefers
     the authoritative advertised name the lib already holds.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.system.device import Device


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeComm:
    def __init__(self, *, device_name="", fresh_brightness=None,
                 stale_brightness=None, name_frame=None):
        self.logger = logging.getLogger("fakecomm")
        self.use_ios_le_protocol = True
        self.device_name = device_name
        self.notification_queue = asyncio.Queue()
        self._expected_response_command = None
        self.events = []
        self._fresh = fresh_brightness
        self._name_frame = name_frame
        if stale_brightness is not None:
            # an unsolicited 0x46 already sitting in the queue (byte[6]=brightness)
            self.notification_queue.put_nowait(
                {"command_id": 0x46, "payload": bytes([0] * 6 + [stale_brightness])})

    def drain_notifications(self):
        self.events.append("drain")
        n = 0
        while not self.notification_queue.empty():
            self.notification_queue.get_nowait()
            n += 1
        return n

    @asynccontextmanager
    async def _framing_context(self, **k):
        yield

    async def send_command(self, *a, **k):
        self.events.append("send")
        if self._fresh is not None:
            self.notification_queue.put_nowait(
                {"command_id": 0x46, "payload": bytes([0] * 6 + [self._fresh])})
        return True

    async def wait_for_response(self, cmd, timeout=3.0):
        try:
            return self.notification_queue.get_nowait()["payload"]
        except asyncio.QueueEmpty:
            return None

    async def send_command_and_wait_for_response(self, *a, **k):
        return self._name_frame


# ── bug 1: stale-read / queue drain ────────────────────────────────────────

def test_get_brightness_drains_stale_frame_before_reading():
    # queue holds a stale 0x46 (brightness 11); the fresh read is 55.
    comm = _FakeComm(stale_brightness=11, fresh_brightness=55)
    dev = Device(comm)
    val = _run(dev.get_brightness())
    assert val == 55, "must read the fresh response, not the stale queued frame"
    # drained before sending the query
    assert comm.events[0] == "drain"
    assert comm.events.index("drain") < comm.events.index("send")


def test_get_brightness_without_stale_still_reads_fresh():
    comm = _FakeComm(fresh_brightness=42)
    assert _run(Device(comm).get_brightness()) == 42


def test_divoom_drain_notifications_empties_queue():
    from divoom_lib.divoom import Divoom

    class _Conn:
        def __init__(self):
            self.notification_queue = asyncio.Queue()

    d = Divoom.__new__(Divoom)
    d._conn = _Conn()
    d._conn.notification_queue.put_nowait("a")
    d._conn.notification_queue.put_nowait("b")
    assert d.drain_notifications() == 2
    assert d._conn.notification_queue.empty()
    assert d.drain_notifications() == 0      # idempotent on an empty queue


# ── bug 2: device name prefers the advertised name ─────────────────────────

def test_get_device_name_prefers_advertised_name():
    # 0x76 would reply with garbage; the lib already knows the real name.
    comm = _FakeComm(device_name="Ditoo-light-2", name_frame=bytes([2, 0x2d, 0x32]))
    dev = Device(comm)
    assert _run(dev.get_device_name()) == "Ditoo-light-2"
    assert "send" not in comm.events      # never issued the unreliable 0x76


def test_get_device_name_falls_back_to_0x76_when_unknown():
    # connected by bare MAC (no advertised name) → use the 0x76 read.
    name = "Xy"
    frame = bytes([len(name)]) + name.encode()
    comm = _FakeComm(device_name="", name_frame=frame)
    assert _run(Device(comm).get_device_name()) == "Xy"


def test_get_device_name_blank_advertised_falls_back():
    comm = _FakeComm(device_name="   ", name_frame=bytes([1, 0x5a]))
    assert _run(Device(comm).get_device_name()) == "Z"
