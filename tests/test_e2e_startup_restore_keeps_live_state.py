"""The app's startup restore must not erase live state the app already has.

**The class:** the app restores persisted state on mount -- a snapshot of a
PREVIOUS session, read over the bridge a second after the page loads. But it
installed that snapshot UNCONDITIONALLY, over whatever the app had established
by then, and `{}` (nothing persisted) is truthy in JavaScript, so an EMPTY
snapshot erased a live wall too.

**What it cost:** the Virtual Wall stopped being a known target
(`isKnownTarget`), so it vanished from the device selector and every write
aimed at it went to a single panel instead of the wall. The same overwrite
dropped the daemon's own live devices from `discoveredDevices`, so
`panelIsLinked` said "not linked" for a panel the daemon WAS linking, and a
write to it was refused with "Connect a device first". A user who arranged a
wall in the first second of the app's life lost it, and the app's own banner
kept naming a wall it could no longer reach.

The restore FILLS A GAP; it never overwrites live state.

This is the second half of the pair the browser suites found when they started
running in the local gate (P1.13): the link flag and the wall slots are two
views of the same fact, and the app's own startup was overwriting both.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"
LIVE_PANEL = "AA:00:00:00:00:01"
PERSISTED_PANEL = "CC:00:00:00:00:03"

# A mock backend whose `load_config` is HELD until the test releases it, so
# "the restore landed" is a state the test owns rather than a 1s timer it
# races. The persisted slots and devices are the PREVIOUS session's -- a
# different wall and a different panel, exactly as a stale snapshot would be.
_MOCK_API = """
window.__api = {};
window.__hold = {};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (name === 'load_config')
        return new Promise(r => { window.__releaseConfig = () => r(JSON.stringify({
            slots: { 'DD:00:00:00:00:04': {x: 0, y: 0, name: 'Old Desk'} },
            devices: [{address: 'CC:00:00:00:00:03', name: 'Old Panel'}],
            last_connected_device: '' })); });
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.DivoomState.assignedSlots")
    return browser, page


LIVE_SLOTS = {A: {"x": 0, "y": 0, "size": 16, "name": "Desk", "room": "wall"},
              B: {"x": 1, "y": 0, "size": 16, "name": "Shelf", "room": "wall"}}


@pytest.mark.asyncio
async def test_the_startup_restore_does_not_erase_a_live_wall():
    """RED on the old code: the restore replaced the live wall with the
    persisted snapshot, and the wall stopped being a known target."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # The live wall, as the app's own arranger would have left it.
            await eval_js(page, "(s) => { window.DivoomState.assignedSlots = s; }", LIVE_SLOTS)
            assert await eval_js(page, "() => window.isKnownTarget('MatrixWall')") is True

            # The restore now lands, carrying the PREVIOUS session's wall.
            await wait_js(page, "() => typeof window.__releaseConfig === 'function'")
            await eval_js(page, "() => window.__releaseConfig()")
            # The restore's assignment is a microtask after the promise
            # resolves; give it the turn it needs to land.
            await eval_js(page, "() => new Promise(r => setTimeout(r, 300))")

            live = await eval_js(page, "() => Object.keys(window.DivoomState.assignedSlots || {})")
            assert sorted(live) == sorted(LIVE_SLOTS), (
                "the startup restore erased the live wall: it installed the "
                f"persisted snapshot over it ({live!r})"
            )
            assert await eval_js(page, "() => window.isKnownTarget('MatrixWall')") is True, (
                "the wall stopped being a known target: it vanished from the "
                "selector and writes aimed at it went to a single panel"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_startup_restore_still_fills_an_empty_wall():
    """The restore's own job is unchanged: with no live wall, it restores the
    persisted one -- otherwise the user's wall would not come back at all."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await wait_js(page, "() => typeof window.__releaseConfig === 'function'")
            await eval_js(page, "() => window.__releaseConfig()")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 300))")

            live = await eval_js(page, "() => Object.keys(window.DivoomState.assignedSlots || {})")
            assert live == ["DD:00:00:00:00:04"], (
                f"with no live wall the restore must restore the persisted one, got {live!r}"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_startup_restore_does_not_drop_the_daemons_live_devices():
    """The same overwrite, the other branch: the daemon's own devices.

    The daemon reports the panels it owns while the page is still loading, so
    by the time the restore lands the live list is not empty -- it is the
    TRUTH. Replacing it with the persisted one dropped every device the daemon
    was linking, and `panelIsLinked` then said "not linked" for a panel that
    was: a write to it was refused with "Connect a device first".

    The persisted devices are still restored -- tagged "not in range", the
    R61 treatment -- but they are MERGED IN, not installed over the live list.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # The daemon's own report, which lands while the page loads.
            await eval_js(page, """(mac) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
                {address: mac, name: 'Live Panel', kind: 'clock', state: 'active'}]})""", LIVE_PANEL)
            assert await eval_js(page, f"() => window.panelIsLinked({LIVE_PANEL!r})") is True

            await wait_js(page, "() => typeof window.__releaseConfig === 'function'")
            await eval_js(page, "() => window.__releaseConfig()")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 300))")

            live = await eval_js(page, "() => (window.DivoomState.discoveredDevices || []).map(d => d.address)")
            assert LIVE_PANEL in live, (
                "the startup restore dropped the daemon's live device: "
                f"got {live!r}"
            )
            assert await eval_js(page, f"() => window.panelIsLinked({LIVE_PANEL!r})") is True, (
                "the daemon's live device stopped counting as linked, so a write "
                "to it was refused with 'Connect a device first'"
            )
            # The persisted device is still restored, with the R61 "not in
            # range" treatment -- the restore's own job is unchanged.
            assert PERSISTED_PANEL in live, (
                f"the persisted device must still be restored, got {live!r}"
            )
            restored = await eval_js(
                page, f"() => (window.DivoomState.discoveredDevices || [])"
                      f".find(d => d.address === {PERSISTED_PANEL!r})")
            assert restored.get("unconfirmed") is True, (
                f"a restored device must be tagged unconfirmed, got {restored!r}"
            )
        finally:
            await browser.close()
