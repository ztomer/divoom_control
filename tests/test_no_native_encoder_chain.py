"""The Python-side FRAMING half of the C chain is gone, and cannot come back quietly.

`divoom_lib/libdivoom_compact.dylib` and `divoom_lib/native_src/*.c` were a
compiled artifact plus its sources, committed to the repository and rebuilt by
`scripts/build_libdivoom.sh`. On 2026-09-25 the last live caller of the library's
FRAMING half went away: `divoomd` frames with `crate::framing` — the same
encoder the BLE path uses, pinned against this C library's own bytes by 550
vectors in `divoomd/tests/framing_vectors.json` — and
`divoom_client/spp_bridge.py` writes the exact bytes it is handed. So
`divoom_lib/framing.py` is a parse-only module now and the Python encoders are
gone from it.

**The IMAGE half of the same library is still here, deliberately, and this file
must not pretend otherwise.** The daemon's image path has no fallback: with the
encoder absent, `wall.rs` silently returns false and
`device_call/basic/display.rs` answers "encoder not available"
(`divoomd/src/native_encode.rs`, loaded through `libloading`). Deleting the C
before porting the 16x16 palette encoder, the 32x32 encoder, the 0x8B chunker
and LANCZOS3 downsampling would break image display — which is exactly what
happened when this round first tried, and the dylib was restored.

So this gate asserts the part that is true, and names the part that is not:

* no Python framing encoder remains, and nothing in a shipped package names the
  library's framing entry points;
* the record of what the framing half produced is present and dense (550
  vectors), because a "the C is gone" claim with a 4-case fixture would pass a
  tree that lost both halves;
* the image half is called out by name, with the file that consumes it and the
  port that replaces it. If someone deletes the C while the port is unmade,
  `test_the_image_half_is_still_c_on_purpose` fails and says what breaks.

`nowplaying/native/libnp_helper.dylib` is also tracked: a different crate's
native helper, not on this chain, and its removal is its own round.

Proven red-once: written while all eight chain files were tracked, it named
every one of them; the framing assertions have been red since before the
encoders were removed, and the image assertion goes red the moment the dylib
disappears without the port.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent

# The shipped Python packages. `examples/` is excluded on purpose: it is not in
# the wheel (pyproject's `exclude`), so a reference there ships to nobody.
SHIPPED_PACKAGES = ("divoom_lib", "divoom_client", "divoom_gui", "divoom_control")

VECTORS = "divoomd/tests/framing_vectors.json"

# Native artifacts NOT on this chain, listed rather than ignored: an exemption
# nobody reads is how a second one sneaks in.
ALLOWED_ELSEWHERE = {
    "nowplaying/native/libnp_helper.dylib": (
        "a different crate's native helper, not on the divoom_lib chain"
    ),
}

# What still legitimately needs the C, and who says so in the code.
IMAGE_HALF_CONSUMERS = ("divoomd/src/native_encode.rs", "divoomd/src/daemon.rs")


def code_only(source: str) -> str:
    """The source with comments and docstrings removed.

    A gate that greps raw text reads a COMMENT as an implementation. The first
    draft of this file asserted `encode_basic_payload` does not appear in
    `divoom_lib/framing.py` and failed on the parse side's own docstring, which
    mentions the encoder by name while explaining the checksum -- a sentence,
    not a call. Judging code is what the check is for.
    """
    import io
    import tokenize

    out: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(token.string)
    except tokenize.TokenError:
        return source
    return " ".join(out)


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, check=True, capture_output=True, text=True
    )
    return out.stdout.splitlines()


def test_no_python_framing_encoder_remains() -> None:
    """`divoom_lib/framing.py` parses; it does not frame.

    A second encoder in Python is the thing this whole phase removed: two
    implementations of one protocol is a device that behaves differently
    depending on which radio reached it, and the disagreement only shows up on
    hardware.
    """
    framing = code_only((REPO / "divoom_lib" / "framing.py").read_text())
    for gone in ("encode_basic_payload", "encode_ios_le_payload", "ctypes", "CDLL"):
        assert gone not in framing, (
            f"divoom_lib/framing.py still has {gone!r}: the daemon frames now "
            "(L4), and a Python encoder is the second implementation"
        )
    assert "parse_ios_le_notification" in framing, "the parse side must stay"
    assert "parse_basic_protocol_frames" in framing, "the parse side must stay"


def test_nothing_shipped_loads_the_library_for_framing() -> None:
    """No shipped Python module frames any more.

    Scoped to the two framing entry points, NOT to `CDLL` or
    `platform_libname`: the daemon client legitimately loads the dylib to hand
    the DAEMON an image encoder (`DIVOOMD_ENCODER_LIB`), which is the image half
    this phase has not reached, and `daemon_client.py` also opens `libc` through
    ctypes for an unrelated macOS call. A gate that flagged those would be
    wrong, and a gate that is wrong gets deleted.
    """
    pattern = re.compile(r"encode_basic_payload|encode_ios_le_payload")
    hits: list[str] = []
    for package in SHIPPED_PACKAGES:
        for path in sorted((REPO / package).rglob("*.py")):
            if path.name == "framing.py":
                continue
            for number, line in enumerate(code_only(path.read_text()).splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not hits, "something shipped still frames in Python:\n" + "\n".join(hits)


def test_the_record_of_what_the_c_framed_is_present_and_dense() -> None:
    # Without this, "the C is gone" is a claim with no evidence attached: the
    # vectors ARE the C's recorded behaviour, and the Rust side asserts every
    # one of them byte for byte.
    assert VECTORS in tracked(), f"{VECTORS} is the C's recorded framing and must be tracked"
    vectors = json.loads((REPO / VECTORS).read_text())
    assert len(vectors["encode_basic"]) >= 200, "the basic-framing sweep shrank"
    assert len(vectors["encode_ios_le"]) >= 300, "the ios_le sweep shrank"


def test_the_c_library_the_image_path_needs_is_actually_present() -> None:
    """The half that is still C must be THERE, not merely referenced.

    Added because this file passed with the dylib deleted from the index: it
    asserted that the consumers still name the library and never that the
    library exists. That is precisely the mistake this round made — deleting the
    C before the image encoders were ported — and the gate that was written to
    prevent it waved it through. An assertion about what depends on something
    is not an assertion that the something is there.
    """
    present = set(tracked())
    required = {
        "divoom_lib/libdivoom_compact.dylib": "image display: wall.rs returns false, display.rs errors",
        "divoom_lib/native_src/image_encode.c": "the 16x16 palette encoder's source",
        "divoom_lib/native_src/image_encode_32.c": "the 32x32 encoder and 0x8B chunker",
        "divoom_lib/native_src/downsample.c": "LANCZOS3 downscaling",
        "scripts/build_libdivoom.sh": "how the dylib is rebuilt when the C changes",
    }
    gone = {path: why for path, why in required.items() if path not in present}
    assert not gone, (
        "the C the image path still needs is GONE, and there is no pure-Rust "
        "fallback:\n"
        + "\n".join(f"  {path}: {why}" for path, why in sorted(gone.items()))
        + "\nPort the encoders first (divoomd/tests/image_vectors.json is the "
        "oracle), then delete the C -- and delete THIS test with it."
    )


def test_the_image_half_is_still_c_on_purpose() -> None:
    """The C is STILL HERE, for images, and this test says so out loud.

    Written after this round deleted the dylib and broke image display: the
    daemon has no pure-Rust fallback for the palette encoders, the 32x32
    encoder, the 0x8B chunker or the downscaler. Whoever finishes L4 has to
    port those first, prove them against `divoomd/tests/image_vectors.json` and
    `divoomd/tests/native_encode_parity.rs`, and only then delete
    `divoom_lib/native_src/` and the dylib. This test is the reminder that turns
    "delete the C" from an obvious next step into a port first.
    """
    for path in IMAGE_HALF_CONSUMERS:
        assert path in tracked(), (
            f"{path} disappeared: it is what still loads the C image encoders, "
            "and its absence means the port replaced it — say so here"
        )
    native_encode = (REPO / "divoomd" / "src" / "native_encode.rs").read_text()
    assert "libdivoom_compact" in native_encode, (
        "divoomd/src/native_encode.rs no longer names the library it loads"
    )
    # The fallback that does NOT exist, stated as an assertion so nobody
    # assumes it: with the encoder gone, display.rs errors out.
    display = (REPO / "divoomd" / "src" / "device_call" / "basic" / "display.rs").read_text()
    assert "encoder not available" in display, (
        "the no-encoder path changed: if the image encoders are now ported, "
        "this refusal is the thing to delete, and this test with it"
    )


def test_the_exemption_list_is_still_needed() -> None:
    for path, reason in ALLOWED_ELSEWHERE.items():
        assert path in tracked(), (
            f"{path} is exempted but is no longer tracked ({reason}); drop it "
            "from ALLOWED_ELSEWHERE"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
