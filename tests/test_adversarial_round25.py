"""R53.45 / R53.46 — round-25 adversarial fixes.

R53.45: Scoreboard.set_scoreboard had no bounds — an out-of-range score
(red_score.to_bytes(2,...)) raised OverflowError, and an out-of-byte on_off hit
bytes() → ValueError. Uncaught for any direct lib/daemon/LAN caller (the GUI's
number input doesn't enforce max=999 for typed values). Now clamped to 0–999 /
masked to a byte at the boundary.

R53.46: LightingApi._render_text_png mkstemp'd a temp PNG and called
canvas.save(); if save failed the file was orphaned because push_text's
caller-side `finally: unlink` never ran (png_path never bound). Now the temp is
unlinked on a save failure before re-raising.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_lib.tools.scoreboard import Scoreboard


# ── R53.45: scoreboard bounds ───────────────────────────────────────────────

def test_set_scoreboard_clamps_out_of_range_instead_of_crashing():
    captured = {}

    class _Divoom:
        logger = __import__("logging").getLogger("test_scoreboard")

        async def send_command(self, cmd, args):
            captured["args"] = list(args)
            return True

    sb = Scoreboard(_Divoom())
    # 99999 / -5 / on_off=256 must NOT raise (they did before: OverflowError).
    ok = asyncio.run(sb.set_scoreboard(256, 99999, -5))
    assert ok is True

    args = captured["args"]
    # [TOOL_TYPE_SCORE, on_off, red_lo, red_hi, blue_lo, blue_hi]
    assert args[1] == 0, "on_off masked to a byte (256 & 0xFF == 0)"
    assert args[2:4] == [0xE7, 0x03], "red clamped to 999 = 0x03E7 little-endian"
    assert args[4:6] == [0, 0], "negative blue clamped to 0"


def test_set_scoreboard_passes_valid_values_through():
    captured = {}

    class _Divoom:
        logger = __import__("logging").getLogger("test_scoreboard")

        async def send_command(self, cmd, args):
            captured["args"] = list(args)
            return True

    sb = Scoreboard(_Divoom())
    asyncio.run(sb.set_scoreboard(1, 10, 20))
    args = captured["args"]
    assert args[1] == 1
    assert args[2:4] == [10, 0]
    assert args[4:6] == [20, 0]


# ── R53.46: render-text temp cleanup on save failure ────────────────────────

