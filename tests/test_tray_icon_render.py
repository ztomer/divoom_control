"""The offscreen tray-glyph renderer must draw the REAL glyph.

`tools/render_tray_icon.py` once reproduced `draw_icon` in Python and
byte-checked it against the Rust. The check held for the pixels and still let
the reproduction's STATE TABLE drift (three states in grey/green/red, where the
agent has four in other colours), and the P7.1 design was argued over that
table. So there is no reproduction now: the tool compiles
`divoom-menubar/src/glyph.rs` + `state.rs` into a probe and draws what it
prints. These tests pin that it does, that every state arrives, and that a
missing source file fails the tool instead of silently drawing nothing.

The distinctness gate itself (every pair of states differs in greyscale, on a
light and a dark bar, at 2x and 1x, and with colour removed) is Rust, beside
the renderer: `glyph::tests` in divoom-menubar.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

render = pytest.importorskip("render_tray_icon")

needs_cargo = pytest.mark.skipif(
    shutil.which("cargo") is None, reason="cargo is needed to compile the real glyph"
)


def _icon_states() -> list[str]:
    src = (REPO / "divoom-menubar" / "src" / "state.rs").read_text()
    body = re.search(r"pub enum IconState \{(.*?)\n\}", src, re.S)
    assert body is not None, "IconState not found in state.rs"
    return re.findall(r"^\s{4}(\w+),", body.group(1), re.M)


@pytest.fixture(scope="module")
def glyphs():
    return render.rust_glyphs()


@needs_cargo
def test_probe_draws_every_icon_state(glyphs):
    states = _icon_states()
    assert len(states) >= 4, states
    assert sorted(glyphs) == sorted(states)


@needs_cargo
def test_menu_bar_shows_it_at_18pt_wide_and_exactly_2x(glyphs):
    """The size decision of 2026-10-05, pinned on the real bitmap.

    tray-icon 0.26 shrinks a bitmap taller than 22pt to 22pt and leaves a
    shorter one at its pixel size, so the canvas is sized for the cap to land
    on exactly 2 px per point while the item keeps v0.40's 18pt width.
    """
    for w, h, rgba in glyphs.values():
        assert len(rgba) == w * h * 4
        wpt, hpt = render.display_pt(w, h)
        assert (wpt, hpt) == (18.0, 22.0)
        assert w / wpt == 2.0 and h / hpt == 2.0


@needs_cargo
def test_sheet_renders_every_state_on_both_bars(glyphs, tmp_path):
    out = tmp_path / "sheet.png"
    w, h = render.render_sheet(out, glyphs)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert w == render.CELL_W_PT * render.SHEET_SCALE * len(render.COLUMNS) * render.ZOOM
    assert h == render.BAR_H_PT * render.SHEET_SCALE * len(glyphs) * render.ZOOM
    assert {bar for bar, *_ in render.COLUMNS} == {"light", "dark"}


def test_probe_refuses_when_the_glyph_source_is_gone(tmp_path):
    """A rename in divoom-menubar must fail the tool, not draw a stale glyph."""
    (tmp_path / "divoom-menubar" / "src").mkdir(parents=True)
    (tmp_path / "divoom-menubar" / "src" / "state.rs").write_text("")
    with pytest.raises(render.ProbeError, match="glyph.rs is gone"):
        render.rust_glyphs(tmp_path)


def test_resampling_does_not_invent_a_dark_fringe():
    """Instrument check: white on transparent must stay white at every alpha.

    Straight-alpha interpolation blends the transparent pixels' black into the
    edge; that drew an outline round the glyph on light sheets that no menu bar
    shows.
    """
    white, clear = bytes((255, 255, 255, 255)), bytes(4)
    out = render.upscale(white + clear, 2, 1, 7, 1)
    for x in range(7):
        r, g, b, a = out[x * 4 : x * 4 + 4]
        if a:
            assert (r, g, b) == (255, 255, 255), (x, r, g, b, a)
