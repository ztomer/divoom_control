"""A status broadcast names a panel; only that panel's link moves (2026-09-12).

Live on a four-panel fleet: `disconnect {mac: Ditoo}` left the Ditoo green
on the bench and in the sidebar. Two causes, both pinned here:

* the bench jewel was a hardcoded ``online`` (it now reads the panel's
  link state as the daemon last reported it);
* the status handler moved the one global dot for ANY panel's event and
  recorded nothing per panel.
"""
from pathlib import Path

import pytest

from tests.support.browser import eval_js, launch as launch_browser, wait_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"

STATE_JS = """() => {
    const list = window.DivoomState.discoveredDevices;
    const jewel = (mac) => {
        const n = document.getElementById(`spatial-node-${mac}`);
        const j = n && n.querySelector('.spatial-jewel');
        return j ? [...j.classList].filter(c => c !== 'spatial-jewel').join(' ') : null;
    };
    const byMac = {};
    list.forEach(d => { byMac[d.address] = { state: d.activityState || null, owned: !!d.daemonOwned, jewel: jewel(d.address) }; });
    const deck = document.getElementById('deck-device-dot');
    return { byMac, appConnected: !!window.DivoomState.appConnected,
             deckJewel: deck ? [...deck.classList].filter(c => c !== 'spatial-jewel').join(' ') : null,
             dot: (document.getElementById('status-dot') || document.querySelector('.status-dot'))?.className || null };
}"""


@pytest.mark.asyncio
async def test_status_moves_only_the_named_panel_and_the_jewel_is_honest():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.Divoom?.onDaemonEvent && !!window.SpatialStage && !!window.jewelClassFor")

        ditoo, pixoo = "E9:DITOO", "A9:PIXOO"
        state = await eval_js(page, """([d, px, stateJs]) => {
            window.DivoomState.discoveredDevices = [
                { address: d, name: "Ditoo", room: "Desk" },
                { address: px, name: "Pixoo", room: "Desk" },
            ];
            window.Divoom.onOwnedDevices({ type: 'owned_devices', devices: [
                { address: d, name: "Ditoo", kind: "clock", state: "active" },
                { address: px, name: "Pixoo", kind: "clock", state: "active" },
            ]});
            window.SpatialStage.refresh();
            // Select the Ditoo the way the bench does.
            document.getElementById('banner-device-mac').textContent = d;
            window.setConnectionState({ mode: 'active', transport: 'ble', mac: d, name: 'Ditoo' });
            return (%s)();
        }""" % STATE_JS, [ditoo, pixoo, None])
        assert state["byMac"][ditoo]["jewel"] == "online", state
        assert state["byMac"][pixoo]["jewel"] == "online", state
        assert state["appConnected"]

        # An owned_devices event alone (no status event after it) must
        # repaint the bench and the deck: a panel the daemon just adopted
        # shows online everywhere, not only in the sidebar chips.
        state = await eval_js(page, """([d, px, _]) => {
            window.DivoomState.discoveredDevices.forEach(x => { x.daemonOwned = false; x.activityState = 'disconnected'; });
            window.SpatialStage.refresh();
            const before = (%s)();
            window.Divoom.onOwnedDevices({ type: 'owned_devices', devices: [
                { address: d, name: "Ditoo", kind: "clock", state: "active" },
                { address: px, name: "Pixoo", kind: "clock", state: "active" },
            ]});
            return { before, after: (%s)() };
        }""" % (STATE_JS, STATE_JS), [ditoo, pixoo, None])
        assert state["before"]["byMac"][ditoo]["jewel"] == "standby"
        assert state["after"]["byMac"][ditoo]["jewel"] == "online", state["after"]
        assert state["after"]["deckJewel"] == "online", state["after"]

        # The PIXOO drops: the Ditoo (selected) must stay connected, the
        # Pixoo's jewel must go to standby.
        state = await eval_js(page, """([d, px, _]) => {
            window.Divoom.onDaemonEvent({ type: 'status', connected: false, state: 'disconnected', mac: px });
            return (%s)();
        }""" % STATE_JS, [ditoo, pixoo, None])
        assert state["byMac"][pixoo]["state"] == "disconnected"
        assert state["byMac"][pixoo]["jewel"] == "standby", state
        assert state["byMac"][ditoo]["jewel"] == "online", state
        assert state["appConnected"], "a drop of another panel must not disconnect the selected one"

        # The PIXOO degrades and recovers; the Ditoo is untouched throughout.
        state = await eval_js(page, """([d, px, _]) => {
            window.Divoom.onDaemonEvent({ type: 'status', connected: true, state: 'degraded', mac: px });
            const mid = (%s)();
            window.Divoom.onDaemonEvent({ type: 'status', connected: true, state: 'active', mac: px });
            return { mid, end: (%s)() };
        }""" % (STATE_JS, STATE_JS), [ditoo, pixoo, None])
        assert state["mid"]["byMac"][pixoo]["jewel"] == "amber"
        assert state["end"]["byMac"][pixoo]["jewel"] == "online"
        assert state["mid"]["appConnected"] and state["end"]["appConnected"]

        # The DITOO (selected) drops: the global dot goes inactive.
        state = await eval_js(page, """([d, px, _]) => {
            window.Divoom.onDaemonEvent({ type: 'status', connected: false, state: 'disconnected', mac: d });
            return (%s)();
        }""" % STATE_JS, [ditoo, pixoo, None])
        assert state["byMac"][ditoo]["jewel"] == "standby", state
        assert state["deckJewel"] == "standby", f"the sidebar card's jewel must follow the selected panel: {state}"
        assert not state["appConnected"], "the selected panel dropped; the app is not connected"
        assert state["byMac"][pixoo]["jewel"] == "online"

        # A fleet-wide status (names nobody) moves everyone.
        state = await eval_js(page, """([d, px, _]) => {
            window.Divoom.onDaemonEvent({ type: 'status', connected: false, state: 'idle' });
            return (%s)();
        }""" % STATE_JS, [ditoo, pixoo, None])
        assert all(v["jewel"] == "standby" for v in state["byMac"].values()), state
        await browser.close()


@pytest.mark.asyncio
async def test_bench_selection_always_reaches_python_including_the_fallback():
    """The bench's selection and Python's device proxy must move together
    on EVERY path: an explicit highlight, and the fallback that picks the
    first panel when the restored selection is not listed. The second path
    once skipped Python, and a music job started on the wrong panel."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.SpatialStage")
        res = await eval_js(page, """() => {
            const calls = [];
            window.pywebview = { api: { select_device: (m) => { calls.push(m); return Promise.resolve(true); } } };
            window.DivoomState.discoveredDevices = [
                { address: 'T1:TIMOO', name: 'Timoo' }, { address: 'E9:DITOO', name: 'Ditoo' }];
            // Restored selection is a panel that no longer exists.
            window.SpatialStage.refresh();
            const afterFallback = { sel: window.SpatialStage.getSelectedMac(), calls: calls.slice() };
            document.querySelector('.spatial-ribbon-chip:nth-child(2)')?.click();
            return { afterFallback, sel: window.SpatialStage.getSelectedMac(), calls };
        }""")
        assert res["afterFallback"]["sel"] == "T1:TIMOO"
        assert res["afterFallback"]["calls"] == ["T1:TIMOO"], res
        assert res["sel"] == "E9:DITOO" and res["calls"][-1] == "E9:DITOO", res
        await browser.close()


@pytest.mark.asyncio
async def test_require_device_and_fleet_status_are_per_panel():
    """Step 2 of the v0.37 plan: `requireDevice(mac)` gates on THAT panel's
    link; without a mac it gates on the selected panel; getFleetStatus
    counts linked panels instead of reporting the one global boolean."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.requireDevice && !!window.panelIsLinked")
        res = await eval_js(page, """() => {
            window.showToast = () => {};
            const d = 'E9:DITOO', px = 'A9:PIXOO';
            window.DivoomState.discoveredDevices = [
                { address: d, name: 'Ditoo' }, { address: px, name: 'Pixoo' }];
            window.Divoom.onOwnedDevices({ type: 'owned_devices', devices: [
                { address: d, name: 'Ditoo', kind: 'clock', state: 'active' },
                { address: px, name: 'Pixoo', kind: 'clock', state: 'active' }]});
            document.getElementById('banner-device-mac').textContent = d;
            window.setConnectionState({ mode: 'active', transport: 'ble', mac: d, name: 'Ditoo' });
            const both = { sel: window.requireDevice(), px: window.requireDevice(px),
                           count: window.getFleetStatus().connectedCount };
            // The Pixoo drops: the selected Ditoo still passes, the Pixoo does not.
            window.Divoom.onDaemonEvent({ type: 'status', connected: false, state: 'disconnected', mac: px });
            const pxDown = { sel: window.requireDevice(), px: window.requireDevice(px),
                             count: window.getFleetStatus().connectedCount,
                             appConnected: window.DivoomState.appConnected };
            // The Ditoo (selected) drops: the gate closes, the count is 0.
            window.Divoom.onDaemonEvent({ type: 'status', connected: false, state: 'disconnected', mac: d });
            const allDown = { sel: window.requireDevice(), count: window.getFleetStatus().connectedCount,
                              appConnected: window.DivoomState.appConnected };
            // A click-flow reconnect of the Pixoo through the funnel marks that panel.
            window.setConnectionState({ mode: 'active', transport: 'ble', mac: px, name: 'Pixoo' });
            const pxBack = { px: window.requireDevice(px), linked: window.panelIsLinked(px),
                             count: window.getFleetStatus().connectedCount };
            return { both, pxDown, allDown, pxBack };
        }""")
        assert res["both"] == {"sel": True, "px": True, "count": 2}
        assert res["pxDown"] == {"sel": True, "px": False, "count": 1, "appConnected": True}
        assert res["allDown"] == {"sel": False, "count": 0, "appConnected": False}
        assert res["pxBack"] == {"px": True, "linked": True, "count": 1}
        await browser.close()
