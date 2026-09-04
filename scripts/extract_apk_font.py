#!/usr/bin/env python3
"""Extract the printable-ASCII subset of a Divoom APK bitmap font (R28).

The official Divoom Android app bundles 16x16 1-bpp bitmap fonts under
``assets/divoom_fond16_*.bin`` / ``FontLib_16_*.bin``. The matrix devices are
16/32/64px, so anti-aliased TrueType text turns to mush — the device-bound text
we rasterise must use these exact bitmap glyphs.

APK storage format (reverse-engineered from ``F2/d.smali``):
  * Each glyph is exactly 32 bytes = 16 rows x 16 cols, 1 bit/pixel.
  * Glyph for codepoint ``cp`` lives at byte offset ``(cp - 0x21) * 32`` for the
    printable-ASCII range ``0x21..0x7e`` (``'A'`` = 0x41 -> index 32, ``'0'`` =
    0x30 -> index 15). (Other Unicode ranges follow in the smali range table.)
  * Within a glyph: 2 bytes per row, little-endian 16-bit, MSB = leftmost pixel,
    but the whole glyph is stored ROTATED — applying a 270deg-CW transform yields
    the upright character.

This script bakes the rotation in at extraction time so the runtime
``BitmapFont`` reader is trivial (read 32 bytes, 2/row, MSB-left, upright). It
writes 95 glyphs for codepoints ``0x20..0x7e`` (space = blank) to
``divoom_lib/fonts/divoom_fond16_default_ascii.bin``.

Usage::

    python3 scripts/extract_apk_font.py            # default font
    python3 scripts/extract_apk_font.py <src.bin> <dst.bin>
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SRC = (
    REPO / "references" / "apk" / "decompiled_src" / "resources" / "assets"
    / "divoom_fond16_default.bin"
)
DEFAULT_DST = REPO / "divoom_lib" / "fonts" / "divoom_fond16_default_ascii.bin"

GLYPH_BYTES = 32          # 16x16 @ 1bpp
FIRST_CP = 0x20           # space (blank)
LAST_CP = 0x7E            # '~'


def _decode_apk_glyph(blob: bytes, cp: int) -> list[list[int]]:
    """Return an upright 16x16 0/1 matrix for ``cp`` from the raw APK blob."""
    idx = cp - 0x21
    g = blob[idx * GLYPH_BYTES : idx * GLYPH_BYTES + GLYPH_BYTES]
    # 2 bytes/row, little-endian 16-bit, MSB = leftmost — the *stored* (rotated)
    # orientation.
    raw = [
        [((g[r * 2] | (g[r * 2 + 1] << 8)) >> (15 - x)) & 1 for x in range(16)]
        for r in range(16)
    ]
    # 270deg-CW transform -> upright glyph.
    return [[raw[c][15 - r] for c in range(16)] for r in range(16)]


def _halve(mat: list[list[int]]) -> list[list[int]]:
    """Return ``mat`` at half scale, top-left aligned in a fresh 16x16 cell.

    The glyph is cropped to its bounding box, 2x-downsampled with a coverage
    threshold: a 2x2 block lights up if **at least 2 of its 4 source pixels**
    are lit (majority rule).  This preserves glyph distinction (e.g. ``B`` vs
    ``8``) better than the OR rule which collapses them at ~5px, while still
    retaining enough stroke fidelity for the small display.

    A 2px-wide stroke in the source covers 2xN blocks along its length; after
    majority downsampling it registers as 1px-wide — the thinnest reproducible
    feature at half scale.  1px-wide source strokes (thin serifs, the crossbar
    of ``A``) may vanish, but at ~5px display height they are illegible anyway.
    """
    rows = [i for i in range(16) if any(mat[i])]
    cols = [j for j in range(16) if any(mat[i][j] for i in range(16))]
    out = [[0] * 16 for _ in range(16)]
    if not rows:
        return out  # blank (e.g. space)
    r0, r1, c0, c1 = rows[0], rows[-1], cols[0], cols[-1]
    h, w = r1 - r0 + 1, c1 - c0 + 1
    for R in range((h + 1) // 2):
        for C in range((w + 1) // 2):
            count = 0
            for dr in range(2):
                for dc in range(2):
                    sr, sc = r0 + R * 2 + dr, c0 + C * 2 + dc
                    if sr <= r1 and sc <= c1 and mat[sr][sc]:
                        count += 1
            out[R][C] = 1 if count >= 2 else 0
    return out


def _pack_upright(mat: list[list[int]]) -> bytes:
    """Pack a 16x16 0/1 matrix as 2 bytes/row, MSB = leftmost pixel."""
    out = bytearray()
    for row in mat:
        val = 0
        for x in range(16):
            if row[x]:
                val |= 1 << (15 - x)
        out.append((val >> 8) & 0xFF)   # high byte first (MSB-left, big-endian row)
        out.append(val & 0xFF)
    return bytes(out)


def extract(src: Path, dst: Path, *, half: bool = False) -> int:
    blob = src.read_bytes()
    out = bytearray()
    for cp in range(FIRST_CP, LAST_CP + 1):
        if cp == FIRST_CP:  # space — blank cell
            out += b"\x00" * GLYPH_BYTES
            continue
        mat = _decode_apk_glyph(blob, cp)
        if half:
            mat = _halve(mat)
        out += _pack_upright(mat)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    return LAST_CP - FIRST_CP + 1


DEFAULT_DST_HALF = REPO / "divoom_lib" / "fonts" / "divoom_fond16_default_half.bin"


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else DEFAULT_SRC
    dst = Path(argv[2]) if len(argv) > 2 else DEFAULT_DST
    if not src.exists():
        print(f"source font not found: {src}", file=sys.stderr)
        return 1
    n = extract(src, dst)
    print(f"wrote {n} glyphs ({dst.stat().st_size} bytes) -> {dst}")
    # Always emit the half-size variant alongside the full one.
    half_dst = Path(argv[3]) if len(argv) > 3 else DEFAULT_DST_HALF
    extract(src, half_dst, half=True)
    print(f"wrote {n} glyphs ({half_dst.stat().st_size} bytes) -> {half_dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
