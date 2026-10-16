#!/usr/bin/env python3
"""Regenerate divoomd/tests/framing_vectors.json from the Python framing.

    PYTHONPATH=<repo root> python3 scripts/codegen/gen_framing_vectors.py

The Python framing is the AUTHORITATIVE source for the PARSER (parallel-build
strategy — see docs/ROADMAP.md), so this tool recomputes, for every committed
input, what `divoom_lib.framing` returns, and the Rust tests then pin the same
bytes. But it no longer generates EVERYTHING, and that is deliberate:

* The ENCODE vectors are FROZEN. Encoding is not Python's any more — the
  encoders went with the C library in phase L4 (2026-09-25) — so those bytes are
  the deleted C library's recorded behaviour and this tool carries them forward
  verbatim rather than inventing a second encoder to regenerate them (a second
  implementation is the exact thing L4 removed, and one that agreed with itself
  would be blind to its own bugs).
* The PARSE vectors' INPUTS are likewise frozen: building a valid frame to feed
  the parser needs an encoder Python no longer has. What is recomputed here is
  the parser's expected OUTPUT for each frozen input — the only thing that
  changes when the parser changes.

`build()` returns the document and `render()` its exact text, so the generator
either reproduces the committed file byte for byte or fails the review; it can
never silently rewrite the vectors. `tests/test_framing_vector_generator.py`
holds that contract.
"""
import json
from pathlib import Path

from divoom_lib import framing


def _h(b: bytes) -> str:
    return bytes(b).hex()


def _ios_le_result(raw: bytes):
    res = framing.parse_ios_le_notification(bytes(raw))
    if res is None:
        return None
    return {
        "command_id": res["command_id"],
        "payload": _h(res["payload"]),
        "packet_number": res["packet_number"],
        "checksum": res["checksum"],
    }


def _parse_ios_le_cases(existing):
    return [{"in": c["in"], "result": _ios_le_result(bytes.fromhex(c["in"]))} for c in existing]


def _parse_basic_cases(existing):
    cases = []
    for c in existing:
        buf = bytearray(bytes.fromhex(c["in"]))
        msgs, remainder = framing.parse_basic_protocol_frames(buf)
        cases.append({
            "in": c["in"],
            "messages": [{"command_id": m["command_id"], "payload": _h(m["payload"])} for m in msgs],
            "remainder": _h(remainder),
        })
    return cases


def build(dest=None):
    """Return the vector document, recomputed from `divoom_lib.framing`.

    The committed file at `dest` is read for the frozen ENCODE vectors and the
    frozen PARSE inputs; only the parse outputs are recomputed. Key order is
    fixed to the file's own order so `render` is byte-stable.
    """
    dest = Path(dest) if dest is not None else vectors_path()
    existing = json.loads(dest.read_text())
    return {
        "encode_basic": existing["encode_basic"],
        "encode_ios_le": existing["encode_ios_le"],
        "parse_ios_le": _parse_ios_le_cases(existing["parse_ios_le"]),
        "parse_basic": _parse_basic_cases(existing["parse_basic"]),
    }


def render(out) -> str:
    """Serialize the document one case per line.

    Hand-laid-out rather than `json.dumps(indent=2)`. Two reasons, both learned
    here: `indent=2` put every case across ten lines and 550 cases became 23,895
    lines — past the repo's own 15,000-line corruption ceiling
    (tests/test_no_runaway_file_growth.py), which is a real gate catching a real
    shape; and a vector file whose diff is one line per case is reviewable,
    where ten lines per case is not. The payload lists are still JSON arrays and
    the hex is still hex.
    """
    lines = ["{"]
    keys = list(out)
    for index, key in enumerate(keys):
        comma = "," if index < len(keys) - 1 else ""
        lines.append(f'"{key}": [')
        cases = out[key]
        for position, case in enumerate(cases):
            tail = "," if position < len(cases) - 1 else ""
            lines.append(json.dumps(case, separators=(",", ":"), sort_keys=True) + tail)
        lines.append(f"]{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def vectors_path() -> Path:
    # scripts/codegen/gen_framing_vectors.py -> repo root is three parents up.
    # It was two, which resolved to scripts/divoomd/ -- a directory that does
    # not exist, created by mkdir and written into: the generator printed a
    # success line and produced a file no test has ever read. Same bug and the
    # same fix as gen_commands.py; a generator whose output path is wrong is
    # indistinguishable from one that is not being run.
    return Path(__file__).resolve().parent.parent.parent / "divoomd" / "tests" / "framing_vectors.json"


def main():
    dest = vectors_path()
    out = build(dest)
    dest.write_text(render(out))
    n = sum(len(v) for v in out.values())
    print(f"wrote {n} vectors -> {dest}")


if __name__ == "__main__":
    main()
