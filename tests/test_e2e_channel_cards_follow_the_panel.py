"""E2E -- the channel cards follow the PANEL in hand (P3.6).

Drives the REAL web_ui with a fake ``window.pywebview.api`` (the harness of
test_e2e_channel_settings_per_panel.py) standing in for a two-panel fleet:
one panel the vendor app gives an FM radio and the VJ channel, and one it
gives neither.

The cards used to be decided at CONNECT time. The daemon says what each
panel IS (the vendor app's per-model switches -- P3.4), but the web UI read
that description for the panel it had just CONNECTED, and never for the panel
the user then SELECTED. So selecting the second panel left the first panel's
abilities on screen: the radio card stayed offered to a panel with no radio,
and the VJ channel stayed offered to a panel that has none. The panels
DIFFER, and the bar has to follow the one in hand.

What these pin:

* the radio card is offered to the panel that has a radio and to no other;
* the VJ channel is offered to the panel that has it and to no other;
* moving between the panels moves the cards with them, both ways;
* a panel the daemon has not described is offered neither (unknown is not
  "has it"), and the cards come back when the description arrives.

Skipped if a browser isn't installed (runs with --run-browser).
"""
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

WEB_UI = Path(__file__).parent.parent / "divoom_gui" / "web_ui"
INDEX_HTML = WEB_UI / "index.html"

# A: the Tiivoo 2 -- the app gives it an FM radio, and it has the VJ channel.
# B: a 64x64 picture frame -- no radio, no VJ.
A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"
C = "CC:00:00:00:00:03"

_MOCK_API = """
window.__fleet = {
  panels: {
    '%A%': {mac: '%A%', connected: true, selected: false, model: 'TivooLcd', width: 128, height: 128,
            model_source: 'name', features: {speaker: true, sd_card: true, radio: true, vj: true}},
    '%B%': {mac: '%B%', connected: true, selected: false, model: 'Pixoo64Wifi', width: 64, height: 64,
            model_source: 'name', features: {speaker: false, sd_card: false, radio: false, vj: false}},
  },
};
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: Object.values(window.__fleet.panels)}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
""".replace("%A%", A).replace("%B%", B)

# What the channel bar offers right now: the FM card and the VJ channel.
_CARDS = """() => {
    const fm = document.getElementById('fm-radio-card');
    const vj = document.querySelector('.tab-btn[data-channel="vj"]');
    const shown = (el) => !!el && el.style.display !== 'none';
    return {radio: shown(fm), vj: shown(vj)};
}"""


async def _open(p):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage")
    await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: 'Desk', kind: 'clock', state: 'active'},
        {address: b, name: 'Kitchen', kind: 'clock', state: 'active'}]})""", [A, B])
    # The daemon's description of each panel has arrived.
    await wait_js(page, f"() => {{ const d = (window.DivoomState.discoveredDevices || [])"
                        f".find(x => x.address === '{A}'); return !!(d && d.features); }}")
    return browser, page


async def _select(page, mac):
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", mac)
    await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{mac}'")


@pytest.mark.asyncio
async def test_the_cards_follow_the_panel_in_hand():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, A)
            cards = await eval_js(page, _CARDS)
            assert cards == {"radio": True, "vj": True}, (
                f"the panel with a radio and the VJ channel must be offered both: {cards}")

            # The other panel has neither: the cards go with the selection.
            await _select(page, B)
            cards = await eval_js(page, _CARDS)
            assert cards == {"radio": False, "vj": False}, (
                f"the cards still show the previous panel's abilities: {cards}")

            # ...and back again, so it is the SELECTION that moves them.
            await _select(page, A)
            cards = await eval_js(page, _CARDS)
            assert cards == {"radio": True, "vj": True}, (
                f"the cards did not come back with the panel: {cards}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_panel_the_daemon_has_not_described_is_offered_neither():
    """Unknown is not "has it": a panel the daemon cannot describe is offered
    neither the radio nor the VJ channel -- and the cards appear when its
    description arrives."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # A third panel the daemon has not described (it cannot name it).
            await eval_js(page, """([a, c]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
                {address: a, name: 'Desk', kind: 'clock', state: 'active'},
                {address: c, name: 'Mystery', kind: 'clock', state: 'active'}]})""", [A, C])
            await _select(page, C)
            cards = await eval_js(page, _CARDS)
            assert cards == {"radio": False, "vj": False}, (
                f"an undescribed panel must be offered neither: {cards}")

            # Its description arrives: the cards follow it.
            await eval_js(page, """(c) => { window.__fleet.panels[c] =
                {mac: c, connected: true, selected: false, model: 'TivooLcd',
                 width: 128, height: 128, model_source: 'name',
                 features: {speaker: true, radio: true, vj: true}};
                window.refreshPanelFacts(); }""", C)
            await wait_js(page, f"""() => {{ const d = (window.DivoomState.discoveredDevices || [])
                .find(x => x.address === '{C}'); return !!(d && d.features && d.features.radio); }}""")
            cards = await eval_js(page, _CARDS)
            assert cards == {"radio": True, "vj": True}, (
                f"the cards did not follow the description that arrived: {cards}")
        finally:
            await browser.close()
