"""R53 round 36 — persona pass (all findings LOW/latent — convergence).

- Display.show_clock(hot=True) sent 0x26 with an EMPTY payload, omitting the
  mandatory 1-byte enable flag → hot mode didn't reliably turn on.
- process_image used .get("duration", default), which keeps a present-but-zero
  duration → _clamp_ms floored it to 1ms → an unviewable strobe.
- cmd_set_temperature didn't range-validate before connecting → an out-of-range
  temp opened BLE then died with a raw ValueError traceback.
"""
import argparse
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))


# ── Uncle Bob: show_clock(hot=True) enable byte ─────────────────────────────

def test_show_clock_hot_sends_enable_byte():
    from divoom_lib.display import Display
    from divoom_lib.models import constants

    captured = []

    class _Comm:
        lan = None
        logger = __import__("logging").getLogger("t_show_clock")

        async def send_command(self, cmd, args):
            captured.append((cmd, list(args)))
            return True

    d = Display(_Comm())
    asyncio.run(d.show_clock(hot=True))
    assert captured == [("set hot", [constants.BOOLEAN_TRUE])], "0x26 must carry its enable byte"


# ── Linus: zero-duration GIF frames use the default, not a 1ms strobe ────────

def test_gif_zero_duration_uses_default(tmp_path):
    from PIL import Image
    from divoom_lib.utils.image_processing import process_image

    f0 = Image.new("RGB", (16, 16), (255, 0, 0))
    f1 = Image.new("RGB", (16, 16), (0, 255, 0))
    gif = tmp_path / "zero.gif"
    f0.save(gif, save_all=True, append_images=[f1], duration=0, loop=0)

    frames, n, _w, _h = process_image(str(gif), size=16)
    assert n >= 2, "the test GIF must keep both frames"
    durations = [fr[3] for fr in frames]
    assert all(d >= 1000 for d in durations), f"duration=0 must fall back to default, not 1ms: {durations}"


# ── Hashimoto: set-temperature validates before connecting ──────────────────

def test_set_temperature_validates_before_connecting():
    from divoom_lib.cli_commands import cmd_set_temperature

    ns = argparse.Namespace(temperature=999, weather="sunny", json=False,
                            mac=None, address=None, name=None)
    with pytest.raises(SystemExit) as ei:
        asyncio.run(cmd_set_temperature(ns))
    assert ei.value.code == 2, "out-of-range temp must be a clean usage error (exit 2), not a traceback"
