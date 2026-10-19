"""A pending connect must not make the app refuse a write to a linked display.

The class: `setConnectionState` writes TWO views of one fact -- the panel's own
flags (`daemonOwned`, which `panelIsLinked` and `requireDevice` read) and the
app-wide `appConnected`. The banner had always followed the rule "a pending
click must not erase the last known device before its outcome is known" --
`connecting` never wipes it -- but the link flag did not: `connecting` cleared
`appConnected`, so the two views of the same fact disagreed.

It cost the app a real write. `requireDevice()` gates every channel write, and
for a Virtual Wall -- which has no `discoveredDevices` record of its own, being
a composite of panels rather than a panel -- it falls back to that app-wide
flag. So while ANY connect was in flight, every wall write was refused with
"Connect a device first" and DROPPED, never reaching the daemon.

The window is ordinary, not exotic: the app's own startup restore
(`app_init.js`) reconnects the last device a second after load, so the writes
that land in that second are lost. This was found by the browser suite running
eight-wide (P1.13): `test_e2e_wall_write_names_the_panel.py` went red under
contention with the toast "Connect a device first" instead of the panel's name.

What this test pins: a write to a LINKED display is still sent while a connect
is in flight, and it is still sent to that display. Both directions of the
gate are checked -- the wall (whose link the app-wide flag carries) and a
panel (whose link its own record carries) -- because the two views are the
same fact and must agree.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from tests.support.browser import (
    add_init_js,
    eval_js,
    install_toast_recorder,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
PANEL = "AA:00:00:00:00:01"
WALL = "MatrixWall"

# A permissive mock daemon API that RECORDS every device call, so a test can
# see which display a write went to. `get_*` calls return "{}" (valid JSON the
# app parses). `connect_single_device` is HELD until the test releases it, so
# "a connect is in flight" is a state the test owns rather than a 150ms window
# a loaded machine overshoots.
_MOCK_API = """
window.__api = {};
window.__deviceCalls = [];
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (name === 'connect_single_device')
        return new Promise(r => { window.__release = () => r(true); });
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
    await install_toast_recorder(page)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.requireDevice")
    return browser, page


def _writes(page, name: str):
    """Every device call of that name, as [{args}]."""
    return eval_js(
        page,
        f"() => window.__deviceCalls.filter(c => c.name === {name!r})",
    )


@pytest.mark.asyncio
async def test_a_wall_write_is_sent_while_a_connect_is_in_flight():
    """The wall is linked and a connect is pending: the write still goes out.

    RED on the old code: the write was refused with "Connect a device first"
    and never reached the daemon -- `requireDevice()` fell back to the
    app-wide link flag, which `connecting` had just cleared.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # The wall, linked: the app is connected to it and the wall has
            # slots, so the app knows a display is there.
            await eval_js(page, """(wall) => {
                window.DivoomState.assignedSlots = {AA: {x: 0, y: 0, name: 'Desk'}};
                document.getElementById('banner-device-mac').textContent = wall;
                window.setConnectionState({mode: 'active', transport: 'wall', mac: wall, name: 'Virtual Wall'});
            }""", WALL)
            # A connect now IN FLIGHT, and it stays in flight: the test owns
            # the state, so the assertion below cannot be won by luck.
            await eval_js(page, "() => window.connectDevice('Ditoo', 'AA:00:00:00:00:01')")
            await wait_js(page, "() => typeof window.__release === 'function'")
            assert await eval_js(page, "() => window.DivoomState.appConnected") is True, (
                "a pending connect is not a lost link: it must not clear the "
                "app-wide link flag the wall's writes are gated on"
            )

            # The user's gesture: pick a clock face on the wall.
            await eval_js(page, "() => document.querySelector('#clock-faces-grid [data-value=\"2\"]').click()")
            await wait_js(
                page,
                "() => window.__deviceCalls.some(c => c.name === 'set_clock')",
                timeout=4000,
            )
            writes = await _writes(page, "set_clock")
            assert writes, "the clock write never reached the daemon"
            assert writes[0]["args"][0] == WALL, (
                f"the write must name the wall it was aimed at, got {writes[0]['args']!r}"
            )
            # And it must NOT have been refused on the way.
            hint = await eval_js(page, "() => window.__divoomToasts.some(t =>"
                                      " t.rendered && t.rendered.text.indexOf('Connect a device first') >= 0)")
            assert not hint, "the write was refused with 'Connect a device first' instead of being sent"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_panel_write_is_sent_while_a_connect_is_in_flight():
    """The same gate, the other branch: a panel's own link record carries it.

    A panel's link lives in ITS OWN record (`daemonOwned`), so this direction
    was never broken -- a pending connect names no mac, so it never touched
    those flags. It is here as the CONTRAST that makes the diagnosis
    checkable: the two views of one fact must agree, and only the app-wide
    one could move on a pending connect. If this test ever fails, the panel
    branch broke too and the wall case is no longer the whole story.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, """(panel) => {
                window.DivoomState.discoveredDevices = [
                    {address: panel, name: 'Ditoo', daemonOwned: true, activityState: 'active'}];
                document.getElementById('banner-device-mac').textContent = panel;
                window.setConnectionState({mode: 'active', transport: 'ble', mac: panel, name: 'Ditoo'});
            }""", PANEL)
            await eval_js(page, "(panel) => window.connectDevice('Ditoo2', panel)", PANEL)
            await wait_js(page, "() => typeof window.__release === 'function'")

            await eval_js(page, "() => document.querySelector('#clock-faces-grid [data-value=\"2\"]').click()")
            await wait_js(
                page,
                "() => window.__deviceCalls.some(c => c.name === 'set_clock')",
                timeout=4000,
            )
            writes = await _writes(page, "set_clock")
            assert writes, "the clock write never reached the daemon"
            assert writes[0]["args"][0] == PANEL, writes[0]["args"]
        finally:
            await browser.close()
