"""The GUI has exactly ONE way to obtain a widget frame.

R70 P1.3. `_widget_frame` is a funnel, and a funnel is only worth building if
nothing can go around it — R67/C2 fixed sysmon's preview properly and the next
two widgets were written the old way anyway, because correctness-per-panel is a
habit and habits do not survive the next contributor.

So these tests check the two things that make it structural rather than
customary:

* the frame the GUI shows is the daemon's bytes, unaltered — pinned by
  comparing the written PNG's pixels against the raw RGB that came over the
  socket, which is the only comparison that can see a resample filter sneaking
  in (the album-art defect was exactly LANCZOS where the device used NEAREST);
* a failure raises the daemon's REASON, and the three causes stay
  distinguishable rather than collapsing into a blank tile.

`sysmon` is the widget under test because it is the one that already worked. If
the funnel is wrong, it should show up in the path with the most prior scrutiny,
not in the two being rewritten around it.
"""
from __future__ import annotations

import base64
import json
import socket
import os
import tempfile
import threading
import uuid

import pytest

from divoom_client.daemon_protocol import DaemonClient
from divoom_gui.widget_frames import WidgetFrameError, WidgetFrameMixin


class StubDaemon:
    """A real unix socket recording requests and replying with canned JSON."""

    def __init__(self, reply: dict):
        self.reply = reply
        self.requests: list[dict] = []
        self.path = os.path.join(
            tempfile.gettempdir(), f"divoom_wf_stub_{uuid.uuid4().hex[:8]}.sock")
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            with conn:
                buf = b""
                try:
                    while b"\n" not in buf:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    if buf:
                        self.requests.append(json.loads(buf.split(b"\n")[0]))
                        conn.sendall(json.dumps(self.reply).encode() + b"\n")
                except OSError:
                    pass

    def close(self) -> None:
        self._stop = True
        for fn in (self._srv.close, lambda: os.unlink(self.path)):
            try:
                fn()
            except OSError:
                pass


class Host(WidgetFrameMixin):
    """Minimal host class — the mixin's only requirement is a client."""

    def __init__(self, client):
        self._client = client


@pytest.fixture
def stub():
    made: list[StubDaemon] = []

    def _make(reply: dict):
        s = StubDaemon(reply)
        made.append(s)
        return s, Host(DaemonClient(socket_path=s.path))

    yield _make
    for s in made:
        s.close()


def _checkerboard(size: int) -> bytes:
    """Hard-edged RGB, deliberately.

    A gradient would let a resample filter through unnoticed — NEAREST and
    LANCZOS agree on smooth data. Every pixel here is a hard edge, so any
    resampling changes the bytes.
    """
    out = bytearray()
    for y in range(size):
        for x in range(size):
            out += b"\xff\xff\xff" if (x + y) % 2 == 0 else b"\x00\x00\x00"
    return bytes(out)


def _ok_reply(size: int = 16, **extras) -> dict:
    raw = _checkerboard(size)
    return {
        "success": True, "kind": "sysmon", "size": size,
        "frame_rgb_b64": base64.b64encode(raw).decode(),
        **extras,
    }


def test_sends_render_widget_with_the_kind_and_size(stub):
    s, host = stub(_ok_reply(16, cpu=1, mem=2, battery=3))
    host._widget_frame("sysmon", 16)
    assert s.requests[0]["command"] == "render_widget"
    assert s.requests[0]["args"]["kind"] == "sysmon"
    assert s.requests[0]["args"]["size"] == 16


def test_the_written_png_is_the_daemons_bytes_unaltered(stub):
    """The property the album-art defect violated.

    Comparing sizes would pass under a resample; comparing PIXELS is what
    catches a filter being applied on the way to the screen.
    """
    from PIL import Image
    size = 16
    raw = _checkerboard(size)
    s, host = stub(_ok_reply(size))
    _extras, path = host._widget_frame("sysmon", size)
    written = Image.open(path).convert("RGB").tobytes()
    assert written == raw


def test_extras_carry_the_kinds_own_fields(stub):
    s, host = stub(_ok_reply(16, cpu=42, mem=71, battery=88))
    extras, _path = host._widget_frame("sysmon", 16)
    assert extras["cpu"] == 42 and extras["mem"] == 71 and extras["battery"] == 88
    # Envelope fields are not "extras" — they describe the reply, not the widget.
    for k in ("success", "size", "kind", "frame_rgb_b64"):
        assert k not in extras


def test_a_truncated_frame_raises_rather_than_rendering_a_partial_buffer(stub):
    """A short draw looks like a design, not like an error."""
    short = base64.b64encode(_checkerboard(16)[:-30]).decode()
    s, host = stub({"success": True, "size": 16, "frame_rgb_b64": short})
    with pytest.raises(WidgetFrameError) as exc:
        host._widget_frame("sysmon", 16)
    assert "expected" in str(exc.value)


def test_a_daemon_error_is_raised_with_its_reason(stub):
    s, host = stub({"success": False, "error": "stocks: no quote for ZZZZ"})
    with pytest.raises(WidgetFrameError) as exc:
        host._widget_frame("stocks", 16, {"symbol": "ZZZZ"})
    assert "no quote for ZZZZ" in str(exc.value)


def test_an_absent_daemon_says_the_service_is_not_running():
    host = Host(DaemonClient(socket_path="/tmp/divoom_wf_definitely_absent.sock"))
    with pytest.raises(WidgetFrameError) as exc:
        host._widget_frame("sysmon", 16)
    assert "not running" in str(exc.value)


def test_params_are_forwarded(stub):
    s, host = stub(_ok_reply(16))
    host._widget_frame("stocks", 16, {"symbol": "AAPL"})
    assert s.requests[0]["args"]["params"] == {"symbol": "AAPL"}


def test_it_accepts_a_callable_client_as_sysmon_widget_provides(stub):
    """`sysmon_widget` exposes `self._client()`; the api layer exposes an
    attribute. Both must work, or the funnel needs a refactor to be adopted —
    and a funnel that is inconvenient is a funnel that gets bypassed."""
    s, _ = stub(_ok_reply(16, cpu=5, mem=6, battery=7))
    client = DaemonClient(socket_path=s.path)

    class CallableHost(WidgetFrameMixin):
        def _client(self):
            return client

    extras, _path = CallableHost()._widget_frame("sysmon", 16)
    assert extras["cpu"] == 5


# ── sysmon, the migrated widget, still behaves ───────────────────────────────

def test_sysmon_widget_reports_the_same_stats_through_the_funnel(stub):
    from divoom_gui.sysmon_widget import SysmonWidgetMixin

    s, _ = stub(_ok_reply(32, cpu=11, mem=22, battery=33))
    client = DaemonClient(socket_path=s.path)

    class Sysmon(SysmonWidgetMixin):
        def _client(self):
            return client

    stats, path = Sysmon()._sysmon_frame(32)
    assert stats == {"cpu": 11, "mem": 22, "battery": 33}
    assert path.exists()


def test_sysmon_asks_for_render_widget_now_not_the_legacy_command(stub):
    """The migration is the point of the step; if it silently kept using
    `sysmon` the funnel would be decorative."""
    from divoom_gui.sysmon_widget import SysmonWidgetMixin

    s, _ = stub(_ok_reply(16, cpu=1, mem=1, battery=1))
    client = DaemonClient(socket_path=s.path)

    class Sysmon(SysmonWidgetMixin):
        def _client(self):
            return client

    Sysmon()._sysmon_frame(16)
    assert s.requests[0]["command"] == "render_widget"
    assert s.requests[0]["args"]["kind"] == "sysmon"


def test_the_only_pil_call_in_the_funnel_is_frombytes():
    """`Image.frombytes` cannot introduce a filter, a font or a colour the
    device will not show. `new`/`open`/`resize` can, and each is how one of the
    R70 findings began — so the funnel is pinned to the one call that is a pure
    encode, by the same gate that guards the rest of the package."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "divoom_gui" / "widget_frames.py").read_text()
    assert "Image.frombytes" in src
    for forbidden in ("Image.new", "Image.open", ".resize(", "ImageDraw"):
        assert forbidden not in src, f"{forbidden} makes this a second renderer"
