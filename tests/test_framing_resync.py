"""P1.7: a spurious start byte must not swallow the real frames behind it.

`parse_basic_protocol_frames` resyncs one byte at a time when a candidate frame
fails validation, so a stray `0x01` whose fake length covers genuine frames
behind it is stepped over rather than consumed. The June 2026 adversarial
review flagged this in the Python era ("low, self-healing"); the Rust port and
this reference kept the same shape, so both were fixed in one commit. The
shared vector in `divoomd/tests/framing_vectors.json` and the Rust twin
`divoomd/tests/framing_resync.rs` pin the same case on the other side.

The two frames are written out as literals rather than built with an encoder:
`divoom_lib.framing` is parse-only since phase L4 (the encoders were deleted
with the C library), and re-implementing one here would be the third
implementation that phase removed. Their validity is asserted below.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import framing

# [0x01][len_lo][len_hi][body...][cksum_lo][cksum_hi][0x02]
# FIRST: body 0x46, len 3 (body + 2 checksum), checksum = 0x03+0x00+0x46 = 0x49.
FIRST = bytes.fromhex("01030046490002")
# SECOND: body 0x74 0x3C, len 4, checksum = 0x04+0x00+0x74+0x3C = 0xB4.
SECOND = bytes.fromhex("010400743cb40002")


def _spurious_header_over(fake_length):
    """`[0x01, fake_length_le, ...]` whose span covers both real frames.

    The filler (0x11) is neither a start nor an end marker, so the fake frame
    fails the end-byte test -- exactly the case that used to drain the whole
    span and drop the genuine frames sitting inside it.
    """
    header = bytes([0x01, fake_length & 0xFF, (fake_length >> 8) & 0xFF])
    span = 4 + fake_length
    body = header + FIRST + SECOND
    assert len(body) <= span, "the real frames must fit inside the fake span"
    return body + b"\x11" * (span - len(body))


def test_the_two_literal_frames_are_valid_on_their_own():
    # Guards the literals below: proves the frames parse alone, so a failure in
    # the resync test is the spurious byte and not a mis-typed checksum.
    messages, remainder = framing.parse_basic_protocol_frames(bytearray(FIRST + SECOND))
    assert [m["command_id"] for m in messages] == [0x46, 0x74]
    assert remainder == b""


def test_short_candidate_is_rejected_not_panicked():
    # P1.11: a candidate whose length field is below three (fewer than seven
    # bytes total) used to panic the Rust parser (slice index inversion) and
    # emit a degenerate frame on the Python side. Both now reject it and resync
    # by one byte, so a stray `0x01 00 00 02` can never produce a frame.
    buf = bytearray(bytes.fromhex("01000002aabbcc"))
    messages, remainder = framing.parse_basic_protocol_frames(buf)
    assert messages == [], "a short candidate must not produce a frame"
    buf = bytearray(_spurious_header_over(fake_length=21))
    messages, remainder = framing.parse_basic_protocol_frames(buf)
    assert [m["command_id"] for m in messages] == [0x46, 0x74], (
        f"the spurious start byte swallowed real frames; got {messages}"
    )
    assert messages[0]["payload"] == b""
    assert messages[1]["payload"] == bytes([0x3C])
    assert remainder == b"", f"unexpected remainder {bytes(remainder).hex()}"
