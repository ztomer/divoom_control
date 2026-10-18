"""E2E -- every channel control writes to the SELECTED panel's state (P5.2).

Drives the REAL web_ui with a fake ``window.pywebview.api`` (the harness of
test_e2e_panel_levels_per_panel.py) standing in for a two-panel fleet.

Before P5.2 the READ side was per display (``syncChannelControlsToDisplay``),
but the WRITE side read app-wide globals: ``DivoomState.selectedClockStyle``,
a module-level ``selectedAmbientMode``, the colour inputs' DOM values, and
``_activeDeviceMac()`` called again when the panel's reply came back. So:

* a colour input kept the previous panel's value when the new panel was on
  another channel, and the next clock write on the new panel sent it;
* a slow reply recorded its result on whichever panel was selected THEN;
* VJ and EQ picks were never recorded per panel at all, so switching back to
  a panel could not show what it was on;
* ``DisplayPreviewRegistry.getActive()`` -- the obvious one place to ask
  "which display" -- had no callers.

What these pin, against the fake bridge's record of every write:

* changing panel A's clock style leaves B's untouched, and each panel shows
  its own style and colour when you come back to it;
* a colour follows its panel onto another channel and back;
* VJ, EQ, ambient and scoreboard picks are each panel's own;
* a write's result lands on the panel it was made for, even if the
  selection moved while it was in flight;
* the write path resolves the panel in ONE place.

Skipped if a browser isn't installed (runs with --run-browser).
"""
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

WEB_UI = Path(__file__).parent.parent / "divoom_gui" / "web_ui"
INDEX_HTML = WEB_UI / "index.html"

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"

_MOCK_API = """
window.__fleet = {
  panels: {
    '%A%': {mac: '%A%', connected: true, selected: false, model: 'DitooPlus', width: 16, height: 16,
            model_source: 'name', features: {speaker: true}},
    '%B%': {mac: '%B%', connected: true, selected: false, model: 'Pixoo64Wifi', width: 64, height: 64,
            model_source: 'name', features: {speaker: false}},
  },
  writes: [],   // every channel write: {m, args}
  delay: {},    // method -> ms before it answers
};
const __write = (m) => (...args) => {
  window.__fleet.writes.push({m, args});
  const ms = window.__fleet.delay[m] || 0;
  return ms ? new Promise(r => setTimeout(() => r(true), ms)) : true;
};
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: Object.values(window.__fleet.panels)}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  set_clock: __write('set_clock'),
  set_clock_rich: __write('set_clock_rich'),
  set_solid_light: __write('set_solid_light'),
  set_vj_effect: __write('set_vj_effect'),
  set_visualization: __write('set_visualization'),
  switch_channel: __write('switch_channel'),
  set_scoreboard: __write('set_scoreboard'),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
""".replace("%A%", A).replace("%B%", B)

# What the channel controls show right now.
_CONTROLS = """() => {
    const active = id => (document.querySelector(`#${id} .selector-cell.active`) || {}).dataset?.value ?? null;
    return {
        clockStyle: active('clock-faces-grid'),
        clockColor: document.getElementById('clock-color-input').value,
        ambientColor: document.getElementById('ambient-color-input').value,
        ambientMode: (document.querySelector('#ambient-mode-grid .ambient-mode-active') || {}).dataset?.value ?? null,
        vj: active('vj-effects-grid'),
        eq: active('eq-visualizer-grid'),
        red: document.getElementById('scoreboard-red').value,
        blue: document.getElementById('scoreboard-blue').value,
        weather: document.getElementById('clock-rich-weather').checked,
    };
}"""


async def _open(p):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage"
                        " && !!document.querySelector('#clock-faces-grid .selector-cell')")
    await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: 'Desk', kind: 'clock', state: 'active'},
        {address: b, name: 'Kitchen', kind: 'clock', state: 'active'}]})""", [A, B])
    return browser, page


async def _select(page, mac):
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", mac)
    await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{mac}'")


async def _settle(page, ms=150):
    await eval_js(page, f"() => new Promise(r => setTimeout(r, {ms}))")


async def _click(page, selector):
    await eval_js(page, "(s) => document.querySelector(s).click()", selector)
    await _settle(page)


async def _colour(page, input_id, value, event):
    await eval_js(page, """([id, v, ev]) => { const i = document.getElementById(id);
        i.value = v; i.dispatchEvent(new Event(ev, {bubbles: true})); }""", [input_id, value, event])
    await _settle(page)


async def _writes(page, method):
    return [w["args"] for w in await eval_js(page, "() => window.__fleet.writes") if w["m"] == method]


async def _clear_writes(page):
    await eval_js(page, "() => { window.__fleet.writes = []; }")


@pytest.mark.asyncio
async def test_changing_a_clock_style_on_one_panel_leaves_the_other_untouched():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, B)
            await _click(page, '#clock-faces-grid .selector-cell[data-value="5"]')
            await _colour(page, "clock-color-input", "#0000ff", "input")
            await _select(page, A)
            await _clear_writes(page)

            await _click(page, '#clock-faces-grid .selector-cell[data-value="3"]')
            await _colour(page, "clock-color-input", "#ff0000", "input")
            assert await _writes(page, "set_clock") == [[3, "#ffffff"], [3, "#ff0000"]]

            await _select(page, B)
            b = await eval_js(page, _CONTROLS)
            assert (b["clockStyle"], b["clockColor"]) == ("5", "#0000ff"), (
                f"B shows B's own clock, not A's last write: {b}")
            await _select(page, A)
            a = await eval_js(page, _CONTROLS)
            assert (a["clockStyle"], a["clockColor"]) == ("3", "#ff0000"), a

            state = await eval_js(page, """([a, b]) => ({
                a: window.getDeviceChannel(a).opts, b: window.getDeviceChannel(b).opts})""", [A, B])
            assert (state["a"]["style"], state["a"]["color"]) == (3, "#ff0000"), state
            assert (state["b"]["style"], state["b"]["color"]) == (5, "#0000ff"), state
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_colour_follows_its_panel_onto_another_channel():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # A: a red clock. B: on Ambient, its clock never touched.
            await _select(page, A)
            await _click(page, '#clock-faces-grid .selector-cell[data-value="2"]')
            await _colour(page, "clock-color-input", "#ff0000", "input")
            await _select(page, B)
            await _click(page, '.tab-btn[data-channel="ambient"]')
            await _click(page, '#ambient-mode-grid .selector-cell[data-value="0"]')

            await _select(page, A)
            await _select(page, B)
            b = await eval_js(page, _CONTROLS)
            assert b["clockColor"] == "#ffffff", f"A's red clock colour leaked onto B: {b}"

            # B goes to Clock and picks a face: B's colour, never A's.
            await _clear_writes(page)
            await _click(page, '.tab-btn[data-channel="clock"]')
            await _click(page, '#clock-faces-grid .selector-cell[data-value="1"]')
            assert await _writes(page, "set_clock") == [[1, "#ffffff"]]
            saved = await eval_js(page, "(b) => window.getDeviceChannel(b)", B)
            assert saved["channel"] == "clock" and saved["opts"]["color"] == "#ffffff", saved

            await _select(page, A)
            a = await eval_js(page, _CONTROLS)
            assert (a["clockStyle"], a["clockColor"]) == ("2", "#ff0000"), a
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_every_channel_control_is_the_selected_panels_own():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            picks = {A: ("4", "2", "#112233", "7", "3", True), B: ("9", "0", "#445566", "1", "8", False)}
            for mac, (vj, eq, amb, red, blue, weather) in picks.items():
                await _select(page, mac)
                await _click(page, f'#vj-effects-grid .selector-cell[data-value="{vj}"]')
                await _click(page, f'#eq-visualizer-grid .selector-cell[data-value="{eq}"]')
                await _click(page, '#ambient-mode-grid .selector-cell[data-value="0"]')
                await _colour(page, "ambient-color-input", amb, "change")
                await _colour(page, "scoreboard-red", red, "change")
                await _colour(page, "scoreboard-blue", blue, "change")
                await eval_js(page, """(on) => { const c = document.getElementById('clock-rich-weather');
                    c.checked = on; c.dispatchEvent(new Event('change', {bubbles: true})); }""", weather)
                await _settle(page)

            for mac in (A, B, A):
                await _select(page, mac)
                got = await eval_js(page, _CONTROLS)
                vj, eq, amb, red, blue, weather = picks[mac]
                assert (got["vj"], got["eq"], got["ambientColor"], got["red"], got["blue"], got["weather"]) == (
                    vj, eq, amb, red, blue, weather), f"{mac} shows another panel's picks: {got}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_write_lands_on_the_panel_it_was_made_for():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, B)
            await _click(page, '#clock-faces-grid .selector-cell[data-value="0"]')
            await _select(page, A)
            await eval_js(page, "() => { window.__fleet.delay.set_clock = 400; }")
            await eval_js(page, "() => document.querySelector('#clock-faces-grid .selector-cell[data-value=\"4\"]').click()")
            await _select(page, B)   # moved on before A's panel answered
            await _settle(page, 700)

            state = await eval_js(page, """([a, b]) => ({
                a: window.getDeviceChannel(a), b: window.getDeviceChannel(b),
                controls: (document.querySelector('#clock-faces-grid .selector-cell.active') || {}).dataset?.value})""",
                [A, B])
            assert state["a"]["opts"]["style"] == 4, f"A's reply must land on A: {state}"
            assert state["b"]["opts"]["style"] == 0, f"A's reply landed on B: {state}"
            assert state["controls"] == "0", f"B is shown; its controls must not move: {state}"
        finally:
            await browser.close()


def test_the_write_path_resolves_the_panel_in_one_place():
    """No channel writer asks "which panel" itself: the selected display comes
    from ``DisplayPreviewRegistry.getActive()`` via ``ChannelSettings``, and the
    app-wide channel globals are gone."""
    writers = ("channels_grids.js", "channels_core.js", "cloud_clock_faces.js")
    for name in writers:
        js = (WEB_UI / name).read_text(encoding="utf-8")
        assert "_activeDeviceMac" not in js, f"{name} resolves the panel itself"
    every = {f.name: f.read_text(encoding="utf-8") for f in WEB_UI.glob("*.js")}
    for stale in ("selectedClockStyle", "selectedAmbientMode"):
        offenders = [n for n, js in every.items() if stale in js]
        assert offenders == [], f"{stale} is an app-wide channel global: {offenders}"
    assert "DisplayPreviewRegistry.getActive()" in every["channel_settings.js"]
