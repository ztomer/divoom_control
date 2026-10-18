"""E2E -- the Spatial Bench snaps panels into one surface, and says why a panel
on Wi-Fi cannot join it (P6.1).

Drives the REAL web_ui with a fake ``window.pywebview.api`` (the harness of
test_e2e_channel_settings_per_panel.py). The geometry itself is
`divoom_gui/web_ui/spatial_snap.js`, unit-tested under node in
tests/test_spatial_snap.py; this checks that a real mouse drag on a real bench
node lands where that function says, and that the position saved -- the one a
wall cuts its image by -- is the snapped one.

The final check, two real panels showing one image across the seam, needs the
hardware (docs/ROADMAP.md, P6.1).

Skipped if a browser isn't installed (runs with --run-browser).
"""
from pathlib import Path

import pytest

from tests.support.browser import (
    add_init_js, eval_js, install_toast_recorder, launch, require_browser, wait_js, wait_toast)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

A, B, LAN = "AA:00:00:00:00:01", "BB:00:00:00:00:02", "LAN:10.0.0.5"
REFUSAL = ("Not a wall slot: images reach panels over Bluetooth only, and the Wi-Fi "
           "image upload Divoom's own app uses is not known.")

_MOCK_API = """
window.__panels = %PANELS%;
window.__calls = [];
const __rec = (m, ret) => (...args) => { window.__calls.push({m, args}); return ret; };
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: window.__panels}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  update_wall_slots: __rec('update_wall_slots', null),
  display_wall_image: __rec('display_wall_image', {success: true, previews: {}}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


def _panel(mac, model="DitooPlus", px=16, refusal=None):
    return {"mac": mac, "connected": True, "selected": False, "model": model, "width": px,
            "height": px, "model_source": "name", "features": {"speaker": False},
            "wall_refusal": refusal}


async def _open(p, panels, owned):
    import json
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _MOCK_API.replace("%PANELS%", json.dumps(panels)))
    await install_toast_recorder(page)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage && !!window.SpatialSnap")
    await eval_js(page, "() => { try { localStorage.clear(); } catch (_) {} }")
    await eval_js(page, "(devs) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: devs})", owned)
    await eval_js(page, "() => window.refreshPanelFacts()")
    for mac in [d["address"] for d in owned]:
        await wait_js(page, f"() => !!document.getElementById('spatial-node-{mac}')")
    return browser, page


async def _box(page, mac):
    return await eval_js(page, """(m) => { const n = document.getElementById('spatial-node-' + m);
        return {x: n.offsetLeft, y: n.offsetTop, w: n.offsetWidth, h: n.offsetHeight}; }""", mac)


async def _drag(page, mac, dx, dy):
    node = page.locator(f"[id='spatial-node-{mac}']")
    box = await node.bounding_box()
    sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await page.mouse.move(sx, sy)
    await page.mouse.down()
    await page.mouse.move(sx + dx / 2, sy + dy / 2, steps=4)
    await page.mouse.move(sx + dx, sy + dy, steps=4)
    await page.mouse.up()


def _owned(*macs):
    names = {A: "Desk", B: "Shelf", LAN: "Kitchen"}
    return [{"address": m, "name": names[m], "kind": "clock", "state": "active"} for m in macs]


@pytest.mark.asyncio
async def test_a_panel_dragged_near_another_snaps_flush_and_lines_up():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            a = await _box(page, A)
            b = await _box(page, B)
            # Toward A's right edge, landing a few px short of it and a few px low.
            gap = b["x"] - (a["x"] + a["w"])
            await _drag(page, B, -(gap - 5), 6)
            got = await _box(page, B)
            assert (got["x"], got["y"]) == (a["x"] + a["w"], a["y"]), (
                f"B must sit flush against A's right edge, tops aligned: A={a} B={got}")
            saved = await eval_js(page, "(m) => window.SpatialRooms.getSavedPositions()[m]", B)
            assert (saved["x"], saved["y"]) == (got["x"], got["y"]), (
                f"the saved position (what a wall cuts by) must be the snapped one: {saved}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_panel_dragged_clear_of_the_others_stays_where_it_was_dropped():
    """Calibration: snapping is a pull within reach, not a magnet everywhere."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            b = await _box(page, B)
            await _drag(page, B, 160, -20)
            got = await _box(page, B)
            assert (got["x"], got["y"]) == (b["x"] + 160, b["y"] - 20), (b, got)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_panel_on_wifi_says_why_it_is_not_a_wall_slot_and_is_left_out():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        panels = [_panel(A), _panel(LAN, "Pixoo64Wifi", 64, REFUSAL)]
        browser, page = await _open(p, panels, _owned(A, LAN))
        try:
            await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", LAN)
            await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{LAN}'")
            note = await eval_js(page, """() => { const n = document.getElementById('deck-wall-note');
                return n && !n.hidden ? n.textContent : null; }""")
            assert note and REFUSAL in note, f"the deck must say why: {note!r}"

            await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", A)
            await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{A}'")
            assert await eval_js(page, "() => document.getElementById('deck-wall-note').hidden"), (
                "a Bluetooth panel has no such note")

            await eval_js(page, """() => { document.getElementById('file-path-input').value = '/tmp/art.png';
                document.getElementById('apply-wall-art').click(); }""")
            toast = await wait_toast(page, "Kitchen")
            assert REFUSAL in toast["rendered"]["text"], toast
            calls = await eval_js(page, "() => window.__calls")
            import json
            sent = [json.loads(c["args"][0]) for c in calls if c["m"] == "update_wall_slots"]
            assert sent and all(LAN not in s and A in s for s in sent), (
                f"the wall's slots must leave the Wi-Fi panel out: {sent}")
            assert any(c["m"] == "display_wall_image" for c in calls), "the rest of the wall still gets the image"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_wall_image_that_one_panel_did_not_take_names_that_panel():
    """P6.3: the daemon names each wall panel whose write failed; the toast
    says which panel, by the name the bench shows, and why -- not "the wall
    failed"."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            await eval_js(page, """(b) => { window.__api.display_wall_image = () => ({
                success: false, previews: {},
                error: `wall: ${b} did not take it (the transfer failed)`,
                failed: {[b]: 'the transfer failed'}, degraded: []}); }""", B)
            await eval_js(page, """() => { document.getElementById('file-path-input').value = '/tmp/art.png';
                document.getElementById('apply-wall-art').click(); }""")
            toast = await wait_toast(page, "Shelf", kind="error")
            text = toast["rendered"]["text"]
            assert "the transfer failed" in text, f"the reason is kept: {text!r}"
            assert "Desk" not in text, f"Desk took the image: {text!r}"
        finally:
            await browser.close()
