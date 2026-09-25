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


# ── send_payload retries: GONE with the method ─────────────────────────────
#
# These three tests covered the retry loop inside `send_payload`, which could
# not survive the L4 framing move: retrying a write means calling it again, and
# a caller that re-frames on each attempt needs a Python encoder — the exact
# second implementation the move deleted. So the tests went with the method.
#
# Worth stating plainly, because "deleted" reads like "lost": the LIVE SPP path
# never had this retry. The bridge called `transport.send(...)` directly, which
# retried nothing, and it calls `send_frame` now, which retries nothing. If a
# retry is wanted on a Bluetooth write it belongs on the path that is actually
# used — `send_frame`, or the daemon's send above it — and it should be a
# deliberate change with its own evidence, not a resurrection of a loop whose
# only callers were dead.


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
