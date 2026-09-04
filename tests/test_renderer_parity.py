"""Renderer parity: what the DEVICE gets vs what the GUI used to draw.

R70 P1.4. Before the widget previews are rerouted through the daemon (P3), the
difference each reroute will make is measured here, so the visible change is a
recorded decision rather than something a user discovers.

**The tie-break rule, stated once.** Where the Rust renderer and the Python one
disagree, the DEVICE-FACING implementation wins — not the newer one, and not
the one that is more convenient to keep. The invariant being restored is
"preview == device", so whichever code actually pushes pixels to the matrix is
by definition correct, and the other is the copy that drifted.

That is NOT a reversal of the R67 finding that "Python was right every time".
That finding is about WIRE FORMATS — which bytes the device protocol expects —
and it still holds; `tools/check_weather_parity.py` exists to keep it holding.
Rendered CONTENT is a different question with a different authority: the daemon
draws what the device shows, so for pixels the daemon is ground truth and
`divoom_lib`'s renderers are reference implementations nothing pushes.

**The measured result, which is not subtle.** For album art the GUI preview and
the device frame disagree on 100% of pixels on hard-edged input — not a drift, a
different picture — because the GUI resamples LANCZOS and the device pipeline
uses NEAREST. See `test_the_album_art_filters_disagree_on_every_pixel`.
"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import subprocess
import time

import pytest


# ── a daemon, without the radio ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def daemon_socket():
    """A real `divoomd` on a private socket.

    `render_widget` touches no Bluetooth, but a BLE-linked daemon started from a
    shell has no macOS TCC grant and dies on its first scan — see the hardware
    note in docs/SESSION_HANDOFF.md. Nothing here scans, so the ordinary binary
    is fine; it is resolved BY VERSION (R69) rather than by path.
    """
    from tests.support.daemon_binary import require_divoomd

    bin_path = require_divoomd()
    sock = f"/tmp/divoomd_r70_parity_{os.getpid()}.sock"
    if os.path.exists(sock):
        os.remove(sock)
    proc = subprocess.Popen([str(bin_path), "--socket", sock],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(60):
            if os.path.exists(sock):
                break
            time.sleep(0.1)
        else:
            proc.kill()
            pytest.fail("divoomd did not bind its socket")
        yield sock
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(sock):
            os.remove(sock)


def call(sock: str, command: str, args: dict) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30)
    s.connect(sock)
    try:
        s.sendall((json.dumps({"command": command, "args": args}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    return json.loads(buf.split(b"\n")[0])


# ── fixtures that can actually show a difference ─────────────────────────────

def hard_edged_cover(size: int = 64):
    """A cover with an edge at every block boundary.

    Deliberately not a gradient: NEAREST and LANCZOS agree on smooth data, so a
    photo-like fixture would let the filter difference through and the test
    would pass on a broken build. Calibrating the instrument before trusting it
    is the whole reason this fixture is described rather than just used.
    """
    from PIL import Image
    img = Image.new("RGB", (size, size))
    for y in range(size):
        for x in range(size):
            on = ((x // 4) + (y // 4)) % 2 == 0
            img.putpixel((x, y), (255, 255, 255) if on else (10, 20, 200))
    return img


def as_png_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def pixels_differing(a: bytes, b: bytes) -> int:
    assert len(a) == len(b)
    return sum(1 for i in range(0, len(a), 3) if a[i:i + 3] != b[i:i + 3])


# ── album art: the decision P3.2 rests on ────────────────────────────────────

def test_the_album_art_filters_disagree_on_every_pixel(daemon_socket):
    """The magnitude of what P3.2 changes, measured rather than asserted.

    `media_sync._artwork_preview` resizes LANCZOS; the daemon's music job pushes
    through `image_proc::process_image_bytes`, which is NEAREST. The preview and
    the matrix have therefore been showing different pictures — under a
    docstring that reads "Uses the same renderer path the device frame comes
    from, so the card and the panel cannot drift".
    """
    from PIL import Image

    src = hard_edged_cover(64)
    reply = call(daemon_socket, "render_widget", {
        "kind": "album_art", "size": 16,
        "params": {"image_b64": as_png_b64(src)},
    })
    assert reply.get("success"), reply
    device = base64.b64decode(reply["frame_rgb_b64"])
    gui = src.resize((16, 16), Image.LANCZOS).convert("RGB").tobytes()

    differing = pixels_differing(device, gui)
    assert differing == 256, (
        f"expected the two filters to disagree everywhere on hard-edged input; "
        f"{differing}/256 pixels differ")


def test_the_daemon_album_art_filter_is_nearest(daemon_socket):
    """Names the filter rather than trusting the Rust source comment.

    `image_proc.rs` says NEAREST; this proves the shipped binary agrees, which
    is what makes the P3.2 decision ("the device-facing filter wins") a decision
    about a known quantity.
    """
    from PIL import Image

    src = hard_edged_cover(64)
    reply = call(daemon_socket, "render_widget", {
        "kind": "album_art", "size": 16,
        "params": {"image_b64": as_png_b64(src)},
    })
    assert reply.get("success"), reply
    device = base64.b64decode(reply["frame_rgb_b64"])
    assert device == src.resize((16, 16), Image.NEAREST).convert("RGB").tobytes()


def test_the_fixture_can_show_a_difference_at_all(daemon_socket):
    """Calibration: on a FLAT image the two filters agree, so a flat fixture
    would make the tests above pass no matter what the daemon did. This pins
    the reason the checkerboard is required."""
    from PIL import Image

    flat = Image.new("RGB", (64, 64), (120, 30, 200))
    reply = call(daemon_socket, "render_widget", {
        "kind": "album_art", "size": 16, "params": {"image_b64": as_png_b64(flat)},
    })
    assert reply.get("success"), reply
    device = base64.b64decode(reply["frame_rgb_b64"])
    gui = flat.resize((16, 16), Image.LANCZOS).convert("RGB").tobytes()
    assert pixels_differing(device, gui) == 0, (
        "a flat fixture cannot distinguish the filters — which is why the real "
        "tests use a hard-edged one")


# ── sysmon: already migrated, so parity must HOLD ────────────────────────────

def test_sysmon_frame_is_the_daemons_own_renderer_at_every_size(daemon_socket):
    """Sysmon was fixed in R67/C2 and must stay fixed through the P1.2 refactor.

    Compared against the daemon's LEGACY command rather than against a Python
    redraw: both paths must produce a full frame of the requested size, and the
    Rust side additionally pins byte-identity against `render_sysmon` on the
    reply's own reported stats (see `render_widget.rs`).
    """
    for size in (16, 32, 64):
        new = call(daemon_socket, "render_widget", {"kind": "sysmon", "size": size})
        old = call(daemon_socket, "sysmon", {"size": size})
        assert new.get("success") and old.get("success")
        assert new["size"] == old["size"] == size
        assert len(base64.b64decode(new["frame_rgb_b64"])) == size * size * 3
        assert len(base64.b64decode(old["frame_rgb_b64"])) == size * size * 3


# ── stocks: the Python renderer still exists; it is not the device's ─────────

def test_the_python_stock_renderer_is_reference_only_not_the_devices():
    """`divoom_lib` renders a stock tile too — and nothing pushes it.

    The device gets `live_jobs/render.rs::render_stock` via the live job. The
    Python one is what `media_sync.apply_stock_ticker` draws for the GUI, which
    is exactly the second implementation P3.1 removes. Recorded here so the
    removal reads as intentional rather than as lost functionality.
    """
    from divoom_lib.utils import media_source
    assert hasattr(media_source, "render_stock_ticker_frame")
    assert hasattr(media_source, "fetch_stock_ticker")


def test_the_daemon_exposes_the_kinds_p3_will_route_to(daemon_socket):
    """P3 cannot route a panel to a kind the shipped daemon does not have."""
    for kind in ("sysmon", "album_art"):
        reply = call(daemon_socket, "render_widget", {"kind": kind, "size": 16,
                                                      "params": {}})
        # album_art without an image fails, but it must fail as a KNOWN kind.
        err = str(reply.get("error", ""))
        assert "unknown kind" not in err, f"{kind} is not a known kind: {err}"

    unknown = call(daemon_socket, "render_widget", {"kind": "nope", "size": 16})
    assert unknown.get("success") is False
    assert "unknown kind" in str(unknown.get("error", ""))
