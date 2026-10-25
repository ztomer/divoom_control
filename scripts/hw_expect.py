#!/usr/bin/env python3
"""What the panel MUST show — derived from the daemon, never asserted here.

THE CLASS THIS FILE CLOSES
--------------------------
The hardware packet used to carry a hand-written description of what the
device shows, and the description went stale silently. The `weather` check
still said (2026-09-07): "the device CYCLES; it does NOT draw one combined
face ... the `weather` flag drives a temperature panel". The daemon's
renderer changed under it (P3.3 draws ONE combined icon+temperature frame),
so the packet asked a human to grade a WORKING widget FAIL — and the
packet's own comment admits it had already "graded a working command FAIL"
twice, for exactly this reason.

The observer that cannot observe was the problem: the packet wrote down what
the device should look like, and no gate could tell when that sentence
stopped being true. So the sentence is GONE. The expectation is now an
artifact the SYSTEM produced:

  * the frame the daemon itself PAINTED (its activity record's preview), and
  * the frame the daemon SAYS it renders (`render_widget`).

The operator compares the panel with a picture the daemon painted, saved next
to the run's report. There is nothing left in the packet to go stale.

What the machine can still do here:
  * the daemon painted a frame at all, and it is not a single-colour blank;
  * the frame is the panel's size;
  * how far the painted frame is from the daemon's own `render_widget` frame
    (an OBSERVATION, never a verdict: `sysmon` samples the CPU again, so the
    two frames differ by design).

What is left for the human: whether the panel's PHYSICAL pixels show that
frame — bezel, glass, colour, crop. Nothing on this machine can see a panel;
only the owner's eyes can.
"""
from __future__ import annotations

import base64
import binascii
import io
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

# The ONE instruction every frame-graded check shows. It says what to
# COMPARE, not what the picture looks like: a description of a picture is a
# claim about the future, and this file has to stay true.
PANEL_LOOK = (
    "the panel must show the frame the daemon itself painted — the picture "
    "saved below, printed as text. Judge the panel against THAT frame. This "
    "packet deliberately describes no picture: a description written here "
    "goes stale the moment the daemon's renderer changes, and a stale "
    "description grades a working widget FAIL."
)

# How long to wait for the daemon's FIRST frame of a job. The jobs paint on
# their own cadence (sysmon every 5s, weather every 15min) and the first one
# can take a moment; asking before the frame exists would grade the panel on
# the PREVIOUS check's picture.
FRAME_WAIT = 25.0
FRAME_POLL = 1.0

RAMP = " .:-=+*#%@"


@dataclass
class Expectation:
    """What the operator is told, and what the machine concluded."""

    text: str = ""
    verdict: str = ""      # "", "FAIL" or "SKIP"
    detail: str = ""


def reply_of(client, command: str, args: dict | None = None) -> dict:
    """One socket command, as a dict. Never raises: a dead socket is an answer."""
    try:
        reply = client.send_command(command, args or {})
    except Exception as exc:                      # noqa: BLE001 — a dead socket IS the answer
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(reply, dict):
        return reply
    return {"success": False, "error": f"non-dict reply: {reply!r}"}


def activity(client, mac: str) -> dict:
    """The daemon's own record of what `mac` is showing."""
    reply = reply_of(client, "get_device_activity")
    records = reply.get("activity") or {}
    record = records.get(mac) if isinstance(records, dict) else None
    return record if isinstance(record, dict) else {}


def decode_data_url(url: str) -> bytes | None:
    """'data:image/png;base64,AAA...' -> the PNG bytes."""
    if not url:
        return None
    payload = url.split(",", 1)[1] if url.startswith("data:") and "," in url else url
    try:
        return base64.b64decode(payload)
    except (binascii.Error, ValueError):
        return None


def painted_png(client, mac: str, kind: str = "", wait: float = 0.0,
                poll: float = FRAME_POLL) -> tuple[bytes | None, dict]:
    """The PNG the daemon last PAINTED on `mac`, and the activity record.

    `kind` asks for one activity kind. A job that has not painted yet leaves
    the PREVIOUS check's record in place, and grading that as this check's
    picture would be grading the wrong thing — so the wait only accepts a
    record of the kind we asked for.
    """
    attempts = max(1, int(wait / poll) + 1)
    record: dict = {}
    for attempt in range(attempts):
        record = activity(client, mac)
        preview = decode_data_url(str(record.get("preview") or ""))
        if preview and (not kind or record.get("kind") == kind):
            return preview, record
        if attempt + 1 < attempts:
            time.sleep(poll)
    return None, record


def rendered_png(client, kind: str, size: int = 16,
                 params: dict | None = None) -> bytes | None:
    """The PNG the daemon SAYS it renders for `kind` — its own `render_widget`."""
    args: dict = {"kind": kind, "size": size}
    if params:
        args["params"] = params
    reply = reply_of(client, "render_widget", args)
    if reply.get("success") is False:
        return None
    b64 = reply.get("frame_rgb_b64")
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return None
    if len(raw) < size * size * 3:
        return None
    return raw_to_png(raw[:size * size * 3], size)


def raw_to_png(rgb: bytes, size: int) -> bytes:
    """A PNG of a size x size RGB buffer — written by hand, so this module
    needs no imaging library to produce evidence."""
    stride = size * 3
    rows = b"".join(
        b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(size)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))


def _pixels(png: bytes):
    """(size, pixel list) of a PNG — the imaging library's job."""
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    return im.size, list(im.get_flattened_data())


def stats(png: bytes) -> dict:
    """What is knowable about a frame without looking at a panel."""
    (w, h), pixels = _pixels(png)
    colours = len(set(pixels))
    return {"size": (w, h), "colours": colours, "blank": colours <= 1,
            "pixels": len(pixels)}


def diff_png(a: bytes, b: bytes) -> tuple[int, int]:
    """(differing pixels, total pixels) between two frames."""
    (aw, ah), ap = _pixels(a)
    (bw, bh), bp = _pixels(b)
    if (aw, ah) != (bw, bh) or len(ap) != len(bp):
        return -1, len(ap)
    return sum(1 for x, y in zip(ap, bp) if x != y), len(ap)


def ascii_art(png: bytes) -> str:
    """The frame as text, so the operator can compare without a viewer."""
    (w, h), pixels = _pixels(png)
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b = pixels[y * w + x]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            row.append(RAMP[min(len(RAMP) - 1, int(lum * len(RAMP) / 256))])
        lines.append("".join(row))
    return "\n".join(lines)


def save_png(png: bytes, directory, name: str) -> str:
    """Save the evidence next to the run's report, and say where it went."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    path.write_bytes(png)
    return str(path)


def describe(png: bytes, path: str = "") -> str:
    """The operator's text: what the frame is, and what it looks like."""
    info = stats(png)
    w, h = info["size"]
    lines = [f"the daemon painted a {w}x{h} frame"
             f" ({info['colours']} distinct colours"
             f"{', BLANK' if info['blank'] else ''})"]
    if path:
        lines.append(f"saved: {path}")
    lines.append("as text:")
    lines.append(ascii_art(png))
    return "\n".join(lines)
