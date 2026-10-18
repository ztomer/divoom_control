"""E2E -- brightness, volume and size are per panel, read from the daemon (P5.1).

Drives the REAL web_ui with a fake ``window.pywebview.api`` (the harness of
test_e2e_weather_card.py) standing in for a two-panel fleet. Before P5.1:

* brightness and volume were read ONCE at startup with no mac (whichever
  panel the backend happened to hold), written with no mac, and the deck's
  per-panel brightness was a localStorage memory of what the slider last sent
  (85 for a panel it had never touched);
* the volume slider had two senders (`spatial_stage.js` and `app_init.js`),
  one of them with no link check at all;
* panel SIZE was guessed from the NAME twice, differently
  (`getDeviceDimensions`, `resolveDeviceSpec`), while `device_status` has
  carried each panel's model and resolution since P3.1.

What these pin, each against the fake daemon's per-mac answers:

* switching panels shows THAT panel's brightness, volume and size;
* a write names the panel it is for, once, and only while that panel is
  linked;
* a slow read for the panel you just left never paints over the one you are
  on (last-wins);
* a name that SAYS 64 on a 16-pixel panel reads 16 -- the size is the
  daemon's, never the name's;
* a value the daemon has not given is shown as unknown, not as a number.

Skipped if a browser isn't installed (runs with --run-browser).
"""
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

# Two panels, deliberately named against their size: the Ditoo's name says
# "64", the Pixoo's name says nothing.
A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"

_MOCK_API = """
window.__fleet = {
  panels: {
    '%A%': {mac: '%A%', connected: true, selected: false, model: 'DitooPlus', width: 16, height: 16,
            model_source: 'name', features: {speaker: true}},
    '%B%': {mac: '%B%', connected: true, selected: false, model: 'Pixoo64Wifi', width: 64, height: 64,
            model_source: 'name', features: {speaker: false}},
  },
  levels: {'%A%': {brightness: 30, volume: 5}, '%B%': {brightness: 90, volume: null}},
  delay: {},        // mac -> ms before its levels reply
  writes: [],       // every set_brightness / set_volume, with its args
  reads: [],        // every get_panel_levels mac
};
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: Object.values(window.__fleet.panels)}),
  get_panel_levels: (mac) => {
    window.__fleet.reads.push(mac);
    const lv = window.__fleet.levels[mac];
    const reply = JSON.stringify(lv ? Object.assign({ok: true, mac}, lv)
                                    : {ok: false, mac, error: 'no such panel'});
    const ms = window.__fleet.delay[mac] || 0;
    return ms ? new Promise(r => setTimeout(() => r(reply), ms)) : reply;
  },
  set_brightness: (mac, v) => { window.__fleet.writes.push({m: 'set_brightness', args: [mac, v]});
                                if (window.__fleet.levels[mac]) window.__fleet.levels[mac].brightness = v; return true; },
  set_volume: (mac, v) => { window.__fleet.writes.push({m: 'set_volume', args: [mac, v]});
                            if (window.__fleet.levels[mac]) window.__fleet.levels[mac].volume = v; return true; },
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
""".replace("%A%", A).replace("%B%", B)

_DECK = """() => {
    const t = id => (document.getElementById(id) || {}).textContent;
    const vol = document.getElementById('deck-volume-container');
    return {
        name: t('deck-device-name'), tag: t('deck-device-tag'),
        b: t('global-brightness-value'), bSlider: document.getElementById('global-brightness-slider').value,
        bState: document.getElementById('global-brightness-slider').dataset.state || '',
        v: t('appbar-volume-value'), vSlider: document.getElementById('appbar-volume-slider').value,
        volShown: !!vol && getComputedStyle(vol).display !== 'none',
        gallery: window.readGalleryTargetSize ? window.readGalleryTargetSize() : null,
    };
}"""


async def _open(p):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage")
    # The daemon adopts both panels: the broadcast every client gets.
    await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: 'Ditoo 64 Desk', kind: 'clock', state: 'active'},
        {address: b, name: 'Kitchen', kind: 'clock', state: 'active'}]})""", [A, B])
    return browser, page


async def _select(page, mac):
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", mac)


async def _deck_shows(page, mac, brightness):
    await wait_js(page, f"""() => document.getElementById('deck-device-name').textContent.trim() !== ''
        && document.getElementById('global-brightness-value').textContent === '{brightness}'""")
    return await eval_js(page, _DECK)


@pytest.mark.asyncio
async def test_switching_panels_shows_each_panels_own_values():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, A)
            a = await _deck_shows(page, A, "30%")
            assert a["bSlider"] == "30" and a["v"] == "5/15" and a["vSlider"] == "5", a
            assert a["volShown"], f"the Ditoo has a speaker; its volume must show: {a}"
            assert a["tag"] == "16×16", f"the daemon says 16 whatever the name says: {a}"
            assert a["gallery"] == 16, a

            await _select(page, B)
            b = await _deck_shows(page, B, "90%")
            assert b["bSlider"] == "90", b
            assert not b["volShown"], f"the Pixoo 64 has no speaker; no volume control: {b}"
            assert b["tag"] == "64×64", b
            assert b["gallery"] == 64, b

            await _select(page, A)
            again = await _deck_shows(page, A, "30%")
            assert again["v"] == "5/15", again
            reads = await eval_js(page, "() => window.__fleet.reads")
            assert reads.count(A) >= 2, f"each switch must ASK the daemon, not replay a memory: {reads}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_write_names_its_panel_and_the_other_panel_keeps_its_value():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, B)
            await _deck_shows(page, B, "90%")
            await eval_js(page, """() => { const s = document.getElementById('global-brightness-slider');
                for (const v of [70, 60, 55]) { s.value = String(v); s.dispatchEvent(new Event('input', {bubbles: true})); }
                s.dispatchEvent(new Event('change', {bubbles: true})); }""")
            await wait_js(page, "() => window.__fleet.writes.length > 0")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 250))")
            writes = await eval_js(page, "() => window.__fleet.writes")
            assert writes == [{"m": "set_brightness", "args": [B, 55]}], writes

            await _select(page, A)
            a = await _deck_shows(page, A, "30%")
            assert a["bSlider"] == "30", f"A must show A's brightness, not B's last write: {a}"

            await eval_js(page, """() => { const s = document.getElementById('appbar-volume-slider');
                s.value = '9'; s.dispatchEvent(new Event('input', {bubbles: true}));
                s.dispatchEvent(new Event('change', {bubbles: true})); }""")
            await wait_js(page, "() => window.__fleet.writes.length > 1")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 250))")
            writes = await eval_js(page, "() => window.__fleet.writes")
            assert writes[1:] == [{"m": "set_volume", "args": [A, 9]}], (
                f"one volume gesture, one write, naming the panel: {writes}")

            await _select(page, B)
            b = await _deck_shows(page, B, "55%")
            assert b["bSlider"] == "55", b
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_no_write_to_a_panel_that_is_not_linked():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, A)
            await _deck_shows(page, A, "30%")
            # The OTHER panel stays linked, so "the app is connected" is true;
            # the selected one is not, and that is the one the slider is for.
            await eval_js(page, "(a) => window.Divoom.onDaemonEvent({type: 'status', connected: false, state: 'disconnected', mac: a})", A)
            for slider in ("global-brightness-slider", "appbar-volume-slider"):
                await eval_js(page, f"""() => {{ const s = document.getElementById('{slider}');
                    s.value = '3'; s.dispatchEvent(new Event('change', {{bubbles: true}})); }}""")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 250))")
            assert await eval_js(page, "() => window.__fleet.writes") == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_slow_read_for_the_panel_you_left_does_not_paint_the_one_you_are_on():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # Start on B (the bench's first render picked A), then visit A --
            # whose read is slow -- and come straight back to B.
            await _select(page, B)
            await _deck_shows(page, B, "90%")
            await eval_js(page, "(a) => { window.__fleet.delay[a] = 400; }", A)
            await _select(page, A)
            await _select(page, B)
            await _deck_shows(page, B, "90%")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 700))")
            state = await eval_js(page, _DECK)
            assert state["b"] == "90%" and state["bSlider"] == "90", (
                f"A's late reply landed on B: {state}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_value_the_daemon_did_not_give_is_unknown_not_a_number():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # B has not been shown yet (the bench's first render selects A).
            await eval_js(page, "(b) => { window.__fleet.levels[b] = {brightness: null, volume: null}; }", B)
            await _select(page, B)
            await wait_js(page, f"() => window.__fleet.reads.includes('{B}')")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 200))")
            state = await eval_js(page, _DECK)
            assert state["b"] == "–" and state["v"] == "–", state
            assert state["bState"] == "unknown", state
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_no_name_guesser_is_left():
    """One source of truth: the guessers are gone, not merely unused."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            assert await eval_js(page, "() => typeof window.getDeviceDimensions") == "undefined"
        finally:
            await browser.close()
    web_ui = INDEX_HTML.parent
    offenders = [f.name for f in web_ui.glob("*.js")
                 if "resolveDeviceSpec" in f.read_text() or "getDeviceDimensions" in f.read_text()]
    assert offenders == [], offenders
