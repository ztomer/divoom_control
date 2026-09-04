"""R53.13: SPP send retries + RX parser can't be stalled by a corrupt length.

Two deferred SPP findings:
- `send_payload(max_retries=N)` accepted the arg but never retried — a single
  transient write failure failed the whole op.
- `_on_data` trusted the iOS-LE length field (bytes 4-5). A corrupt length made it
  wait FOREVER for bytes that never arrive, stalling all RX behind it.
"""
import asyncio
import logging
import queue
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import models
from divoom_lib.bt_spp_transport import BTSppTransport


class _FakePort:
    def __init__(self, is_open=True):
        self.is_open = is_open


def _t():
    return BTSppTransport("AA:BB:CC:DD:EE:FF", logger=logging.getLogger("spp_rob"))


# ── send_payload retries ────────────────────────────────────────────────────

def test_send_payload_retries_then_succeeds():
    t = _t()
    t._serial_port = _FakePort(is_open=True)        # is_connected → True
    calls = {"n": 0}

    async def flaky(payload, framing=None, packet_number=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("EAGAIN")

    t.send = flaky
    assert asyncio.run(t.send_payload([0x44], max_retries=3)) is True
    assert calls["n"] == 3                            # retried until it stuck


def test_send_payload_gives_up_after_max_retries():
    t = _t()
    t._serial_port = _FakePort(is_open=True)
    calls = {"n": 0}

    async def always_fail(payload, framing=None, packet_number=0):
        calls["n"] += 1
        raise OSError("dead")

    t.send = always_fail
    assert asyncio.run(t.send_payload([0x44], max_retries=2)) is False
    assert calls["n"] == 2                            # exactly max_retries attempts


def test_send_payload_bails_immediately_when_disconnected():
    t = _t()                                          # no port/channel → not connected
    calls = {"n": 0}

    async def fail(payload, framing=None, packet_number=0):
        calls["n"] += 1
        raise OSError("x")

    t.send = fail
    assert asyncio.run(t.send_payload([0x44], max_retries=5)) is False
    assert calls["n"] == 1                            # no point retrying a dead link


# ── RX parser resync on corrupt length ──────────────────────────────────────

def test_on_data_does_not_stall_on_corrupt_length():
    t = _t()
    t._rx_buf = bytearray()
    t._rx_queue = queue.Queue()
    hdr = bytes(models.IOS_LE_HEADER)
    # length 0xFFFF → frame_len 65542, far over the bound; only a few bytes follow
    corrupt = hdr + b"\xff\xff" + b"\x00" * 8
    t._on_data(corrupt)
    # the stalled state is "a full iOS-LE header sitting at the front waiting for
    # 65k bytes" — the resync must have dropped past it.
    stalled = len(t._rx_buf) >= 4 and bytes(t._rx_buf[:4]) == hdr
    assert not stalled


def test_on_data_recovers_real_frame_after_corrupt_prefix():
    """After resyncing past a corrupt-length header, a following valid basic-protocol
    frame must still be delivered (RX not wedged)."""
    t = _t()
    t._rx_buf = bytearray()
    t._rx_queue = queue.Queue()
    from divoom_lib.framing import encode_basic_payload
    good = encode_basic_payload([0x44, 0x01])
    # a bogus iOS-LE header with an absurd length, then a real basic frame
    t._on_data(bytes(models.IOS_LE_HEADER) + b"\xff\xff" + bytes(good))
    got = []
    while not t._rx_queue.empty():
        got.append(t._rx_queue.get_nowait())
    assert any(n.command_id == 0x44 for n in got), "real frame lost after corrupt prefix"
