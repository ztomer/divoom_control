"""L1 protocol lock, Python side: the shared vector file is consumed by BOTH suites.

`divoomd/tests/framing_vectors.json` is generated from `divoom_lib/framing.py`
by `scripts/codegen/gen_framing_vectors.py` and pinned by Rust's
`framing_parity.rs`. Without this test, a regenerated-but-wrong vectors file
goes green on the Rust side by construction (it pins whatever Python emitted).
This test closes the loop: Python must reproduce every committed vector, so a
bad regeneration fails HERE with the Python behavior as witness.
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import framing

VECTORS = json.loads(
    (Path(__file__).parent.parent / "divoomd" / "tests" / "framing_vectors.json").read_text()
)


def _h(b) -> str:
    return bytes(b).hex()


# The two ENCODE tests that lived here are gone with the encoders (L4: the
# daemon frames, `divoom_lib/framing` is parse-only). Their subject moved rather
# than vanished: `divoomd/tests/framing_parity.rs` asserts every one of these
# vectors byte for byte against the Rust encoder, which is the implementation
# that now owns framing. Keeping a Python test that re-implements framing to
# check a Rust encoder would be a third implementation, which is the thing this
# phase removed.


def test_parse_ios_le_vectors_reproduce():
    for c in VECTORS["parse_ios_le"]:
        res = framing.parse_ios_le_notification(bytes.fromhex(c["in"]))
        if res is not None:
            res = {
                "command_id": res["command_id"],
                "payload": _h(res["payload"]),
                "packet_number": res["packet_number"],
                "checksum": res["checksum"],
            }
        assert res == c["result"], f"parse_ios_le({c['in']})"


def test_parse_basic_vectors_reproduce():
    for c in VECTORS["parse_basic"]:
        msgs, remainder = framing.parse_basic_protocol_frames(bytearray(bytes.fromhex(c["in"])))
        got = {
            "messages": [
                {"command_id": m["command_id"], "payload": _h(m["payload"])} for m in msgs
            ],
            "remainder": _h(remainder),
        }
        assert got["messages"] == c["messages"], f"parse_basic msgs for {c['in']}"
        assert got["remainder"] == c["remainder"], f"parse_basic remainder for {c['in']}"


def test_resync_vector_present():
    """The MAX_BASIC_FRAME corrupt-length resync case must stay in the vectors;
    losing it silently un-pins the R53.18 stall guard on both sides."""
    assert any(
        c["in"].startswith("01ffff") for c in VECTORS["parse_basic"]
    ), "corrupt-length resync vector missing — regenerate with gen_framing_vectors.py"
