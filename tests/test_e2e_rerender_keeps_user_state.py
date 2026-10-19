"""E2E -- a background re-render of the Spatial Bench keeps what the user is doing.

``SpatialStage.refresh`` (``refreshBenchNodes``) runs on EVERY device-list
update: each scan result, each daemon activity event, each owned-device
broadcast, the startup auto-scan ``app_init.js`` schedules a second after load.
It rebuilds the bench nodes. Two things it used to do on every one of those
runs that belong only to a SELECTION:

1. **It moved the channel tab.** Its "rehydrate on initial bench load" block
   ran on every refresh, so a scan landing after the user opened the Text tab
   put them back on Clock. Main CI run 39171574815 attempt 2: the Danmaku test
   clicked Text, the startup scan's refresh hid the panel, and the click on
   ``#send-danmaku-btn`` timed out on "element is not visible".
2. **It threw away a drag in flight.** ``bench.innerHTML = ''`` detached the
   node under the mouse and re-seeded positions from storage, so the drop
   moved a node nobody could see and the bench showed the old place. Same run,
   attempt 1: B ended at its starting x (110), not flush with A (79).

Both reached CI only when the page's own timer happened to land inside a test's
gesture, which is why they looked like flakes on two different tests. Here the
refresh is fired INSIDE the gesture on purpose, so the race is a certainty.
"""
import pytest

from tests.support.browser import eval_js, require_browser, wait_js
from tests.test_e2e_bench_snap import A, B, _box, _open, _owned, _panel

_REFRESH = "() => window.SpatialStage.refresh()"


@pytest.mark.asyncio
async def test_a_bench_refresh_does_not_move_the_user_off_the_channel_tab_they_opened():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            await page.click('.tab-btn[data-channel="text"]')
            await page.wait_for_selector("#panel-text.active", state="visible")
            await eval_js(page, _REFRESH)  # what a scan result does
            await wait_js(page, "() => !!document.getElementById('spatial-node-" + A + "')")
            active = await eval_js(page, """() => ({
                panel: document.querySelector('#control-panel .channel-panel.active')?.id,
                tab: document.querySelector('.tab-btn[data-channel].active')?.dataset.channel })""")
            assert active == {"panel": "panel-text", "tab": "text"}, (
                f"a re-render is not a selection; the user's tab must stay: {active}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_first_panel_arriving_after_the_user_opened_a_tab_does_not_move_it():
    """The Danmaku failure exactly: the page opens with no panel, the user
    opens Text, THEN the startup scan delivers the first panel. The bench
    auto-selects it (provisionally) and paints its controls -- but that is a
    re-render, not the user choosing a panel, so the tab stays."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], [])
        try:
            await page.click('.tab-btn[data-channel="text"]')
            await page.wait_for_selector("#panel-text.active", state="visible")
            await eval_js(page, "(devs) => window.Divoom.onOwnedDevices("
                                "{type: 'owned_devices', devices: devs})", _owned(A, B))
            await eval_js(page, "() => window.refreshPanelFacts()")
            await wait_js(page, "() => !!document.getElementById('spatial-node-" + A + "')")
            await eval_js(page, _REFRESH)
            active = await eval_js(page, """() => ({
                panel: document.querySelector('#control-panel .channel-panel.active')?.id,
                tab: document.querySelector('.tab-btn[data-channel].active')?.dataset.channel })""")
            assert active == {"panel": "panel-text", "tab": "text"}, (
                f"the first panel arriving is not the user choosing one: {active}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_selection_still_shows_the_selected_panels_channel():
    """Calibration for the test above: CHOOSING a panel is what syncs the tab
    to that panel's channel, and that must keep working."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            await page.click('.tab-btn[data-channel="text"]')
            await page.wait_for_selector("#panel-text.active", state="visible")
            await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", B)
            await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{B}'")
            await wait_js(page, "() => document.querySelector("
                                "'#control-panel .channel-panel.active')?.id === 'panel-clock'")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_bench_refresh_during_a_drag_keeps_the_drag():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            a = await _box(page, A)
            b = await _box(page, B)
            gap = b["x"] - (a["x"] + a["w"])
            dx, dy = -(gap - 5), 6
            box = await page.locator(f"[id='spatial-node-{B}']").bounding_box()
            sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            await page.mouse.move(sx, sy)
            await page.mouse.down()
            await page.mouse.move(sx + dx / 2, sy + dy / 2, steps=4)
            await eval_js(page, _REFRESH)  # a scan result lands mid-drag
            await page.mouse.move(sx + dx, sy + dy, steps=4)
            await page.mouse.up()
            await wait_js(page, "() => !!document.getElementById('spatial-node-" + B + "')")
            got = await _box(page, B)
            assert (got["x"], got["y"]) == (a["x"] + a["w"], a["y"]), (
                f"the drop must land where it was dropped, snapped: A={a} B={got}")
            saved = await eval_js(page, "(m) => window.SpatialRooms.getSavedPositions()[m]", B)
            assert (saved["x"], saved["y"]) == (got["x"], got["y"]), (
                f"what is saved is what is shown: saved={saved} shown={got}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_bench_refresh_does_not_move_a_level_slider_the_user_is_holding():
    """The same class on the deck: every refresh repaints the selected panel's
    last-read levels, so a scan landing mid-gesture snapped the brightness
    thumb back under the user's finger."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [_panel(A), _panel(B)], _owned(A, B))
        try:
            slider = page.locator("#global-brightness-slider")
            await wait_js(page, "() => document.getElementById('global-brightness-slider')"
                                ".dataset.state === 'known'")
            box = await slider.bounding_box()
            y = box["y"] + box["height"] / 2
            await page.mouse.move(box["x"] + box["width"] * 0.5, y)
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"] * 0.9, y, steps=4)
            held = await eval_js(page, "() => document.getElementById('global-brightness-slider').value")
            assert held != "50", f"calibration: the gesture moved the thumb ({held})"
            await eval_js(page, _REFRESH)
            during = await eval_js(page, "() => document.getElementById('global-brightness-slider').value")
            await page.mouse.up()
            assert during == held, (
                f"a re-render must not move a slider the user is holding: {held} -> {during}")
        finally:
            await browser.close()
