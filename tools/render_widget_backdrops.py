#!/usr/bin/env python3
"""The four live widgets as a panel shows them, against a light AND a dark room (P9.3).

P9.3 asks whether the widgets read against a light and a dark surrounding. A
camera on this machine cannot see the bench (it counted 0 blue-dominant pixels
after a blue push), so this draws the evidence instead, from the daemon's own
frames: `render_widget` is byte-identical to what the panel is sent (P9.3's
2026-10-20 hardware round: weather 0 of 256 pixels differ), so nothing here is
a redrawing of the widget. Each 16x16 frame is laid out as LEDs on the panel's
black face, the face on a light (#f4f4f6) and a dark (#121316) backdrop, at a
real-scale pitch, and every frame is MEASURED: how many diodes carry ink (differ
from the frame's own ground), and how many of those are under 3:1 against it (an LED that dim is
lost in a lit room -- the WCAG 1.4.11 bar the GUI's own gate uses).

`custom_art` is not a render kind: it is the owner's picture downscaled
NEAREST (P9.3), so it is drawn here from the same source image with PIL's
nearest filter, and `album_art` is the daemon's `render_widget album_art`.

The daemon is a BLE-free `target/debug/divoomd` this tool starts under a
throwaway HOME and socket (it never reaches the radio or the owner's state).

Usage:
    cargo build -p divoomd --no-default-features
    python3 tools/render_widget_backdrops.py --out docs/assets/widget-backdrops.png
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DAEMON = REPO / "target" / "debug" / "divoomd"
SIZE = 16
PITCH, LED, BEZEL, PAD = 12, 10, 14, 24
FACE = (8, 8, 9)
BACKDROPS = {"light": (244, 244, 246), "dark": (18, 19, 22)}
MIN_RATIO = 3.0


def _lum(rgb: tuple[int, int, int]) -> float:
    def lin(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(a, b) -> float:
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _ask(sock: str, command: str, args: dict) -> dict:
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(20)
        s.connect(sock)
        s.sendall((json.dumps({"command": command, "args": args, "id": 1}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.split(b"\n")[0])


def _pixels(reply: dict) -> list[tuple[int, int, int]]:
    if not reply.get("success"):
        raise SystemExit(f"render_widget failed: {reply}")
    raw = base64.b64decode(reply["frame_rgb_b64"])
    return [tuple(raw[i : i + 3]) for i in range(0, len(raw), 3)]


def _cover(light: bool):
    """A synthetic album cover: a light one (a white field, a dark title) or a dark one."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (480, 480), (236, 232, 222) if light else (22, 24, 34))
    d = ImageDraw.Draw(img)
    d.ellipse((90, 90, 390, 390), fill=(200, 60, 40) if light else (60, 140, 220))
    d.rectangle((60, 400, 420, 440), fill=(30, 30, 30) if light else (230, 230, 230))
    return img


def _png_b64(img) -> str:
    out = io.BytesIO()
    img.save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode()


def frames(sock: str) -> list[tuple[str, list[tuple[int, int, int]]]]:
    out = [("sysmon", _pixels(_ask(sock, "render_widget", {"kind": "sysmon", "size": SIZE})))]
    for code, name in ((1, "clear"), (3, "cloudy"), (6, "rain"), (8, "snow")):
        for t in (23, -5):
            out.append(
                (
                    f"weather {name} {t}C",
                    _pixels(
                        _ask(
                            sock,
                            "render_widget",
                            {"kind": "weather", "size": SIZE, "params": {"temperature_c": t, "weather": code}},
                        )
                    ),
                )
            )
    for light in (True, False):
        cover = _cover(light)
        label = "light cover" if light else "dark cover"
        out.append(
            (
                f"album_art {label}",
                _pixels(
                    _ask(
                        sock,
                        "render_widget",
                        {"kind": "album_art", "size": SIZE, "params": {"image_b64": _png_b64(cover)}},
                    )
                ),
            )
        )
        from PIL import Image

        small = cover.resize((SIZE, SIZE), Image.Resampling.NEAREST)
        out.append((f"custom_art {label}", list(small.get_flattened_data())))
    return out


def judge(px: list[tuple[int, int, int]]) -> tuple[int, int]:
    """(ink, dim): diodes that differ from the frame's ground (its commonest
    colour -- the widgets paint a near-black ground, not 0), and how many of
    those are under 3:1 against that ground."""
    from collections import Counter

    ground = Counter(px).most_common(1)[0][0]
    ink = [p for p in px if p != ground]
    return len(ink), sum(1 for p in ink if _ratio(p, ground) < MIN_RATIO)


def _panel(px):
    from PIL import Image, ImageDraw

    side = SIZE * PITCH + 2 * BEZEL
    img = Image.new("RGB", (side, side), FACE)
    d = ImageDraw.Draw(img)
    for i, p in enumerate(px):
        x, y = BEZEL + (i % SIZE) * PITCH, BEZEL + (i // SIZE) * PITCH
        d.rectangle((x, y, x + LED - 1, y + LED - 1), fill=p if max(p) > 0 else (16, 16, 18))
    return img


def sheet(rows, out: Path) -> None:
    from PIL import Image, ImageDraw

    panel = _panel(rows[0][1])
    cols = 4
    cell_w, cell_h = panel.width + PAD, panel.height + PAD + 30
    lines = (len(rows) + cols - 1) // cols
    half_w = cols * cell_w + PAD
    img = Image.new("RGB", (2 * half_w, lines * cell_h + PAD), (0, 0, 0))
    for side, (theme, bg) in enumerate(BACKDROPS.items()):
        ImageDraw.Draw(img).rectangle((side * half_w, 0, (side + 1) * half_w - 1, img.height), fill=bg)
        ink = (40, 42, 48) if theme == "light" else (200, 202, 208)
        for i, (label, px) in enumerate(rows):
            x = side * half_w + PAD + (i % cols) * cell_w
            y = PAD + (i // cols) * cell_h
            img.paste(_panel(px), (x, y))
            lit, dim = judge(px)
            ImageDraw.Draw(img).text(
                (x, y + panel.height + 6), f"{label}  ink {lit}  dim {dim}", fill=ink, font_size=14
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def _start_daemon(tmp: Path) -> tuple[subprocess.Popen, str]:
    if not DAEMON.is_file():
        raise SystemExit(f"no {DAEMON}: cargo build -p divoomd --no-default-features")
    sock = str(tmp / "d.sock")
    env = dict(os.environ, HOME=str(tmp), DIVOOM_SOCKET=sock)
    proc = subprocess.Popen(
        [str(DAEMON), "--socket", sock],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        if Path(sock).exists():
            return proc, sock
        time.sleep(0.1)
    proc.kill()
    raise SystemExit("the daemon did not open its socket")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "docs" / "assets" / "widget-backdrops.png"))
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="widget-backdrops-") as t:
        proc, sock = _start_daemon(Path(t))
        try:
            rows = frames(sock)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    sheet(rows, Path(args.out))
    for label, px in rows:
        lit, dim = judge(px)
        print(f"  {label:24s} ink {lit:3d}  dim<{MIN_RATIO}:1 {dim:3d}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
