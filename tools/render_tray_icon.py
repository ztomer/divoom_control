#!/usr/bin/env python3
"""Render the divoom-menubar tray glyph offscreen, the way the menu bar shows it.

WHY OFFSCREEN, AND WHY A COMMITTED TOOL
----------------------------------------
The glyph cannot be judged by screenshotting the live menu bar: the bar on a
real machine is FULL, so starting the agent shifts every other item and a
before/after diff measures congestion rather than the icon (verified that way
on 2026-10-05). So this renders the glyph in isolation, on a light and a dark
bar, at every size the menu bar gives it, in colour and in greyscale -- the
greyscale columns are the P7.1 question ("do the states differ by shape?")
asked by eye.

THE PIXELS ARE THE PRODUCT'S
----------------------------
This used to reproduce `draw_icon` in Python, byte-checked against the Rust.
The reproduction drifted anyway: its state table (Offline/Online/Error in
grey/green/red) was never the agent's (four states: Offline, Idle, Connected,
Degraded, in other colours), and the P7.1 design was decided over that table.
A preview that is a parallel implementation always drifts, so there is none
now: this compiles `divoom-menubar/src/glyph.rs` and `state.rs` themselves
into a throwaway probe (`#[path]`, no text extraction) and draws the bytes it
prints. The state list is `IconState::ALL`, so a new state appears here
without anyone editing this file.

Sheet layout: one row per state, columns left to right --
  dark bar 2x | dark bar 1x | dark bar 2x greyscale |
  light bar 2x | light bar 1x | light bar 2x greyscale
composited at the device scale (2x = Retina, 1x = a non-Retina display), then
enlarged with nearest-neighbour so each device pixel is visible.

Usage:
    python3 tools/render_tray_icon.py --out /tmp/tray.png
"""

from __future__ import annotations

import argparse
import json
import os
import math
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cargo_env import probe_env  # noqa: E402
from _tui import err, ok  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MARKER = "TRAYICON "


class ProbeError(RuntimeError):
    """The real glyph could not be built or read; the message says why."""


def rust_glyphs(root: Path | None = None) -> dict[str, tuple[int, int, bytes]]:
    """{state name: (w, h, rgba)} from the product's own `glyph::draw`."""
    src = (root or ROOT) / "divoom-menubar" / "src"
    for name in ("glyph.rs", "state.rs"):
        if not (src / name).is_file():
            raise ProbeError(f"{src / name} is gone -- the renderer is stale")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "src").mkdir()
        (d / "src" / "main.rs").write_text(
            f"#[path = {json.dumps(str(src / 'glyph.rs'))}]\nmod glyph;\n"
            f"#[path = {json.dumps(str(src / 'state.rs'))}]\nmod state;\n"
            + """
fn main() {
    for s in state::IconState::ALL {
        let (rgba, w, h) = glyph::draw(s.look());
        let hex: String = rgba.iter().map(|b| format!("{b:02x}")).collect();
        println!("TRAYICON {s:?} {w} {h} {hex}");
    }
}
"""
        )
        (d / "Cargo.toml").write_text(
            '[package]\nname = "probe"\nversion = "0.0.0"\nedition = "2021"\n'
        )
        # `tray_glyph_probe` exposes IconState::ALL outside cfg(test); see the
        # workspace lints in Cargo.toml.
        base = dict(os.environ)
        base["RUSTFLAGS"] = (base.get("RUSTFLAGS", "") + " --cfg tray_glyph_probe").strip()
        # The build stays in `d`, which this `with` removes; see _cargo_env.
        r = subprocess.run(
            ["cargo", "run", "--quiet"], capture_output=True, text=True, cwd=d, timeout=900,
            stdin=subprocess.DEVNULL, env=probe_env(d, base),
        )
    if r.returncode != 0:
        raise ProbeError("the glyph probe did not build:\n" + r.stderr[-2000:])
    out: dict[str, tuple[int, int, bytes]] = {}
    for line in r.stdout.splitlines():
        if not line.startswith(MARKER):
            continue
        name, w, h, hexs = line[len(MARKER):].split(" ")
        rgba = bytes.fromhex(hexs)
        if len(rgba) != int(w) * int(h) * 4:
            raise ProbeError(f"{name}: {len(rgba)} bytes is not {w}x{h} RGBA")
        out[name] = (int(w), int(h), rgba)
    if not out:
        raise ProbeError("the glyph probe printed no TRAYICON line:\n" + r.stdout[-2000:])
    return out


# ── a minimal PNG writer, so the tool needs no third-party imaging library ────
def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        raw += rgb[y * width * 3 : (y + 1) * width * 3]
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    path.write_bytes(png)


# ── compositing: bilinear resample, the way a menu bar scales a status item ──
def upscale(rgba: bytes, sw: int, sh: int, dw: int, dh: int) -> bytes:
    """Bilinear resample in PREMULTIPLIED alpha, as AppKit does.

    Interpolating straight alpha blends the colour of fully transparent pixels
    -- black, here -- into every edge, which drew a dark outline round the
    resampled glyphs that no real menu bar shows. On a light bar it made the
    near-white border look visible when it is not.
    """
    pm = [0.0] * (sw * sh * 4)
    for i in range(sw * sh):
        a = rgba[i * 4 + 3] / 255.0
        pm[i * 4] = rgba[i * 4] * a
        pm[i * 4 + 1] = rgba[i * 4 + 1] * a
        pm[i * 4 + 2] = rgba[i * 4 + 2] * a
        pm[i * 4 + 3] = float(rgba[i * 4 + 3])
    out = bytearray(dw * dh * 4)
    for y in range(dh):
        sy = (y + 0.5) * sh / dh - 0.5
        y0 = max(0, min(sh - 1, int(math.floor(sy))))
        y1 = max(0, min(sh - 1, y0 + 1))
        fy = max(0.0, min(1.0, sy - y0))
        for x in range(dw):
            sx = (x + 0.5) * sw / dw - 0.5
            x0 = max(0, min(sw - 1, int(math.floor(sx))))
            x1 = max(0, min(sw - 1, x0 + 1))
            fx = max(0.0, min(1.0, sx - x0))
            px = [0.0] * 4
            for c in range(4):
                px[c] = (
                    pm[(y0 * sw + x0) * 4 + c] * (1 - fx) * (1 - fy)
                    + pm[(y0 * sw + x1) * 4 + c] * fx * (1 - fy)
                    + pm[(y1 * sw + x0) * 4 + c] * (1 - fx) * fy
                    + pm[(y1 * sw + x1) * 4 + c] * fx * fy
                )
            a = px[3]
            o = (y * dw + x) * 4
            if a > 0.0:
                for c in range(3):
                    out[o + c] = max(0, min(255, int(round(px[c] * 255.0 / a))))
            out[o + 3] = int(round(a))
    return bytes(out)


def over(dst: bytearray, dw: int, src: bytes, sw: int, sh: int, ox: int, oy: int) -> None:
    for y in range(sh):
        for x in range(sw):
            si = (y * sw + x) * 4
            a = src[si + 3] / 255.0
            if a == 0.0:
                continue
            di = ((y + oy) * dw + (x + ox)) * 3
            for c in range(3):
                dst[di + c] = int(round(src[si + c] * a + dst[di + c] * (1 - a)))


# A status item's image is centred in the menu bar, drawn here as 24pt; the
# item itself is 22pt tall (`NSStatusBar.system.thickness` measured 22.0 on
# 2026-10-05). ZOOM only enlarges the result so each device pixel is visible.
BAR_H_PT = 24
CELL_W_PT = 26
ZOOM = 6
# Each column is drawn at 2 device px per point, so a 1x column is the glyph
# composited at 1x and then doubled, which is what a non-Retina display shows.
SHEET_SCALE = 2
# The flat approximations a screenshot of each bar settles on; the bars are
# translucent, and the point is the GLYPH's contrast against them. The same
# two values are the BARS in glyph.rs's distinctness gate.
BARS = {"dark": (0x2A, 0x2A, 0x2E), "light": (0xEC, 0xEC, 0xEC)}
# (bar, device px per pt, greyscale)
COLUMNS = [
    ("dark", 2, False), ("dark", 1, False), ("dark", 2, True),
    ("light", 2, False), ("light", 1, False), ("light", 2, True),
]
# tray-icon 0.26 keeps a bitmap's pixel height as its point height, shrinking
# only what is taller than this cap (macos/icon.rs `to_nsimage`).
HEIGHT_CAP_PT = 22.0


def display_pt(w: int, h: int, cap: float = HEIGHT_CAP_PT) -> tuple[float, float]:
    """The point size tray-icon gives a w x h px bitmap."""
    if h > cap:
        return w * cap / h, cap
    return float(w), float(h)


def _luma(r: int, g: int, b: int) -> int:
    return round(0.2126 * r + 0.7152 * g + 0.0722 * b)


def render_sheet(path: Path, glyphs: dict[str, tuple[int, int, bytes]]) -> tuple[int, int]:
    cell_w = CELL_W_PT * SHEET_SCALE
    cell_h = BAR_H_PT * SHEET_SCALE
    sheet_w = cell_w * len(COLUMNS)
    sheet_h = cell_h * len(glyphs)
    sheet = bytearray(sheet_w * sheet_h * 3)

    for r, (_name, (w, h, rgba)) in enumerate(glyphs.items()):
        wpt, hpt = display_pt(w, h)
        for c, (bar, scale, grey) in enumerate(COLUMNS):
            cell = bytearray(bytes(BARS[bar]) * (cell_w * cell_h))
            # Composite at the column's device scale...
            dw, dh = round(wpt * scale), round(hpt * scale)
            scaled = upscale(rgba, w, h, dw, dh)
            k = SHEET_SCALE // scale
            small_w, small_h = cell_w // k, cell_h // k
            small = bytearray(bytes(BARS[bar]) * (small_w * small_h))
            over(small, small_w, scaled, dw, dh, (small_w - dw) // 2, (small_h - dh) // 2)
            # ...then show each of its device pixels as k x k sheet pixels.
            for y in range(cell_h):
                for x in range(cell_w):
                    si = ((y // k) * small_w + (x // k)) * 3
                    cell[(y * cell_w + x) * 3 : (y * cell_w + x) * 3 + 3] = small[si : si + 3]
            for y in range(cell_h):
                for x in range(cell_w):
                    px = cell[(y * cell_w + x) * 3 : (y * cell_w + x) * 3 + 3]
                    if grey:
                        px = bytes([_luma(*px)] * 3)
                    di = ((r * cell_h + y) * sheet_w + c * cell_w + x) * 3
                    sheet[di : di + 3] = px

    zoomed = bytearray()
    for y in range(sheet_h):
        row = bytearray()
        for x in range(sheet_w):
            row += sheet[(y * sheet_w + x) * 3 : (y * sheet_w + x) * 3 + 3] * ZOOM
        zoomed += bytes(row) * ZOOM
    write_png(path, sheet_w * ZOOM, sheet_h * ZOOM, bytes(zoomed))
    return sheet_w * ZOOM, sheet_h * ZOOM


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "tray_icon_sheet.png"))
    args = ap.parse_args()
    try:
        glyphs = rust_glyphs()
    except ProbeError as e:
        err(str(e))
        return 2
    w, h = render_sheet(Path(args.out), glyphs)
    ok(f"wrote {args.out}  {w}x{h}px  rows {list(glyphs)}")
    print("  columns: dark 2x | dark 1x | dark 2x grey | light 2x | light 1x | light 2x grey")
    return 0


if __name__ == "__main__":
    sys.exit(main())
