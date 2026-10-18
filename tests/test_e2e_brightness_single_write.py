"""One brightness gesture, one device call.

P1.1: the deck's brightness slider (`#global-brightness-slider`) had TWO senders
on it. `divoom_gui/web_ui/spatial_stage.js` sent `set_brightness` on every
`input` event, and `divoom_gui/web_ui/app_init.js` sent it AGAIN on `change`.
A real drag fires `input` per value and `change` once when the mouse is
released, so the last value of every gesture was written to the device twice,
and the two paths also disagreed about when a send was allowed at all
(spatial_stage sent with no panel selected; app_init's `change` handler would
not).

This counts device calls over a REAL gesture in a REAL browser against the REAL
web_ui. The fix is one sender, not a debounce: a debounce keeps two owners and
only hides the duplicate.

Skipped if Playwright / a browser isn't installed (runs in CI's `--run-browser`).
"""
import pytest
from pathlib import Path
from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
PANEL = "AA:00:00:00:00:01"

# A permissive mock daemon API that RECORDS every device call, so a test can
# count them. `get_*` calls return "{}" (valid JSON the app parses).
_MOCK_API = """
window.__api = {};
window.__deviceCalls = [];
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    window.__deviceCalls.push({name: String(name), args: args});
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!document.getElementById('global-brightness-slider')")
    # A linked, selected panel: the one sender is allowed to write to IT (P5.1:
    # the gate is that panel's link, not the app-wide appConnected flag).
    await eval_js(page, """(mac) => {
        window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
            {address: mac, name: 'Ditoo', kind: 'clock', state: 'active'}]});
        window.Divoom.onSelection({type: 'selection', mac: mac});
    }""", PANEL)
    return browser, page


def _brightness_writes(page):
    """Every `set_brightness` device call so far, as [{name, args}]."""
    return eval_js(
        page,
        "() => window.__deviceCalls.filter(c => c.name === 'set_brightness')",
    )


@pytest.mark.asyncio
async def test_one_brightness_gesture_writes_the_device_once():
    """One real gesture (keyboard arrow on the slider) → ONE `set_brightness`.

    Watched red on today's code with `got 2 calls` — the duplicate the roadmap
    names.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.focus("#global-brightness-slider")
            await page.keyboard.press("ArrowRight")
            await wait_js(
                page,
                "() => window.__deviceCalls.some(c => c.name === 'set_brightness')",
                timeout=4000,
            )
            writes = await _brightness_writes(page)
            assert len(writes) == 1, (
                "one slider gesture must write the device once; got "
                f"{len(writes)} calls (a duplicate sender is listening again)"
            )
            # ...and it must carry the value the slider now shows, not a stale
            # one, for the panel it is shown for.
            assert int(writes[0]["args"][0]) == await eval_js(
                page, "() => parseInt(document.getElementById('global-brightness-slider').value)"
            )
            assert writes[0]["args"][1] == PANEL, writes
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_dragged_slider_does_not_write_every_intermediate_value():
    """A drag that crosses N values must not push N device writes.

    This is the other half of the duplicate: `spatial_stage.js` wrote on
    `input`, so a slow drag across the whole track wrote the device dozens of
    times. One call per value, i.e. one per committed value, is the contract
    (the same rule the volume slider documents next to it).
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # A real drag: many `input` events, then the release `change`.
            await eval_js(
                page,
                """() => {
                    const s = document.getElementById('global-brightness-slider');
                    for (const v of [20, 40, 60, 80, 99]) {
                        s.value = String(v);
                        s.dispatchEvent(new Event('input', {bubbles: true}));
                    }
                    s.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
            )
            await wait_js(
                page,
                "() => window.__deviceCalls.some(c => c.name === 'set_brightness')",
                timeout=4000,
            )
            writes = await _brightness_writes(page)
            # One write for the value the gesture settled on.
            assert len(writes) == 1, (
                "a drag across five values must not write the device five times "
                f"(or twice on top of that); got {len(writes)} calls"
            )
            assert int(writes[0]["args"][0]) == 99, (
                f"the single write must carry the final value, got {writes[0]['args']}"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_no_brightness_write_without_a_linked_panel():
    """A gesture with no panel linked writes nothing.

    `spatial_stage.js`'s sender had no connectivity check — it fired whether or
    not a panel was linked, so a drag over a disconnected deck still hit the
    bridge. The one sender refuses a panel that is not linked (P5.1: that
    panel's link, not the app-wide `appConnected`).
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page()
        await add_init_js(page, _MOCK_API)
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DivoomState && !!document.getElementById('global-brightness-slider')")
        try:
            assert await eval_js(page, "() => window.DivoomState.appConnected") is False
            # The bench's placeholder fleet selects a panel nobody linked.
            assert not await eval_js(page, "() => window.panelIsLinked(window.SpatialStage.getSelectedMac())")
            await page.focus("#global-brightness-slider")
            await page.keyboard.press("ArrowRight")
            # Give a stray sender every chance to fire before asserting absence.
            await eval_js(page, "() => new Promise(r => setTimeout(r, 250))")
            writes = await _brightness_writes(page)
            assert writes == [], (
                "no panel is linked, so the slider must not write the device; got "
                f"{writes}"
            )
        finally:
            await browser.close()
