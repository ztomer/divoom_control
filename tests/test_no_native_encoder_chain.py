"""L4 is finished: the C encoder chain is out of the tree, and stays out.

`divoom_lib/libdivoom_compact.dylib` and `divoom_lib/native_src/*.c` were a
compiled artifact plus its sources, committed to the repository and rebuilt by
`scripts/build_libdivoom.sh`. Both are gone as of 2026-09-25, and so is the
loader (`divoom_lib/native_lib.py`), the `DIVOOMD_ENCODER_LIB` hand-off in the
daemon client, and the `pyproject.toml` globs that shipped a per-platform binary
inside the wheel.

What replaced them, and what this file holds them to:

* the framing half by `divoomd::framing` — the same encoder the BLE path uses,
  asserted against 550 vectors captured from the C library itself;
* the image half by `divoomd::image_encode` — palette dedup and LSB-first
  packing, asserted against 192 vectors captured from the C, across 13 sizes and
  6 colour counts, with the one case where the C and its Python reference
  differed (a zero dimension, which the C refuses) recorded as a refusal;
* the refusal that came with it: `display.rs` used to answer "encoder not
  available" whenever the library was missing, so a working install could not
  show an image. There is nothing to be missing now, and this asserts the
  refusal does not come back.

How this gate got here is worth recording, because it was wrong twice. It was
first written to demand the whole C be gone, which was false — the daemon's image
path had no fallback, and deleting the library broke image display. It was then
written to demand the C STAY, and that version passed with the dylib deleted
from the index, because it asserted what depends on the library without asserting
the library was there. Both versions were red-once proven. This one asserts the
state that is actually true, and each of its assertions has been watched fail.

`nowplaying/native/libnp_helper.dylib` is also tracked: a different crate's
native helper, not on this chain, and its removal is its own round.
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


def test_the_c_is_gone_and_nothing_can_reach_for_it() -> None:
    """L4 finished: no C, no binary, no loader, anywhere.

    Every one of these was a way back to the C, and each is a thing that
    silently comes back: a `.c` file re-added "just to compare", a prebuilt
    dylib committed so nobody has to build it, a `native_lib` import that still
    resolves on a machine with an old install. The gate that stopped the
    halfway deletion is this one.
    """
    present = set(tracked())
    gone = [
        path
        for path in present
        if path.endswith((".c", ".h"))
        or (path.startswith("divoom_lib/") and path.endswith((".dylib", ".so", ".dll")))
        or path in ("scripts/build_libdivoom.sh", "divoom_lib/native_lib.py")
    ]
    assert not gone, "the C encoder chain is back:\n" + "\n".join(f"  {p}" for p in sorted(gone))


def test_nothing_shipped_mentions_the_library() -> None:
    pattern = re.compile(r"libdivoom_compact|DIVOOMD_ENCODER_LIB|native_lib|platform_libname")
    hits: list[str] = []
    for package in SHIPPED_PACKAGES:
        for path in sorted((REPO / package).rglob("*.py")):
            for number, line in enumerate(code_only(path.read_text()).splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not hits, "shipped code still names the deleted library:\n" + "\n".join(hits)


def test_pyproject_ships_no_native_binary() -> None:
    globs = re.findall(r'"\*\.(?:dylib|so|dll)"', (REPO / "pyproject.toml").read_text())
    assert not globs, f"pyproject still globs native binaries into the wheel: {globs}"


def test_the_recording_that_replaced_the_c_is_present_and_dense() -> None:
    """The evidence the port stands on, and both halves of it.

    `image_vectors.json` is the C's recorded image output — 192 cases, asserted
    byte for byte by `image_encode.rs`. `framing_vectors.json` is the C's
    recorded framing, asserted by `framing_parity.rs` and `framing_round_trip.rs`.
    A "the C is gone" rule with thin fixtures would pass a tree that lost both
    halves, so the density is asserted, not just the presence.
    """
    for relative, direction, floor in (
        ("divoomd/tests/image_vectors.json", "frame", 100),
        ("divoomd/tests/framing_vectors.json", "encode_basic", 200),
    ):
        assert relative in tracked(), f"{relative} records what the C produced and must be tracked"
        vectors = json.loads((REPO / relative).read_text())
        assert len(vectors[direction]) >= floor, (
            f"{relative}: {direction} has {len(vectors[direction])} cases, expected "
            f"at least {floor}"
        )


def test_the_image_path_no_longer_refuses_for_a_missing_encoder() -> None:
    """The refusal existed only because the encoder could be absent.

    `display.rs` answered "encoder not available (DIVOOMD_ENCODER_LIB)" whenever
    the C library was not found, which is how a perfectly good install could not
    show an image. With the encoders in the binary there is nothing to be
    missing, so the refusal is the thing that should be gone -- and this asserts
    it stays gone, because putting it back would be a way to reintroduce the
    dependency without anyone noticing.
    """
    display = (REPO / "divoomd" / "src" / "device_call" / "basic" / "display.rs").read_text()
    assert "encoder not available" not in display, (
        "display.rs refuses again for a missing encoder, but the encoder is Rust "
        "in this binary and cannot be missing"
    )
    daemon = (REPO / "divoomd" / "src" / "daemon.rs").read_text()
    assert "encoder" not in daemon, (
        "Daemon::encoder() is back: there is no library to load and no lazy init "
        "to do"
    )


def test_the_exemption_list_is_still_needed() -> None:
    for path, reason in ALLOWED_ELSEWHERE.items():
        assert path in tracked(), (
            f"{path} is exempted but is no longer tracked ({reason}); drop it "
            "from ALLOWED_ELSEWHERE"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
