"""E2E -- with no panel known, the GUI invents none (P5.5).

Before P5.5, with no panel known:

* the bench drew a made-up four-panel fleet (``11:22:33:44:55:01``..``04``,
  "Ditoo-L", "Pixoo-64") from ``getDeviceList``'s fallback;
* ``window._activeDeviceMac()`` fell back to ``11:22:33:44:55:01``, so the
  deck, the channel controls and every other caller acted on a panel that
  does not exist, and the bench told the backend to select it.

That is placeholder data dressed as the user's (the honest-placeholder rule).
What these pin, against a fake bridge that records every call:

* the bench says there are no panels and how to add one, and draws none;
* the deck says "No panel selected" and shows no levels;
* the lookup answers "none", and no bridge call carries a mac the daemon
  never reported -- through a walk of the tabs and channel controls;
* the moment the daemon reports a panel, the bench and deck show THAT one.

Skipped if a browser isn't installed (runs with --run-browser).
"""
import json
import re
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

REAL = "CC:00:00:00:00:03"
MAC = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", re.I)

_MOCK_API = """
window.__calls = [];
window.__panels = [];
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: window.__panels}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 40, volume: null}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    window.__calls.push({name: String(name), args: JSON.stringify(args)});
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""

_SCREEN = """() => {
    const deck = document.getElementById('sidebar-device-deck');
    const shown = el => !!el && el.offsetParent !== null && getComputedStyle(el).display !== 'none' && !el.hidden;
    const empty = document.getElementById('spatial-bench-empty');
    return {
        nodes: [...document.querySelectorAll('.spatial-node')].map(n => n.id),
        empty: empty && shown(empty) ? empty.textContent.replace(/\\s+/g, ' ').trim() : null,
        deckName: document.getElementById('deck-device-name').textContent.trim(),
        levelsShown: [...deck.querySelectorAll('.deck-slider-row')].some(shown),
        active: window._activeDeviceMac(),
        selected: window.ChannelSettings.selected(),
    };
}"""


async def _open(p):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.SpatialStage && !!document.querySelector('#clock-faces-grid .selector-cell')")
    await eval_js(page, "() => new Promise(r => setTimeout(r, 300))")
    return browser, page


async def _macs_sent(page):
    calls = await eval_js(page, "() => window.__calls")
    return {(c["name"], m.upper()) for c in calls for m in MAC.findall(c["args"])}


@pytest.mark.asyncio
async def test_no_panel_known_shows_an_honest_empty_state():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            s = await eval_js(page, _SCREEN)
            assert s["nodes"] == [], f"the bench drew panels nobody reported: {s['nodes']}"
            assert s["empty"] and "Scan" in s["empty"] and "Settings" in s["empty"], (
                f"the empty bench must say how to add a panel: {s}")
            assert s["deckName"] == "No panel selected", s
            assert not s["levelsShown"], f"no panel, so no levels: {s}"
            assert s["active"] is None and s["selected"] is None, s
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_no_bridge_call_names_a_panel_the_daemon_never_reported():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # Walk the app: every section, every channel card, a control on each.
            await eval_js(page, """async () => {
                const pause = () => new Promise(r => setTimeout(r, 60));
                for (const b of document.querySelectorAll('.nav-btn[data-tab]')) { b.click(); await pause(); }
                document.querySelector('.nav-btn[data-tab="control-panel"]').click();
                for (const c of document.querySelectorAll('.tab-btn[data-channel]')) { c.click(); await pause(); }
                for (const id of ['clock-faces-grid', 'ambient-mode-grid', 'vj-effects-grid', 'eq-visualizer-grid']) {
                    document.querySelector(`#${id} .selector-cell`).click(); await pause();
                }
                const s = document.getElementById('global-brightness-slider');
                s.value = '20'; s.dispatchEvent(new Event('change', {bubbles: true}));
                document.getElementById('deck-device-power').click();
                window.markActiveDeviceFrame('data:image/png;base64,AA==');
                // What the playlist / photo-album / sleep-aid writers do after a
                // success: record on "the selected panel" by passing none.
                window.setDeviceActivity(null, 'playlist', {playId: 1});
                await pause();
            }""")
            sent = await _macs_sent(page)
            assert sent == set(), f"bridge calls named panels the daemon never reported: {sorted(sent)}"
            # Nor the banner's placeholder text passed off as a panel address.
            calls = await eval_js(page, "() => window.__calls")
            fake = [c for c in calls if any(a in ("-", "None") for a in json.loads(c["args"]))]
            assert fake == [], f"bridge calls named a placeholder as their panel: {fake}"

            # The daemon reports one: from now on, that one and only that one.
            await eval_js(page, """(m) => { window.__panels = [{mac: m, connected: true, model: 'DitooPlus',
                    width: 16, height: 16, features: {speaker: true}}];
                window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
                    {address: m, name: 'Shelf', kind: 'clock', state: 'active'}]}); }""", REAL)
            await wait_js(page, f"() => !!document.getElementById('spatial-node-{REAL}')")
            await eval_js(page, "() => document.querySelector('#clock-faces-grid .selector-cell[data-value=\"2\"]').click()")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 200))")
            s = await eval_js(page, _SCREEN)
            assert s["nodes"] == [f"spatial-node-{REAL}"] and s["empty"] is None, s
            assert s["deckName"] == "Shelf" and s["active"] == REAL and s["levelsShown"], s
            assert {m for _n, m in await _macs_sent(page)} == {REAL}
        finally:
            await browser.close()
