#!/usr/bin/env python3
"""Render the divoom-menubar tray icon offscreen, the way the menu bar sizes it.

WHY OFFSCREEN, AND WHY A COMMITTED TOOL
----------------------------------------
tray-icon 0.26 changed how a status-item bitmap becomes points: 0.24 forced
every icon to 18.0pt tall, 0.26 takes the pixel height as the point height and
only shrinks what exceeds a 22.0pt cap. The 22 px glyph v0.41.0 shipped
therefore grew from 18pt to 22pt (+22%), and stayed a 1x bitmap that every
Retina display resamples. No test can see that, and it cannot be checked by
screenshotting the live menu bar: the bar on a real machine is FULL, so starting
the agent shifts every other item and a before/after diff measures congestion
rather than the icon. Verified that way on 2026-10-05 -- a start/stop diff
produced a 190pt-wide, full-height cluster that was other items moving.

So this renders the icon in isolation, which is the only place the question can
actually be asked. It is committed rather than thrown away because the next
tray-icon bump moves the rule again, and the answer should be re-derivable in
one command instead of re-discovered.

The default sheet has one row per state and three columns, left to right:
v0.40 (the 22 px glyph forced to 18pt), v0.41.0 (the same bitmap at its natural
22pt), and the current glyph (36 x 44 px under the 22pt cap = 18 x 22pt at 2x).
Each is composited at 2 device pixels per point, as a Retina panel does, then
enlarged with nearest-neighbour so the device pixels stay visible.

FIDELITY
--------
`draw_icon` in divoom-menubar/src/tray.rs is reproduced here line for line: the
same W, H, UNITS, MARGIN, STROKE, SUBSAMPLES, the same supersample loop, the
same "half the covered samples on the band" border test, and the same integer
alpha `(coverage * 255 + cells / 2) / cells`. Divergence is not acceptable, so
`--verify-against-rust` builds a probe that runs the REAL function and compares
every pixel; `tests/test_tray_icon_render.py` asserts that check passes.

Usage:
    python3 tools/render_tray_icon.py --out /tmp/tray.png [--light]
    python3 tools/render_tray_icon.py --verify-against-rust
"""

from __future__ import annotations

import argparse
import math
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, ok  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# ── draw_icon's constants, verbatim from divoom-menubar/src/tray.rs ─────────
UNITS = 22.0
W = 36
H = 44
MARGIN = 3.0
STROKE = 2.2
BORDER = (0xF5, 0xF5, 0xF5)
SUBSAMPLES = 4

# The colours `IconState` uses. Read from tray.rs; Offline is what the agent
# shows before the daemon answers, so it is the state a user sees most.
STATE_COLORS = {
    "Offline": (0x8E, 0x8E, 0x93),
    "Online": (0x30, 0xD1, 0x58),
    "Error": (0xFF, 0x45, 0x50),
}


def draw_icon(rgb: tuple[int, int, int], w: int = W, h: int = H) -> bytearray:
    """The exact RGBA `draw_icon` produces. Mirrors the Rust line for line.

    `w`/`h` exist only so the sheet can also draw the v0.40/v0.41.0 bitmap
    (22 x 22, scale 1) for comparison; the verifier uses the defaults.
    """
    cells = SUBSAMPLES * SUBSAMPLES
    k = w / UNITS
    stroke = STROKE * k
    left = MARGIN * k
    radius = (UNITS / 2.0 - MARGIN) * k
    mid = left + radius
    cy = h / 2.0
    top = cy - radius
    bottom = cy + radius

    def inside_d(fx: float, fy: float) -> bool:
        in_rect = left <= fx <= mid and top <= fy <= bottom
        dx = fx - mid
        dy = fy - cy
        dist2 = dy * dy + dx * dx          # the Rust uses mul_add; same value
        in_bowl = fx >= mid and dist2 <= radius * radius
        return in_rect or in_bowl

    def is_border(fx: float, fy: float) -> bool:
        dx = fx - mid
        dy = fy - cy
        dist_from_arc = radius - math.hypot(dx, dy)
        near_left = (
            fx <= mid
            and abs(fx - left) <= stroke
            and top - stroke <= fy <= bottom + stroke
        )
        near_top = fx <= mid and abs(fy - top) <= stroke
        near_bottom = fx <= mid and abs(fy - bottom) <= stroke
        near_bowl = fx >= mid and abs(dist_from_arc) <= stroke
        return near_left or near_top or near_bottom or near_bowl

    rgba = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            coverage = 0
            border_weight = 0
            for sy in range(SUBSAMPLES):
                for sx in range(SUBSAMPLES):
                    fx = x + (sx + 0.5) / SUBSAMPLES
                    fy = y + (sy + 0.5) / SUBSAMPLES
                    if inside_d(fx, fy):
                        coverage += 1
                        if is_border(fx, fy):
                            border_weight += 1
            if coverage == 0:
                continue
            color = BORDER if border_weight * 2 >= coverage else rgb
            i = (y * w + x) * 4
            rgba[i], rgba[i + 1], rgba[i + 2] = color
            rgba[i + 3] = (coverage * 255 + cells // 2) // cells
    return rgba


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


def write_png_rgba(path: Path, width: int, height: int, rgba: bytes) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgba[y * width * 4 : (y + 1) * width * 4]
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
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
# 2026-10-05), which is why a 22pt glyph touches its edges. DEVICE is the Retina
# backing scale the bar is composited at; ZOOM only enlarges the result with
# nearest-neighbour so each device pixel is visible in the sheet.
BAR_H_PT = 24
DEVICE = 2
ZOOM = 6
CELL_W_PT = 34


def bar_rgb(light: bool) -> tuple[int, int, int]:
    # The menu bar is translucent over the wallpaper; these are the flat
    # approximations a screenshot settles on, and the point is the ICON's
    # contrast against each, not the bar's own texture.
    return (0xEC, 0xEC, 0xEC) if light else (0x2A, 0x2A, 0x2E)


def display_pt(w: int, h: int, forced: float | None, cap: float) -> tuple[float, float]:
    """The point size tray-icon gives a w x h px bitmap.

    0.24 forced the height (`forced`); 0.26 keeps the natural size and only
    shrinks what is taller than `cap` (macos/icon.rs `to_nsimage`).
    """
    if forced is not None:
        return w * forced / h, forced
    if h > cap:
        return w * cap / h, cap
    return float(w), float(h)


# (label, bitmap w, bitmap h, forced height or None, cap)
COLUMNS = [
    ("v0.40: 22px forced to 18pt", 22, 22, 18.0, 22.0),
    ("v0.41.0: 22px at 22pt", 22, 22, None, 22.0),
    (f"now: {W}x{H}px under the 22pt cap", W, H, None, 22.0),
]


def render_sheet(path: Path, states: list[str], light: bool) -> tuple[int, int]:
    bgc = bar_rgb(light)
    cell_w = CELL_W_PT * DEVICE
    cell_h = BAR_H_PT * DEVICE
    sheet_w = cell_w * len(COLUMNS)
    sheet_h = cell_h * len(states)
    sheet = bytearray(bytes(bgc) * (sheet_w * sheet_h))

    for r, state in enumerate(states):
        for c, (_label, w, h, forced, cap) in enumerate(COLUMNS):
            rgba = draw_icon(STATE_COLORS[state], w, h)
            wpt, hpt = display_pt(w, h, forced, cap)
            dw, dh = round(wpt * DEVICE), round(hpt * DEVICE)
            scaled = upscale(rgba, w, h, dw, dh)
            ox = c * cell_w + (cell_w - dw) // 2
            oy = r * cell_h + (cell_h - dh) // 2
            over(sheet, sheet_w, scaled, dw, dh, ox, oy)

    zoomed = bytearray()
    for y in range(sheet_h):
        row = bytearray()
        for x in range(sheet_w):
            row += sheet[(y * sheet_w + x) * 3 : (y * sheet_w + x) * 3 + 3] * ZOOM
        zoomed += bytes(row) * ZOOM
    write_png(path, sheet_w * ZOOM, sheet_h * ZOOM, bytes(zoomed))
    return sheet_w * ZOOM, sheet_h * ZOOM


def verify_against_rust() -> int:
    """Compare this reproduction against the REAL `draw_icon`, pixel for pixel.

    A reimplementation that has drifted is worse than no harness, because it
    answers confidently about the wrong glyph. So the reference is the product's
    own function: the exact text is lifted out of tray.rs at run time and
    compiled, so this check CANNOT pass against a stale copy. That is also why
    `draw_icon` was split from `make_icon` -- that returned a wrapped `tray_icon::Icon`, whose bytes
    are not reachable, so the drawing had to be separable to be checkable.

    `draw_icon` is private, so it is reached by extraction rather than by
    `pub`-ing it -- product code should not gain a visibility change for a
    harness. Its constants live inside the
    function body, so it is self-contained and needs no dependency at all.
    """
    src = (ROOT / "divoom-menubar" / "src" / "tray.rs").read_text()
    key = "fn draw_icon(rgb: [u8; 3])"
    if key not in src:
        err(f"draw_icon is gone from tray.rs -- the harness is stale ({key!r} not found)")
        return 2

    # Brace-match the function body; the constants are inside it.
    i = src.index(key)
    depth, j = 0, None
    for k in range(i, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                j = k + 1
                break
    if j is None:
        err("could not brace-match draw_icon in tray.rs")
        return 2
    fn_text = src[i:j]

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "src").mkdir()
        (d / "src" / "main.rs").write_text(
            fn_text
            + """

fn main() {
    let mut out = String::from("TRAYICON ");
    for (name, rgb) in [
        ("Offline", [0x8Eu8, 0x8Eu8, 0x93u8]),
        ("Online", [0x30u8, 0xD1u8, 0x58u8]),
        ("Error", [0xFFu8, 0x45u8, 0x50u8]),
    ] {
        let (rgba, _w, _h) = draw_icon(rgb);
        out.push_str(name);
        out.push(':');
        for b in rgba { out.push_str(&format!("{b:02x}")); }
        out.push('|');
    }
    println!("{out}");
}
"""
        )
        (d / "Cargo.toml").write_text(
            '[package]\nname = "probe"\nversion = "0.0.0"\nedition = "2024"\n'
        )
        r = subprocess.run(
            ["cargo", "run", "--quiet"], capture_output=True, text=True, cwd=d, timeout=900
        )
        if r.returncode != 0:
            err("the Rust probe did not build:\n" + r.stderr[-2000:])
            return 2

    # `cargo run` prints the payload on ONE line, prefixed so it is findable
    # even if a build warning ever lands on stdout. The name is separated by
    # the ':' the probe writes -- not by a fixed offset, because the three
    # state names are 7, 6 and 5 characters long, and slicing a fixed width
    # silently truncated "Error" by one byte and made the hex odd-length.
    marker = "TRAYICON "
    line = next(
        (l for l in reversed(r.stdout.splitlines()) if l.startswith(marker)), None
    )
    if line is None:
        err("the Rust probe printed no TRAYICON payload line:\n" + r.stdout[-2000:])
        return 2
    seen: set[str] = set()
    for chunk in line[len(marker):].split("|"):
        if not chunk:
            continue
        name, _, hexs = chunk.partition(":")
        if name not in STATE_COLORS or not hexs or len(hexs) % 2:
            err(f"malformed probe chunk {chunk[:40]!r}")
            return 2
        seen.add(name)
        rust = bytes.fromhex(hexs)
        mine = bytes(draw_icon(STATE_COLORS[name]))
        if rust == mine:
            ok(f"{name}: reproduction byte-identical to draw_icon ({len(mine)} bytes)")
            continue
        if len(rust) != len(mine):
            err(f"{name}: DIFFERS in size (rust={len(rust)} bytes, mine={len(mine)} bytes)")
            return 1
        diffs = [i for i, (a, b) in enumerate(zip(rust, mine)) if a != b]
        first = diffs[0]
        err(f"{name}: DIFFERS in {len(diffs)} byte(s); first at {first} "
            f"(rust={rust[first]} mine={mine[first]})")
        return 1
    # A probe that printed only some states would otherwise pass on the rest.
    missing = sorted(set(STATE_COLORS) - seen)
    if missing:
        err(f"the Rust probe printed no glyph for {missing}")
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "tray_icon_sheet.png"))
    ap.add_argument("--states", default=",".join(STATE_COLORS))
    ap.add_argument("--light", action="store_true", help="light menu bar instead of dark")
    ap.add_argument("--verify-against-rust", action="store_true")
    args = ap.parse_args()

    if args.verify_against_rust:
        return verify_against_rust()

    states = args.states.split(",")
    w, h = render_sheet(Path(args.out), states, args.light)
    print(f"wrote {args.out}  {w}x{h}px  rows {states} "
          f"({'light' if args.light else 'dark'} bar); columns, left to right:")
    for label, *_ in COLUMNS:
        print(f"  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
