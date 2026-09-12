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
