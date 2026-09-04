"""R60 #3 — pin show_clock() to the APK C2() canonical wire frame.

The device's 0x45 clock env frame reads overlay positions 4/5/6 as
humidity/weather/date (verified against decompiled APK CmdManager.java:316 C2
+ LightViewModel.java:222). show_clock() must emit exactly::

    [0x00, time_type, style, 0x01, humidity, weather, date, R, G, B]

Hardware-free: drives a fake communicator and asserts the captured payload.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divoom_lib.display import Display


class _FakeCommunicator:
    def __init__(self):
        self.sent = []
        self.lan = None
        self.logger = None

    async def send_command(self, name, payload):
        self.sent.append((name, list(payload)))
        return True

    def convert_color(self, color):
        h = color.lstrip("#")
        return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


def _show_clock(**kw):
    c = _FakeCommunicator()
    d = Display(c)
    asyncio.run(d.show_clock(**kw))
    return c.sent


def test_show_clock_default_is_canonical():
    sent = _show_clock()
    assert sent[-1][0] == "set light mode"
    assert sent[-1][1] == [0x00, 1, 0, 0x01, 0, 0, 0, 255, 255, 255]


def test_show_clock_overlays_canonical_order():
    sent = _show_clock(clock=3, twentyfour=True, humidity=True, weather=True, date=True, color="#ff0000")
    assert sent[-1][1] == [0x00, 1, 3, 0x01, 1, 1, 1, 255, 0, 0]


def test_show_clock_no_overlays_color_only():
    sent = _show_clock(clock=7, twentyfour=False, color="#00ff00")
    assert sent[-1][1] == [0x00, 0, 7, 0x01, 0, 0, 0, 0, 255, 0]
