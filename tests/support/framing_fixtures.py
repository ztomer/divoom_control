"""Device bytes for tests, taken from the record of what the C library produced.

`divoom_lib/framing.py` used to encode as well as parse, through
`libdivoom_compact.dylib`. It is parse-only now (phase L4, 2026-09-25): the
daemon frames with `divoomd::framing` and the SPP co-process writes the bytes it
is handed. So a test that needs a frame — a parser test, a resync test, an RX
edge case — cannot make one any more, and the wrong answers are both obvious in
hindsight: re-implement the encoder in the test (a THIRD implementation of the
protocol, which is what this phase exists to remove), or type hex from memory.

Typing hex is what the first drafts did, and of eleven hand-written literals
three were wrong — a wrong length field, a wrong checksum, a wrong end byte —
each of which is a test that passes for the wrong reason or fails for a reason
that has nothing to do with the parser.

So the bytes come from `divoomd/tests/framing_vectors.json`: 550 vectors
captured from the C library itself, which the Rust encoder and parser are
already asserted against byte for byte. A fixture and the implementation under
test then come from the same record, and a payload nobody recorded fails loudly
instead of silently becoming a plausible-looking frame.

Usage:
    from tests.support.framing_fixtures import basic_frame, ios_le_frame

    frame = basic_frame(0x46)                    # exactly as recorded
    frame, payload = longest_recorded("encode_ios_le")
"""

from __future__ import annotations

import json
from pathlib import Path

VECTORS_PATH = (
    Path(__file__).resolve().parents[2] / "divoomd" / "tests" / "framing_vectors.json"
)

BASIC = "encode_basic"
IOS_LE = "encode_ios_le"


def _vectors() -> dict:
    return json.loads(VECTORS_PATH.read_text())


def recorded_frame(direction: str, payload: list[int]) -> bytes:
    """The frame the C library produced for exactly this payload.

    Raises rather than inventing one: a payload nobody recorded means the test
    wants bytes no device has been observed to send, and the honest thing is to
    add it to the record (regenerate with
    `scripts/codegen/gen_framing_vectors.py`) or pick a recorded one.
    """
    for case in _vectors()[direction]:
        if case["payload"] == payload and not case.get("escape", False):
            return bytes.fromhex(case["out"])
    raise AssertionError(
        f"no recorded {direction} frame for payload {payload}; the C library's "
        "record is the only source of device bytes now that Python does not "
        "encode"
    )


def basic_frame(*payload: int) -> bytes:
    return recorded_frame(BASIC, list(payload))


def ios_le_frame(*payload: int) -> bytes:
    return recorded_frame(IOS_LE, list(payload))


def longest_recorded(direction: str) -> tuple[bytes, list[int]]:
    """The longest recorded frame, and the payload inside it.

    Both, because callers assert the parsed command id and the command id IS the
    payload's first byte — a hardcoded id in the test would be asserting a fact
    about whichever frame happens to be longest.
    """
    case = max(_vectors()[direction], key=lambda c: len(c["payload"]))
    return bytes.fromhex(case["out"]), case["payload"]
