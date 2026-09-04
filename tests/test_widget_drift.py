"""For EVERY widget kind, the preview bytes and the pushed bytes are one call.

R70 P3.4. This is the class-level test, and the reason it is written at the
class level is that the per-widget version already failed once: R67/C2 fixed
sysmon's preview properly, asserted it properly, and stocks and album art kept
their second renderer for another two rounds because nothing said "all of
them".

**Kinds are enumerated from the daemon**, not listed here. A kind added to
`render_widget::KINDS` is covered without anyone remembering to add a case,
which is the only version of this test that survives the next widget.

**The shape of the comparison is deliberate**, and was learned the hard way in
P1.2. The first sysmon parity test compared two REPLIES to each other; CPU load
moves between calls, so the only assertions that survived were size and length,
and it passed with the renderer sabotaged to emit a solid block of 7s. A
comparison blind to the property it names is worse than none, because it
reports confidence. So each kind is checked by taking the bytes the daemon
returned and proving the GUI wrote exactly those — the one comparison a second
renderer cannot satisfy.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from divoom_client.daemon_protocol import DaemonClient
from divoom_gui.widget_frames import WidgetFrameMixin

REPO = Path(__file__).resolve().parent.parent


def daemon_kinds() -> list[str]:
    """The kinds the DAEMON declares, read from its own source.

    Deliberately not a literal list in this file: a hardcoded copy is a second
    source of truth about which widgets exist, which is the same class of
    defect the test is guarding against one level up.
    """
    src = (REPO / "divoomd" / "src" / "render_widget.rs").read_text()
    m = re.search(r'pub const KINDS: &\[&str\] = &\[(.*?)\];', src, re.S)
    assert m, "render_widget.rs no longer declares KINDS"
    return re.findall(r'"([a-z_]+)"', m.group(1))


def test_the_daemon_declares_the_kinds_this_round_migrated():
    """A floor, so the enumeration above cannot silently go empty and make
    every parameterised test below vacuous."""
    kinds = daemon_kinds()
    assert {"sysmon", "stocks", "album_art"} <= set(kinds), kinds


class Recorder(WidgetFrameMixin):
    """Captures what the daemon returned, so the written PNG can be compared
    against it rather than against a second render."""

    def __init__(self, raw: bytes, size: int, kind: str, extras: dict | None = None):
        self.raw = raw
        payload = {
            "success": True, "kind": kind, "size": size,
            "frame_rgb_b64": base64.b64encode(raw).decode(),
        }
        payload.update(extras or {})

        class _Client:
            def render_widget(_self, k, size=16, params=None):
                return payload

        self._fake = _Client()

    def _client(self):
        return self._fake


def hard_edged(size: int) -> bytes:
    """Every pixel is an edge.

    A flat or gradient frame would survive a resample unchanged, so a test
    using one would pass on a build that quietly reintroduced a filter — the
    P1.4 calibration, applied here.
    """
    out = bytearray()
    for y in range(size):
        for x in range(size):
            out += b"\xff\x00\x80" if (x + y) % 2 == 0 else b"\x00\x40\xff"
    return bytes(out)


@pytest.mark.parametrize("kind", daemon_kinds())
def test_the_gui_writes_exactly_the_bytes_the_daemon_returned(kind):
    """One call, one set of pixels, for every kind the daemon knows."""
    from PIL import Image

    size = 16
    raw = hard_edged(size)
    _extras, path = Recorder(raw, size, kind)._widget_frame(kind, size)
    assert Image.open(path).convert("RGB").tobytes() == raw, (
        f"{kind}: the frame on screen is not the frame the daemon rendered")


@pytest.mark.parametrize("kind", daemon_kinds())
def test_no_kind_is_rendered_twice_at_different_sizes(kind):
    """Size is the daemon's answer, not the GUI's request.

    `clamp_size` lives daemon-side; a GUI that re-derived the size would be a
    second opinion about how big the device is, and the frame it wrote would
    not match the one the device gets.
    """
    from PIL import Image

    for size in (8, 16, 32):
        raw = hard_edged(size)
        _extras, path = Recorder(raw, size, kind)._widget_frame(kind, size)
        img = Image.open(path)
        assert img.size == (size, size), f"{kind} at {size}: wrote {img.size}"
        assert img.convert("RGB").tobytes() == raw


# ── the GUI has no renderer left to drift WITH ───────────────────────────────

def test_the_gui_package_constructs_no_pixels():
    """The structural half: `tools/check_gui_is_a_client.py` enforces this
    repo-wide, and this states the property in the language of the defect.

    Every finding in R70's renderer group began with one of these calls in
    `divoom_gui/`. `Image.frombytes` is the exception and the whole point — it
    cannot introduce a filter, a font, or a colour the device will not show.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "check_gui_is_a_client.py")],
        capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_widget_kinds_the_gui_asks_for_all_exist_in_the_daemon():
    """A GUI panel asking for a kind the daemon does not know renders an error
    where a widget should be — and would do it only at runtime, on the panel
    nobody opened during testing."""
    kinds = set(daemon_kinds())
    gui = REPO / "divoom_gui"
    asked: set[str] = set()
    for path in gui.rglob("*.py"):
        for m in re.finditer(r'_widget_frame\(\s*"([a-z_]+)"', path.read_text()):
            asked.add(m.group(1))
    assert asked, "no _widget_frame call sites found — has the funnel moved?"
    assert asked <= kinds, f"the GUI asks for kinds the daemon lacks: {asked - kinds}"
