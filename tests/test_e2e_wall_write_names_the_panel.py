"""Real chain: a wall write one panel did not take names that panel (P6.4).

P6.3 made the daemon name each wall panel whose write failed and the wall
image push said which. The other wall writes answered a bare true/false, so
on the wall the toast said "Failed to switch channel" with no panel named and
the daemon's reason reached only the log. Every display write now answers its
outcome through one funnel (`write_outcome`, `divoom_gui/api/__init__.py`) and
the page says it through one helper (`web_ui/display_write.js`).

No fake between the click and the panel: the real web UI, the real
`DivoomGuiAPI` (`tests/e2e_gui_bridge.py`) and a real `divoomd` with two mock
panels on a wall, Desk and Shelf, where Shelf takes no write (`connect`'s mock
`failing`). Each gesture below is the user's click; each must raise a toast
naming Shelf, with the reason, and not Desk.

The gestures are held to the enumeration in
`tests/test_wall_writes_name_the_panel.py`: every bridge method that writes
to the wall has one here, or a reason it has none.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, install_toast_recorder, launch, require_browser, wait_js, wait_toast
from tests.support.daemon_binary import find_divoomd
from tests.support.gui_daemon_stack import IsolatedStack

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"

_REAL_BRIDGE_API = """
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) =>
    fetch(window.__BRIDGE_URL__ + '/call', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: name, args: args}),
    }).then(r => r.json()).then(d => { if (d.error) throw new Error(d.error); return d.result; })
})};
"""

#: Each wall write's gesture, and the failure toast it raises.
GESTURES = {
    "switch_channel": ("Failed to switch channel",
                       "document.querySelector('.tab-btn[data-channel=\"vj\"]').click()"),
    "set_vj_effect": ("Failed to apply VJ effect",
                      "document.querySelector('#vj-effects-grid [data-value=\"2\"]').click()"),
    "set_visualization": ("Failed to apply EQ",
                          "document.querySelector('#eq-visualizer-grid [data-value=\"1\"]').click()"),
    "set_clock": ("Failed to apply clock",
                  "document.querySelector('#clock-faces-grid [data-value=\"2\"]').click()"),
    "set_clock_rich": ("Failed to apply clock", """(() => { const c = document.getElementById('clock-rich-date');
                       c.checked = true; c.dispatchEvent(new Event('change')); })()"""),
    "set_solid_light": ("Failed to apply ambient",
                        "document.querySelector('#ambient-mode-grid [data-value=\"0\"]').click()"),
    "push_text": ("Failed to push text", """(() => { document.getElementById('text-content-input').value = 'HI';
                  document.getElementById('push-text-btn').click(); })()"""),
    "set_scoreboard": ("Failed to set scoreboard", """(() => { const r = document.getElementById('scoreboard-red');
                       r.value = 3; r.dispatchEvent(new Event('change')); })()"""),
    # The deck's levels are the wall's while it is the display (P6.6).
    "set_brightness": ("The wall did not take the brightness", """(() => {
                       const s = document.getElementById('global-brightness-slider');
                       s.value = 40; s.dispatchEvent(new Event('change')); })()"""),
    "set_volume": ("The wall did not take the volume", """(() => {
                   const s = document.getElementById('appbar-volume-slider');
                   s.value = 7; s.dispatchEvent(new Event('change')); })()"""),
    "display_wall_image": ("Failed to split and sync wall image", """(() => {
                           document.getElementById('file-path-input').value = window.__IMAGE__;
                           document.getElementById('apply-wall-art').click(); })()"""),
}

#: Wall writes with no gesture here, and why. Each is held to the same reply
#: by the bridge-level enumeration.
NOT_FROM_THE_PAGE = {
    "apply_stock_ticker": "renders a live Yahoo quote first; the network is not part of this test",
    "play_gallery_art": "the gallery push is display_wall_image's, from a cached download",
}


def test_every_wall_write_has_a_gesture_or_a_reason(tmp_path):
    """Calibration of this file against the enumeration: no wall write is
    silently left out of the real-chain check."""
    from tests.support.bridge_calls import recorded_api
    from tests.test_wall_writes_name_the_panel import _FailingWall, _wall_writes
    with recorded_api(tmp_path) as api:
        api._daemon_client = _FailingWall()
        api.wall_slots = {A: {"x": 0, "y": 0, "size": 16}, B: {"x": 1, "y": 0, "size": 16}}
        found = set(_wall_writes(api))
    assert found == set(GESTURES) | set(NOT_FROM_THE_PAGE), (
        f"no gesture: {sorted(found - set(GESTURES) - set(NOT_FROM_THE_PAGE))}; "
        f"stale: {sorted((set(GESTURES) | set(NOT_FROM_THE_PAGE)) - found)}")


@pytest.fixture
def stack():
    require_browser()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.skip("the real DivoomGuiAPI bridge needs a macOS GUI session; runs locally")
    bin_path = find_divoomd()
    if bin_path is None:
        pytest.skip("divoomd for this tree is not built (cargo build -p divoomd)")
    s = IsolatedStack(bin_path)
    try:
        for mac, failing in ((A, False), (B, True)):
            reply = s.client.send_command(
                "connect", {"mock": True, "mac": mac, "name": "Ditoo-Plus", "failing": failing})
            assert reply.get("success") is True, reply
        yield s
    finally:
        s.close()


@pytest.mark.asyncio
async def test_each_wall_write_names_the_panel_that_did_not_take_it(stack, tmp_path):
    from PIL import Image
    from playwright.async_api import async_playwright

    image = tmp_path / "wall.png"
    Image.new("RGB", (32, 16), (200, 40, 10)).save(image)
    slots = {A: {"x": 0, "y": 0, "size": 16, "name": "Desk", "room": "wall"},
             B: {"x": 1, "y": 0, "size": 16, "name": "Shelf", "room": "wall"}}

    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await install_toast_recorder(page)
            await add_init_js(page, f"window.__BRIDGE_URL__ = {json.dumps(stack.bridge_url)};\n"
                              f"window.__IMAGE__ = {json.dumps(str(image))};\n" + _REAL_BRIDGE_API)
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.Divoom?.onOwnedDevices"
                                " && !!document.querySelector('#vj-effects-grid [data-value]')")
            await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
                {address: a, name: 'Desk', kind: 'clock', state: 'active'},
                {address: b, name: 'Shelf', kind: 'clock', state: 'active'}]})""", [A, B])
            # The bench's wall, then the wall chosen as the display (the
            # selector's Virtual Wall button).
            await eval_js(page, """async (slots) => {
                window.DivoomState.assignedSlots = slots;
                await window.pywebview.api.update_wall_slots(JSON.stringify(slots));
                window.connectDevice('Virtual Wall', 'MatrixWall'); }""", slots)
            await wait_js(page, "() => window._activeDeviceMac() === 'MatrixWall'", timeout=10000)

            missed = {}
            for name, (failed, gesture) in GESTURES.items():
                # One toast history per gesture: two writes share a message.
                await eval_js(page, f"() => {{ window.__divoomToasts.length = 0; {gesture}; }}")
                try:
                    toast = await wait_toast(page, f"{failed}: Shelf", kind="error", timeout=15000)
                except Exception as exc:
                    missed[name] = f"no error toast naming Shelf ({exc})"
                    continue
                text = toast["rendered"]["text"]
                if "Desk" in text or "did not take" not in text:
                    missed[name] = text
            assert missed == {}, f"wall writes whose toast did not name Shelf alone: {missed}"
        finally:
            await browser.close()
