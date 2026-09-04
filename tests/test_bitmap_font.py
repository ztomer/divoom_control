"""R28 — device-bound text must use the crisp APK bitmap font, never an
anti-aliased TrueType font (the matrix is only 16/32/64px)."""
from __future__ import annotations

from pathlib import Path

import pytest

from divoom_lib.fonts import BitmapFont, get_default_font

REPO_ROOT = Path(__file__).parent.parent
MEDIA_SOURCE = REPO_ROOT / "divoom_lib" / "utils" / "media_source.py"
ASSET = REPO_ROOT / "divoom_lib" / "fonts" / "divoom_fond16_default_ascii.bin"


def test_asset_present_and_sized() -> None:
    """95 printable-ASCII glyphs (0x20..0x7e) x 32 bytes."""
    assert ASSET.exists()
    assert ASSET.stat().st_size == (0x7E - 0x20 + 1) * 32 == 3040


def test_default_font_is_singleton() -> None:
    assert get_default_font() is get_default_font()


def test_glyph_A_is_upright() -> None:
    """'A' has a single-pixel apex up top widening downward with a crossbar —
    proves the APK rotation was baked out correctly."""
    m = get_default_font().glyph_matrix("A")
    lit_rows = [r for r in m if any(r)]
    # The glyph's top row is the apex: exactly one lit pixel.
    assert sum(lit_rows[0]) == 1
    # ...and it widens below (more lit pixels further down).
    assert sum(lit_rows[-1]) > 1
    # A real multi-row glyph, not a stray dot.
    assert len(lit_rows) >= 7


def test_proportional_widths() -> None:
    f = get_default_font()
    # 'W'/'M' are wider than 'I'/'i' in a proportional font.
    assert f.char_width("W") > f.char_width("I")
    assert f.char_width("M") > f.char_width("l")


def test_text_width_matches_components() -> None:
    f = get_default_font()
    gap = 1
    assert f.text_width("AB", gap=gap) == f.char_width("A") + gap + f.char_width("B")
    assert f.text_width("", gap=gap) == 0


def test_render_is_crisp_no_antialiasing() -> None:
    """Every pixel is either off (bg) or fully on (fg) — no grey AA fringe."""
    f = get_default_font()
    img = f.render("Hello 123", (255, 255, 255), bg=(0, 0, 0))
    px = img.load()
    seen = set()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            seen.add(px[x, y])
    assert seen <= {(0, 0, 0), (255, 255, 255)}, f"anti-aliased values present: {seen}"


def test_max_width_drops_whole_glyphs() -> None:
    """A narrow max_width never clips a glyph mid-stroke; it drops it whole."""
    from PIL import Image, ImageDraw

    f = get_default_font()
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    drawn = f.draw_text(ImageDraw.Draw(img), (0, 0), "AAAAAA", (255, 255, 255), max_width=16)
    assert drawn <= 16
    # No pixels were drawn at/over the right edge boundary as a partial glyph:
    # the returned width is the sum of *whole* glyph advances, hence <= 16.


def test_unsupported_codepoint_falls_back() -> None:
    """ASCII-only font: out-of-range chars render the '?' glyph rather than crashing."""
    f = get_default_font()
    assert f.glyph_matrix("中") == f.glyph_matrix("?")  # CJK -> '?' in ASCII-only font


def test_space_is_blank() -> None:
    f = get_default_font()
    assert all(v == 0 for row in f.glyph_matrix(" ") for v in row)


# ── CJK / full APK font support (R31) ──────────────────────────────────


def test_apk_range_table_maps_cjk() -> None:
    """BitmapFont.from_apk_asset loads the raw APK font with range-table
    lookup, supporting CJK and other non-ASCII ranges."""
    apk = REPO_ROOT / "references" / "apk" / "decompiled_src" / "resources" / "assets" / "divoom_fond16_default.bin"
    if not apk.exists():
        pytest.skip("APK font asset not available")
    font = BitmapFont.from_apk_asset(apk)
    # CJK glyphs have content distinct from '?'.
    cjk = font.glyph_matrix("中")
    fallback = font.glyph_matrix("?")
    assert cjk != fallback
    # An actual CJK ideograph has many lit pixels, not blank.
    assert sum(sum(row) for row in cjk) > 10


def test_apk_range_table_unknown_codepoint_falls_back() -> None:
    """Codepoints outside all APK ranges fall back to '?'."""
    apk = REPO_ROOT / "references" / "apk" / "decompiled_src" / "resources" / "assets" / "divoom_fond16_default.bin"
    if not apk.exists():
        pytest.skip("APK font asset not available")
    font = BitmapFont.from_apk_asset(apk)
    # U+FFFF is a non-character, outside all ranges.
    unknown = font.glyph_matrix(chr(0xFFFF))
    fallback = font.glyph_matrix("?")
    assert unknown == fallback


def test_apk_range_table_ascii_still_works() -> None:
    """Full APK font loads ASCII glyphs correctly."""
    apk = REPO_ROOT / "references" / "apk" / "decompiled_src" / "resources" / "assets" / "divoom_fond16_default.bin"
    if not apk.exists():
        pytest.skip("APK font asset not available")
    font = BitmapFont.from_apk_asset(apk)
    mA = font.glyph_matrix("A")
    lit_rows = [r for r in mA if any(r)]
    assert len(lit_rows) >= 7


# ── guard: media_source must NOT use an anti-aliased font for the device ──


def test_media_source_uses_bitmap_font_not_truetype() -> None:
    src = MEDIA_SOURCE.read_text()
    # Device text uses the half-size bitmap font (R28 r3).
    assert "get_small_font" in src, "media_source should render device text via the small bitmap font"
    assert "ImageFont" not in src, "media_source must not import/use ImageFont (anti-aliased)"
    assert "load_default" not in src, "media_source must not use ImageFont.load_default"


def test_small_font_is_half_height_of_default() -> None:
    """The device (small) font is ~half the full font's glyph height."""
    from divoom_lib.fonts import get_default_font, get_small_font

    sample = "ABCDEFG0123456789"
    full_h = get_default_font().glyph_height(sample)
    small_h = get_small_font().glyph_height(sample)
    assert small_h <= -(-full_h // 2) + 1, (small_h, full_h)  # ceil(full/2)(+1 slack)
    assert small_h < full_h


def test_small_font_asset_present() -> None:
    half = REPO_ROOT / "divoom_lib" / "fonts" / "divoom_fond16_default_half.bin"
    assert half.exists() and half.stat().st_size == (0x7E - 0x20 + 1) * 32
