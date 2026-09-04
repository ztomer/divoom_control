"""Crisp bitmap font for device-bound text (R28).

The Divoom LED matrix is only 16/32/64px across — anti-aliased TrueType text
(PIL ``ImageFont.load_default(size=...)``) turns to grey mush at that
resolution. Every string we rasterise and push to the device must therefore use
this 1-bit bitmap font, whose glyphs are the *exact* ones the official Divoom app
renders (extracted from the APK asset ``divoom_fond16_default.bin`` — see
``scripts/extract_apk_font.py`` for the format reverse-engineering + regen).

Bundled asset ``divoom_fond16_default_ascii.bin``: printable ASCII 0x20..0x7e,
one 16x16 1-bpp glyph per codepoint, 2 bytes/row, MSB = leftmost pixel, upright
(the rotation the APK stores is already baked out at extraction time). 95 glyphs
x 32 bytes = 3040 bytes.

Rendering is proportional (each glyph trimmed to its column bounding box, with a
configurable inter-glyph gap) and pixel-exact: a pixel is either fully on (the
requested colour) or untouched — there is no anti-aliasing, ever.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

_ASSET = Path(__file__).parent / "divoom_fond16_default_ascii.bin"
# Half-size variant (each glyph 2x-downsampled, same 16-cell format) for the tiny
# matrix — device-bound text uses this so it doesn't dominate a 16px screen.
_ASSET_HALF = Path(__file__).parent / "divoom_fond16_default_half.bin"

_CELL = 16
_GLYPH_BYTES = 32
_FIRST_CP = 0x20  # space
_LAST_CP = 0x7E   # ~
_FALLBACK_CP = 0x3F  # '?' for unsupported codepoints

# Codepoint range table matching the APK's CmdManager / F2.d internal table.
# Each entry is (start_inclusive, end_inclusive).  Used by BitmapFont when
# loading a full APK asset (via ``from_apk_asset`` / ``range_table=...``).
APK_RANGES: list[tuple[int, int]] = [
    (0x21, 0x7E),
    (0xA1, 0x2AF),
    (0x370, 0x52F),
    (0x600, 0x6FF),
    (0x750, 0x77F),
    (0xE00, 0xE7F),
    (0x1100, 0x11FF),
    (0x1E00, 0x1FFF),
    (0x2E80, 0x2FDF),
    (0x2FF0, 0x2FFF),
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x3130, 0x318F),
    (0x31C0, 0x31EF),
    (0x31F0, 0x331F),
    (0x4E00, 0x9FA5),
    (0xAC00, 0xD8AF),
    (0xFF00, 0xFFEF),
]


class BitmapFont:
    """A 16px 1-bit bitmap font loaded from a bundled APK-derived blob."""

    CELL = _CELL
    SPACE_WIDTH = 3  # blank advance for ' ' (px)

    def __init__(self, path: Optional[Path] = None,
                 range_table: Optional[list[tuple[int, int]]] = None,
                 expected_glyphs: Optional[int] = None) -> None:
        """Load a bitmap font.

        Parameters
        ----------
        path
            Path to a ``.bin`` glyph blob.  Defaults to the ASCII-only asset.
        range_table
            When provided, glyph lookup walks this range table (matching the
            APK's layout).  Without it, a contiguous flat range is assumed
            (backward-compatible with the ASCII-only extracted blobs).
        expected_glyphs
            Optional check: raise if the blob doesn't hold at least this many
            glyphs.  Ignored when ``range_table`` is set (the table itself
            defines the expected size).
        """
        blob = (path or _ASSET).read_bytes()
        if range_table is None and expected_glyphs is None:
            expected = (_LAST_CP - _FIRST_CP + 1) * _GLYPH_BYTES
            if len(blob) < expected:
                raise ValueError(
                    f"bitmap font {path or _ASSET} too small: {len(blob)} < {expected}"
                )
        if expected_glyphs is not None and range_table is None:
            expected = expected_glyphs * _GLYPH_BYTES
            if len(blob) < expected:
                raise ValueError(
                    f"bitmap font too small: {len(blob)} < {expected}"
                )
        self._blob = blob
        self._range_table = range_table

    @classmethod
    def from_apk_asset(cls, path: Path) -> BitmapFont:
        """Load a full raw APK font blob (with the range table).

        Unlike the extracted ASCII-only blobs, raw APK assets (e.g.
        ``references/apk/.../divoom_fond16_default.bin``) contain glyphs for
        *all* Unicode ranges used by the Divoom app — CJK, Hangul, Greek,
        Arabic, etc. — stored rotated and in APK-native order.
        This factory reads the blob, applies the APK range table for glyph
        lookup, and returns a BitmapFont that maps any supported codepoint
        (including CJK 0x4E00-0x9FA5) to its glyph.
        """
        return cls(path, range_table=APK_RANGES)

    # ── glyph access ───────────────────────────────────────────────────

    def _find_glyph_offset(self, cp: int) -> Optional[int]:
        """Walk the range table to find ``cp``'s byte offset in the blob.

        Returns ``None`` when the codepoint is not in any range (caller
        should fall back to ``?``).
        """
        if self._range_table is None:
            if _FIRST_CP <= cp <= _LAST_CP:
                return (cp - _FIRST_CP) * _GLYPH_BYTES
            return None
        offset = 0
        for start, end in self._range_table:
            if cp < start:
                return None
            if cp <= end:
                return (offset + (cp - start)) * _GLYPH_BYTES
            offset += end - start + 1
        return None

    def _rows(self, ch: str) -> list[int]:
        """16 row bitmasks for ``ch`` (bit 15 = leftmost pixel)."""
        cp = ord(ch)
        off = self._find_glyph_offset(cp)
        if off is None:
            off = self._find_glyph_offset(_FALLBACK_CP)
            if off is None:
                return [0] * _CELL
        g = self._blob[off: off + _GLYPH_BYTES]
        return [(g[r * 2] << 8) | g[r * 2 + 1] for r in range(_CELL)]

    @staticmethod
    def _col_bbox(rows: list[int]) -> Optional[tuple[int, int]]:
        cols = [x for x in range(_CELL) if any((v >> (15 - x)) & 1 for v in rows)]
        return (cols[0], cols[-1]) if cols else None

    def glyph_matrix(self, ch: str) -> list[list[int]]:
        """16x16 list of 0/1 for ``ch`` (upright)."""
        rows = self._rows(ch)
        return [[(v >> (15 - x)) & 1 for x in range(_CELL)] for v in rows]

    # ── metrics ────────────────────────────────────────────────────────

    def char_width(self, ch: str) -> int:
        if ch == " ":
            return self.SPACE_WIDTH
        bb = self._col_bbox(self._rows(ch))
        return (bb[1] - bb[0] + 1) if bb else self.SPACE_WIDTH

    def text_width(self, text: str, *, gap: int = 1) -> int:
        """Pixel width of ``text`` when drawn proportionally with ``gap``."""
        if not text:
            return 0
        return sum(self.char_width(c) for c in text) + gap * (len(text) - 1)

    def glyph_height(self, text: str) -> int:
        """Tallest occupied row+1 across ``text`` (0 if blank)."""
        h = 0
        for ch in text:
            if ch == " ":
                continue
            rows = self._rows(ch)
            for r in range(_CELL - 1, -1, -1):
                if rows[r]:
                    h = max(h, r + 1)
                    break
        return h

    # ── rendering ──────────────────────────────────────────────────────

    def draw_text(self, draw, xy, text: str, fill, *, gap: int = 1,
                  max_width: Optional[int] = None) -> int:
        """Stamp ``text`` onto a ``PIL.ImageDraw`` at ``xy`` with crisp pixels.

        Proportional spacing; no anti-aliasing. If ``max_width`` is given, glyphs
        that would overflow it are dropped whole (never clipped mid-glyph) — the
        right call on a narrow matrix. Returns the pixel width drawn."""
        x0, y0 = xy
        x = x0
        for i, ch in enumerate(text):
            advance = gap if i else 0
            if ch == " ":
                if max_width is not None and (x + advance + self.SPACE_WIDTH - x0) > max_width:
                    break
                x += advance + self.SPACE_WIDTH
                continue
            rows = self._rows(ch)
            bb = self._col_bbox(rows)
            if bb is None:
                x += advance + self.SPACE_WIDTH
                continue
            c0, c1 = bb
            gw = c1 - c0 + 1
            if max_width is not None and (x + advance + gw - x0) > max_width:
                break
            x += advance
            for r in range(_CELL):
                v = rows[r]
                if not v:
                    continue
                yy = y0 + r
                for c in range(c0, c1 + 1):
                    if (v >> (15 - c)) & 1:
                        draw.point((x + (c - c0), yy), fill=fill)
            x += (c1 - c0 + 1)
        return x - x0

    def render(self, text: str, fill=(255, 255, 255), *, gap: int = 1,
               bg=(0, 0, 0), mode: str = "RGB"):
        """Render ``text`` to a tightly-cropped ``PIL.Image`` (height = 16)."""
        from PIL import Image, ImageDraw  # local import: PIL optional at import time

        w = max(1, self.text_width(text, gap=gap))
        img = Image.new(mode, (w, _CELL), bg)
        self.draw_text(ImageDraw.Draw(img), (0, 0), text, fill, gap=gap)
        return img


_default: Optional[BitmapFont] = None
_small: Optional[BitmapFont] = None


def get_default_font() -> BitmapFont:
    """Process-wide singleton for the full-size (~9px) device bitmap font."""
    global _default
    if _default is None:
        _default = BitmapFont()
    return _default


def get_small_font() -> BitmapFont:
    """Process-wide singleton for the half-size (~5px) device bitmap font.

    This is what we rasterise for the device — at 16/32px the full-size glyphs
    dominate the screen, so device-bound text uses the half-size variant."""
    global _small
    if _small is None:
        _small = BitmapFont(_ASSET_HALF)
    return _small
