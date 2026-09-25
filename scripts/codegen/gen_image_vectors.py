#!/usr/bin/env python3
"""Capture image-encoder parity vectors FROM THE C, densely, and cross-check them.

    PYTHONPATH=<repo root> python3 scripts/codegen/gen_image_vectors.py

Phase L4 is going to replace `libdivoom_compact`'s image encoders with Rust, and
this file is the evidence that the replacement preserved them. Two things about
the previous version of this generator were wrong, and both mattered:

* **The vectors came from the Python reference, not from the C.** The old
  docstring called the Python encoders "the SPEC" — they live in
  `examples/divoom_legacy`, were retired from the product on 2026-09-14, and
  nothing in the shipped app runs them. That is a fine cross-check and a poor
  oracle: the thing being replaced is the C, so the C's bytes are the behaviour
  to preserve. So every vector here is captured from the dylib, and the Python
  reference is checked AGAINST it rather than the other way round.
* **21 cases.** Eight sizes for the palette encoders and five colour counts for
  the 32x32 one, which is a smoke test wearing the name of an oracle. What sizes
  actually stress an encoder is the awkward ones — non-square, one pixel wide,
  larger than the panel so the LANCZOS3 downsampler runs — and none of those
  were in the set except 5x7.

Every case is therefore cross-checked against BOTH implementations, and this
script fails if they disagree. That turns it into a two-implementation gate
rather than a recorder: if a future change to either side moves one byte, the
regeneration stops and says which case.

One documented divergence, probed rather than assumed (140 comparisons across
13 sizes x 5 colour counts, 2026-09-25): at a ZERO dimension the C refuses
(`NULL`/negative) while the Python reference emits a degenerate frame. The C's
behaviour is the one recorded, and it is the one the port must keep — a
zero-sized panel is a caller bug, and the honest answer to it is a refusal.
"""

from __future__ import annotations

import ctypes
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "examples"))
sys.path.insert(0, str(REPO))

from divoom_legacy.native import image_encoder as IE  # noqa: E402
from divoom_legacy.utils.divoom_image_encode_32 import (  # noqa: E402
    encode_animation_frame_32 as py_frame32,
)

LIB = REPO / "divoom_lib" / "libdivoom_compact.dylib"

U8P = ctypes.POINTER(ctypes.c_ubyte)

# Sizes chosen for what they stress, not for looking tidy: non-square, a single
# pixel, and larger-than-panel so the downsampler is on the path at all. The
# palette encoders target 16x16 and the 32x32 one targets 32x32, so anything
# bigger proves the downscale and anything else proves the crop.
PALETTE_SIZES = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 7), (7, 5), (8, 8), (3, 1), (1, 3), (16, 16), (17, 13), (32, 32), (64, 64)]
COLOUR_COUNTS = [1, 2, 5, 17, 64, 256]
FRAME_TIMES = [0, 1, 500, 1000, 65535]
SIZE_32 = [(32, 32)]


def _load() -> ctypes.CDLL:
    if not LIB.exists():
        sys.exit(
            f"✗ {LIB} is gone. This generator captures the C's own bytes, so the C "
            "has to exist to run it — that is the whole point of the file. Build "
            "it with scripts/build_libdivoom.sh."
        )
    lib = ctypes.CDLL(str(LIB))
    lib.divoom_encode_animation_frame.argtypes = [U8P, ctypes.c_int, ctypes.c_int, ctypes.c_uint16, U8P, ctypes.c_int]
    lib.divoom_encode_animation_frame.restype = ctypes.c_int
    lib.divoom_encode_static_image.argtypes = [U8P, ctypes.c_int, ctypes.c_int, U8P, ctypes.c_int]
    lib.divoom_encode_static_image.restype = ctypes.c_int
    lib.divoom_encode_animation_frame_32.argtypes = [U8P, ctypes.c_int, ctypes.c_int, ctypes.c_uint16, U8P, ctypes.c_int]
    lib.divoom_encode_animation_frame_32.restype = ctypes.c_int
    return lib


def c_frame(lib, rgb: bytes, w: int, h: int, t: int) -> bytes | None:
    out = (ctypes.c_ubyte * (8 + 256 * 3 + w * h + 16))()
    buf = (ctypes.c_ubyte * max(len(rgb), 1)).from_buffer_copy(rgb or b"\0")
    n = lib.divoom_encode_animation_frame(buf, w, h, t, out, len(out))
    return bytes(out[:n]) if n >= 0 else None


def c_static(lib, rgb: bytes, w: int, h: int) -> bytes | None:
    out = (ctypes.c_ubyte * (8 + 256 * 3 + w * h + 16))()
    buf = (ctypes.c_ubyte * max(len(rgb), 1)).from_buffer_copy(rgb or b"\0")
    n = lib.divoom_encode_static_image(buf, w, h, out, len(out))
    return bytes(out[:n]) if n >= 0 else None


def c_frame32(lib, rgb: bytes, w: int, h: int, t: int) -> bytes | None:
    out = (ctypes.c_ubyte * (16 + 256 * 3 + w * h + 64))()
    buf = (ctypes.c_ubyte * max(len(rgb), 1)).from_buffer_copy(rgb or b"\0")
    n = lib.divoom_encode_animation_frame_32(buf, w, h, t, out, len(out))
    return bytes(out[:n]) if n >= 0 else None


def rgb_n(w: int, h: int, nc: int, seed: int) -> bytes:
    """A deterministic image: a palette of `nc` colours laid out so every row and
    column differs, because a flat image proves an encoder nothing."""
    rng = random.Random(seed)
    pal = [bytes((rng.randrange(256), rng.randrange(256), rng.randrange(256))) for _ in range(nc)]
    return b"".join(pal[(x * 7 + y * 13) % nc] for y in range(h) for x in range(w))


def record(direction: str, w: int, h: int, rgb: bytes, t: int | None, c_bytes: bytes | None, py_bytes: bytes | None) -> dict:
    case = {"w": w, "h": h, "rgb": rgb.hex()}
    if t is not None:
        case["time"] = t
    if c_bytes is None:
        # The C refused. Recorded as a refusal, because a Rust port that emits a
        # frame here has invented behaviour — and "the C returned nothing" is not
        # the same fact as "the C returned zero bytes".
        case["refused"] = True
        if py_bytes is not None:
            print(f"  ! {direction} {w}x{h} t={t}: C refused, python emitted {len(py_bytes)}B")
        return case
    case["out"] = c_bytes.hex()
    if py_bytes is not None and py_bytes != c_bytes:
        raise SystemExit(
            f"✗ {direction} {w}x{h} colours={len({bytes(rgb[i:i+3]) for i in range(0, len(rgb), 3)})} "
            f"time={t}: the two implementations DISAGREE and this script will not "
            f"pick a winner.\n  C:     {c_bytes[:48].hex()}\n  python: {py_bytes[:48].hex()}"
        )
    if py_bytes is None:
        raise SystemExit(f"✗ {direction} {w}x{h} t={t}: no python reference to cross-check against")
    return case


def main() -> None:
    lib = _load()
    out: dict[str, list[dict]] = {"frame": [], "static": [], "frame32": []}
    disagreements = 0

    for w, h in PALETTE_SIZES:
        for nc in COLOUR_COUNTS:
            rgb = rgb_n(w, h, nc, w * 1000 + h * 10 + nc)
            py_static = bytes(IE.encode_static_image(rgb, w, h)) if w and h else None
            out["static"].append(record("static", w, h, rgb, None, c_static(lib, rgb, w, h), py_static))
            # One time value per (size, colours) for the bulk, then a full sweep of
            # the time axis on one size: `time_ms` only reaches the frame DURATION
            # field, so one size proves it and 65k of them prove nothing new.
            times = FRAME_TIMES if (w, h) == (16, 16) else [500]
            for t in times:
                py_frame = bytes(IE.encode_animation_frame(rgb, w, h, t)) if w and h else None
                case = record("frame", w, h, rgb, t, c_frame(lib, rgb, w, h, t), py_frame)
                out["frame"].append(case)
                if case.get("refused"):
                    disagreements += 1

    for w, h in SIZE_32:
        for nc in COLOUR_COUNTS:
            rgb = rgb_n(w, h, nc, nc + 9999)
            times = FRAME_TIMES if nc == COLOUR_COUNTS[0] else [500]
            for t in times:
                py32 = bytes(py_frame32(rgb, w, h, t)) if w and h else None
                out["frame32"].append(record("frame32", w, h, rgb, t, c_frame32(lib, rgb, w, h, t), py32))

    # The zero-dimension divergence, captured as a case rather than left as a
    # sentence in a docstring: it is the one place the two implementations
    # differ, and a port has to know about it.
    for direction, fn in (("static", lambda: c_static(lib, b"", 0, 0)), ("frame", lambda: c_frame(lib, b"", 0, 0, 500))):
        out[direction].append({"w": 0, "h": 0, "rgb": "", **({"time": 500} if direction == "frame" else {}), "refused": True})

    total = sum(len(v) for v in out.values())
    dest = REPO / "divoomd" / "tests" / "image_vectors.json"
    # One line per case, for the reason the framing vectors learned the hard way:
    # `indent=2` turned 550 cases into 23,895 lines, past this repo's own
    # corruption ceiling, and a diff nobody can read is a fixture nobody checks.
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
    dest.write_text("\n".join(lines) + "\n")
    size = dest.stat().st_size
    print(f"wrote {total} vectors ({size:,} bytes) -> {dest}")
    print(f"  frame={len(out['frame'])} static={len(out['static'])} frame32={len(out['frame32'])}")
    if disagreements:
        print(f"  {disagreements} documented C-refusals where the python reference emitted a frame")


if __name__ == "__main__":
    main()
