"""Real chain: a wall push hands the bench one preview per panel (P6.5).

After a wall image push, `LightingApi.display_wall_image` asks the wall for
`get_last_previews` so the bench can draw each panel's cut. The Rust wall
never answered it -- the call was dropped when the Python wall was ported --
so the reply was `unsupported`, the GUI logged a warning, and every push came
back with `previews: {}`. The GUI's unit tests faked the call, which is how
that stayed green; `tests/test_bridge_commands_exist_in_daemon.py` now holds
every call the GUI makes to the daemon's own tables.

This drives the real `DivoomGuiAPI` (in `tests/e2e_gui_bridge.py`'s
subprocess) against a real `divoomd` with two mock panels, with no fake in
between, and decodes what comes back: each panel's preview is that panel's
half of the image.
"""
from __future__ import annotations

import base64
import io
import json
import os
import urllib.request

import pytest

from tests.support.daemon_binary import find_divoomd
from tests.support.gui_daemon_stack import IsolatedStack

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"
WALL = "MatrixWall"
RED, BLUE = (220, 20, 20), (20, 20, 220)


@pytest.fixture
def stack():
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.skip("the real DivoomGuiAPI bridge needs a macOS GUI session; runs locally")
    bin_path = find_divoomd()
    if bin_path is None:
        pytest.skip("divoomd for this tree is not built (cargo build -p divoomd)")
    s = IsolatedStack(bin_path)
    try:
        for mac in (A, B):
            reply = s.client.send_command("connect", {"mock": True, "mac": mac, "name": "Ditoo-Plus"})
            assert reply.get("success") is True, reply
        yield s
    finally:
        s.close()


def _bridge(stack, method, *args):
    body = json.dumps({"method": method, "args": list(args)}).encode()
    req = urllib.request.Request(f"{stack.bridge_url}/call", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        reply = json.loads(r.read())
    assert "error" not in reply, reply
    return reply["result"]


def _colour_of(data_url: str):
    from PIL import Image
    head, body = data_url.split(";base64,", 1)
    img = Image.open(io.BytesIO(base64.b64decode(body))).convert("RGB")
    return head, img.size, set(img.getdata())


def test_a_wall_push_returns_each_panels_own_preview(stack, tmp_path):
    from PIL import Image
    picture = Image.new("RGB", (32, 16), BLUE)
    picture.paste(Image.new("RGB", (16, 16), RED), (0, 0))
    path = tmp_path / "wall.png"
    picture.save(path)

    # The bench lists its panels on load; that is what links the backend to
    # the daemon before anything is pushed.
    panels = json.loads(_bridge(stack, "get_panels"))
    assert sorted(p["mac"] for p in panels["panels"]) == [A, B], panels
    _bridge(stack, "update_wall_slots", json.dumps({
        A: {"x": 0, "y": 0, "size": 16}, B: {"x": 1, "y": 0, "size": 16}}))
    result = _bridge(stack, "display_wall_image", WALL, str(path), 16)

    assert result.get("success") is True, result
    previews = result.get("previews") or {}
    assert sorted(previews) == [A, B], f"one preview per panel, got {sorted(previews)}: {result}"
    for mac, colour in ((A, RED), (B, BLUE)):
        head, size, colours = _colour_of(previews[mac])
        assert head == "data:image/png", (mac, head)
        assert size == (16, 16), (mac, size)
        assert colours == {colour}, f"{mac} must preview its own half, got {colours}"
