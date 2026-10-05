"""The offscreen tray-icon renderer must draw the REAL glyph, byte for byte.

`tools/render_tray_icon.py` reproduces `draw_icon` (divoom-menubar/src/tray.rs)
in Python so the glyph can be judged at every size macOS may give it without
screenshotting a full menu bar. A reproduction that has drifted answers
confidently about the wrong glyph, so its `--verify-against-rust` mode compiles
the product's own function, lifted out of tray.rs at run time, and compares
every pixel. These tests keep that check green AND keep it able to fail.

The first version of the verifier could not pass: it sliced a fixed 8-character
state name off names 7, 6 and 5 characters long, and when that was fixed the
parser looked for a `TRAYICON ` prefix the probe never printed. Neither was
noticed because nothing ran it.
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
    shutil.which("cargo") is None, reason="cargo is needed to compile the real draw_icon"
)


def _rust_const(name: str) -> str:
    src = (REPO / "divoom-menubar" / "src" / "tray.rs").read_text()
    m = re.search(rf"const {name}: [^=]+ = ([^;]+);", src)
    assert m is not None, f"const {name} not found in tray.rs"
    return m.group(1).strip()


@needs_cargo
def test_reproduction_is_byte_identical_to_the_rust_glyph(capsys):
    assert render.verify_against_rust() == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    for state in render.STATE_COLORS:
        assert f"{state}: reproduction byte-identical" in out


@needs_cargo
def test_verifier_goes_red_when_the_reproduction_drifts(monkeypatch, capsys):
    """Calibration: a 0.1 change to one stroke constant must be caught."""
    monkeypatch.setattr(render, "STROKE", render.STROKE + 0.1)
    assert render.verify_against_rust() == 1
    assert "DIFFERS" in capsys.readouterr().err


def test_verifier_refuses_when_draw_icon_is_gone(monkeypatch, tmp_path, capsys):
    """A rename in tray.rs must fail the harness, not silently skip it."""
    (tmp_path / "divoom-menubar" / "src").mkdir(parents=True)
    (tmp_path / "divoom-menubar" / "src" / "tray.rs").write_text("fn make_icon() {}\n")
    monkeypatch.setattr(render, "ROOT", tmp_path)
    assert render.verify_against_rust() == 2
    assert "draw_icon is gone" in capsys.readouterr().err


def test_constants_match_tray_rs():
    """Cheap tripwire that runs without cargo; the byte check is the real one."""
    assert float(_rust_const("UNITS")) == render.UNITS
    assert int(_rust_const("W")) == render.W
    assert int(_rust_const("H")) == render.H
    assert float(_rust_const("MARGIN")) == render.MARGIN
    assert float(_rust_const("STROKE")) == render.STROKE
    assert int(_rust_const("SUBSAMPLES")) == render.SUBSAMPLES
    border = tuple(int(b, 16) for b in re.findall(r"0x[0-9a-fA-F]+", _rust_const("BORDER")))
    assert border == render.BORDER


def test_glyph_is_w_by_h_rgba():
    rgba = render.draw_icon(render.STATE_COLORS["Offline"])
    assert len(rgba) == render.W * render.H * 4


def test_menu_bar_shows_it_at_18pt_wide_and_exactly_2x():
    """The size decision of 2026-10-05, pinned.

    tray-icon 0.26 shrinks a bitmap taller than 22pt to 22pt and leaves a
    shorter one at its pixel size. A 22 px glyph therefore grew from v0.40's
    18pt to 22pt AND stayed 1x on Retina. The canvas is sized so the cap lands
    on exactly 2 px per point while the item keeps v0.40's 18pt width.
    """
    wpt, hpt = render.display_pt(render.W, render.H, None, 22.0)
    assert (wpt, hpt) == (18.0, 22.0)
    assert render.W / wpt == 2.0 and render.H / hpt == 2.0


def test_resampling_does_not_invent_a_dark_fringe():
    """Instrument check: white on transparent must stay white at every alpha.

    Straight-alpha interpolation blends the transparent pixels' black into the
    edge; that drew an outline round the glyph on light sheets that no menu bar
    shows, and made the near-white border look visible on a light bar.
    """
    white, clear = bytes((255, 255, 255, 255)), bytes(4)
    out = render.upscale(white + clear, 2, 1, 7, 1)
    for x in range(7):
        r, g, b, a = out[x * 4 : x * 4 + 4]
        if a:
            assert (r, g, b) == (255, 255, 255), (x, r, g, b, a)
