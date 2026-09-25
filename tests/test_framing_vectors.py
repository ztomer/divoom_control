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


def test_encode_basic_vectors_reproduce():
    for c in VECTORS["encode_basic"]:
        got = framing.encode_basic_payload(c["payload"], escape=c["escape"])
        assert _h(got) == c["out"], f"encode_basic({c['payload']}, escape={c['escape']})"


def test_encode_ios_le_vectors_reproduce():
    for c in VECTORS["encode_ios_le"]:
        got = framing.encode_ios_le_payload(c["payload"], packet_number=c["packet"])
        assert _h(got) == c["out"], f"encode_ios_le({c['payload']}, packet={c['packet']})"


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
