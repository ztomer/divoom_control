"""E2E -- a bench node's preview is drawn when the node is built, not on the next frame.

Found 2026-11-11 in the installed app (DV.BENCHBLANK): with the window off
screen (hidden, or on another Space), a daemon broadcast (`owned_devices`,
here from a `select_device`) rebuilt the bench, and all four node previews
came out blank -- the dark screen with no clock -- and stayed blank in every
capture after. The node canvases were drawn ONLY by the
`requestAnimationFrame` loop (spatial_stage.js `startAnimationLoop`), and
WebKit does not run that loop for a page that is not on screen, so a node
built while the window was away had nothing on it until the loop ran again.
The same holds for a canvas whose pixels the engine dropped while the page
was hidden.

So a node is drawn by the same renderer the moment it is built, and every
node is redrawn the moment the page becomes visible again; the loop only
animates. These tests hold the animation loop still (the state WebKit puts
an off-screen page in) and read the node canvases' pixels.

Skipped if a browser isn't installed (runs with --run-browser).
"""

import json

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js
from tests.test_e2e_bench_snap import INDEX_HTML
from tests.test_e2e_room_lists_its_panels import _MOCK_API

PANELS = [
    ("aa000000-0000-4000-8000-000000000001", "Ditoo-light-2", "DITOO"),
    ("bb000000-0000-4000-8000-000000000002", "Tivoo-Max-light-3", "TivooMax"),
]

# The page's frame loop, held still on request: the state WebKit leaves a page
# in while its window is off screen. Frames asked for while held are dropped.
_HOLD_FRAMES = """
window.__holdFrames = false;
(() => {
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => raf((t) => { if (!window.__holdFrames) cb(t); });
})();
"""

# Lit pixels per node canvas: any pixel brighter than the screen's dark ground.
_CANVASES = "#spatial-bench canvas.spatial-node-canvas"
_LIT = (
    """() => Object.fromEntries([...document.querySelectorAll('"""
    + _CANVASES
    + """')].map(c => {
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let lit = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && (d[i] > 60 || d[i + 1] > 60 || d[i + 2] > 60)) lit++;
    return [c.id.slice('stage-canvas-'.length), lit];
}))"""
)


def _panel(mac, model):
    return {
        "mac": mac,
        "connected": True,
        "selected": False,
        "model": model,
        "width": 16,
        "height": 16,
        "model_source": "name",
        "features": {"speaker": False},
        "wall_refusal": None,
    }


async def _bench(p):
    topology = {"rooms": ["Shelf"], "devices": {m: {"room": "Shelf"} for m, _, _ in PANELS}}
    init = _MOCK_API.replace("%PANELS%", json.dumps([_panel(m, mo) for m, _, mo in PANELS])).replace(
        "%TOPOLOGY%", json.dumps(topology)
    )
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _HOLD_FRAMES + init)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialRooms?.isLoaded()")
    await eval_js(page, "(d) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: d})", _owned())
    await wait_js(page, f"() => document.querySelectorAll('{_CANVASES}').length === {len(PANELS)}")
    return browser, page


def _owned():
    return [{"address": m, "name": n, "kind": "clock", "state": "active"} for m, n, _ in PANELS]


@pytest.mark.asyncio
async def test_a_bench_rebuilt_while_off_screen_still_shows_its_clocks():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _bench(p)
        try:
            # Calibration: with frames running, every node draws its clock.
            await wait_js(page, f"() => Object.values(({_LIT})()).every(n => n > 0)")
            # The window leaves the screen, and the daemon's broadcast rebuilds the bench.
            await eval_js(page, "() => { window.__holdFrames = true; }")
            await eval_js(page, "(d) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: d})", _owned())
            lit = await eval_js(page, _LIT)
            assert set(lit) == {m for m, _, _ in PANELS}, lit
            assert all(n > 0 for n in lit.values()), f"blank node previews after an off-screen rebuild: {lit}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_nodes_are_redrawn_when_the_page_comes_back_on_screen():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _bench(p)
        try:
            await wait_js(page, f"() => Object.values(({_LIT})()).every(n => n > 0)")
            # Off screen: no frames, and the engine drops the canvases' pixels.
            await eval_js(
                page,
                """() => { window.__holdFrames = true;
                document.querySelectorAll('#spatial-bench canvas.spatial-node-canvas')
                    .forEach(c => c.getContext('2d').clearRect(0, 0, c.width, c.height)); }""",
            )
            assert all(n == 0 for n in (await eval_js(page, _LIT)).values())
            # Back on screen: the page says so before its first frame runs.
            await eval_js(page, "() => document.dispatchEvent(new Event('visibilitychange'))")
            lit = await eval_js(page, _LIT)
            assert all(n > 0 for n in lit.values()), f"node previews not redrawn on return: {lit}"
        finally:
            await browser.close()


def _solid_green_png_data_url():
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (0, 255, 0)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.asyncio
async def test_a_frame_loaded_while_window_is_covered_paints_its_node():
    """DV.BGLAUNCH: while the window is covered (`__divoomCovered`), the animation loop is held.
    A raster frame arriving then finishes `img.onload` asynchronously; it must still paint
    onto the node canvas instead of leaving the pre-load glyph/blank frame."""
    require_browser()
    from playwright.async_api import async_playwright

    mac = PANELS[0][0]
    green_url = _solid_green_png_data_url()
    async with async_playwright() as p:
        browser, page = await _bench(p)
        try:
            await wait_js(page, f"() => Object.values(({_LIT})()).every(n => n > 0)")
            await eval_js(
                page,
                "() => { window.__divoomCovered = true; window.dispatchEvent(new Event('divoom:window-covered')); }",
            )
            await eval_js(
                page,
                "(args) => window.Divoom.onActivity("
                "{type: 'activity', mac: args.mac, kind: 'image', preview: args.url})",
                {"mac": mac, "url": green_url},
            )
            await wait_js(page, f"() => !!window.DisplayPreviewRegistry?.get({mac!r})?.imgLoaded")
            green_pixels = await eval_js(
                page,
                """(m) => {
                    const c = document.getElementById('stage-canvas-' + m);
                    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                    let g = 0;
                    for (let i = 0; i < d.length; i += 4) if (d[i] < 40 && d[i + 1] > 180 && d[i + 2] < 40) g++;
                    return g;
                }""",
                mac,
            )
            assert green_pixels == 16 * 16, f"covered node canvas did not paint loaded frame ({green_pixels}/256 green)"
        finally:
            await browser.close()
