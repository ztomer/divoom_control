"""E2E -- every device action outside the channels names the panel clicked (P5.7).

P5.6 made the channel controls pass the mac they resolved at the gesture
(`tests/test_e2e_channel_settings_per_panel.py`). The Tools tab, the alarms
editor, the live widgets, the gallery, hot-channel and custom-art pushes sent
no mac at all: the backend acted on the panel the bench had selected by the
time the call RAN. This drives the REAL web UI against a fake bridge for a
two-panel fleet, makes each gesture with A selected, moves the selection to B
at once, and asserts every call the gesture made named A as its first
argument. The alarms editor's writes are debounced -- the call leaves 500 ms
after the click -- so the selection has moved by the time it is sent; that is
the race in its plainest form.

`tests/test_device_actions_name_their_panel.py` pins the bridge's half (a
call naming A reaches A), `tests/test_e2e_device_action_reaches_its_panel.py`
the whole chain against a real daemon.

Skipped if a browser isn't installed (runs with --run-browser).
"""
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

WEB_UI = Path(__file__).parent.parent / "divoom_gui" / "web_ui"
INDEX_HTML = WEB_UI / "index.html"

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"

#: Every bridge method a gesture below may call that acts on a panel.
ACTIONS = (
    "start_sleep", "stop_sleep", "set_timer", "set_countdown", "set_noise", "set_screen_mirror",
    "set_hour_type", "set_temp_unit", "set_low_power", "set_screen_dir", "sync_time",
    "set_device_name", "set_auto_power_off", "set_memorial", "factory_reset",
    "send_notification", "set_fm_frequency", "set_alarm", "toggle_music_sync",
    "toggle_stocks_sync", "toggle_sysmon_sync", "toggle_weather_sync", "apply_stock_ticker",
    "play_gallery_art", "hot_channel_update", "custom_art_push", "device_call",
)

_MOCK_API = """
const __GIF = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
window.__fleet = {
  panels: {
    '%A%': {mac: '%A%', connected: true, selected: false, model: 'DitooPlus', width: 16, height: 16,
            model_source: 'name', features: {speaker: true}},
    '%B%': {mac: '%B%', connected: true, selected: false, model: 'Pixoo64Wifi', width: 64, height: 64,
            model_source: 'name', features: {speaker: false}},
  },
  calls: [],   // every device action: {m, args}
};
const __ACTIONS = %ACTIONS%;
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: Object.values(window.__fleet.panels)}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  get_alarms: (mac) => { window.__fleet.calls.push({m: 'get_alarms', args: [mac]}); return '[]'; },
  // A tile with a real preview: gallery.js drops a tile whose preview is
  // missing or will not decode (R64), 180ms after drawing it, so an empty
  // preview_url here was a broken asset the test raced to click.
  fetch_gallery: () => JSON.stringify([{file_id: 'f1', name: 'Art', likes: 1, preview_url: __GIF}]),
  get_animated_preview: () => __GIF,
  apply_stock_ticker: (...args) => { window.__fleet.calls.push({m: 'apply_stock_ticker', args});
      return JSON.stringify({success: true, price: 1, change: 0, preview: ''}); },
  custom_art_push: (...args) => { window.__fleet.calls.push({m: 'custom_art_push', args});
      return JSON.stringify({success: true, files_pushed: 1}); },
  device_call: (...args) => { window.__fleet.calls.push({m: 'device_call', args});
      return JSON.stringify({success: true}); },
  play_gallery_art: (...args) => { window.__fleet.calls.push({m: 'play_gallery_art', args});
      return {success: true}; },
  hot_channel_update: (...args) => { window.__fleet.calls.push({m: 'hot_channel_update', args});
      return JSON.stringify({success: true, started: true}); },
};
__ACTIONS.forEach(m => { if (!window.__api[m]) window.__api[m] = (...args) => {
    window.__fleet.calls.push({m, args}); return true; }; });
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
window.confirm = () => true;
window.prompt = () => 'RESET';
localStorage.setItem('divoom_custom_art_slots', JSON.stringify(
    [[{fileId: 'f1', thumb: ''}].concat(new Array(11).fill(null)), new Array(12).fill(null), new Array(12).fill(null)]));
""".replace("%A%", A).replace("%B%", B).replace("%ACTIONS%", repr(list(ACTIONS)))

_CLICK = "(s) => { const el = document.querySelector(s); if (!el) throw new Error('no ' + s); el.click(); }"

#: (what the user does, the JS that does it, the calls it must make)
GESTURES = [
    ("start sleep", "#sleep-start-btn", {"start_sleep"}),
    ("stop sleep", "#sleep-stop-btn", {"stop_sleep"}),
    ("stopwatch", ".tool-timer-btn", {"set_timer"}),
    ("countdown", "#countdown-start-btn", {"set_countdown"}),
    ("noise meter", "#noise-start-btn", {"set_noise"}),
    ("24-hour clock", "#hour24-seg .tab-btn", {"set_hour_type"}),
    ("orientation", "#screen-dir-tabs .tab-btn", {"set_screen_dir"}),
    ("sync time", "#sync-time-btn", {"sync_time"}),
    ("auto power off", "#auto-off-save", {"set_auto_power_off"}),
    ("anniversary", "#memorial-save", {"set_memorial"}),
    ("factory reset", "#factory-reset-btn", {"factory_reset"}),
    ("notification", "#notif-send", {"send_notification"}),
    ("FM radio", "#fm-tune-btn", {"set_fm_frequency"}),
    ("hot channel", "#hot-update-btn", {"hot_channel_update"}),
    ("custom art push", "#push-custom-art-btn", {"custom_art_push"}),
    ("custom art page", '#panel-design .page-tab[data-page="1"]', {"device_call"}),
    ("a live widget", "#widget-card-sysmon",
     {"toggle_music_sync", "toggle_stocks_sync", "toggle_sysmon_sync", "toggle_weather_sync"}),
]


async def _open(p):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage"
                        " && !!window.ChannelSettings && !!document.getElementById('sync-time-btn')"
                        " && !!document.querySelector('#panel-design .page-tab')")
    await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: 'Desk', kind: 'clock', state: 'active'},
        {address: b, name: 'Kitchen', kind: 'clock', state: 'active'}]})""", [A, B])
    await eval_js(page, "() => window.buildCustomArtSlots && window.buildCustomArtSlots()")
    return browser, page


async def _select(page, mac):
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", mac)
    await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{mac}'")


async def _settle(page, ms=150):
    await eval_js(page, f"() => new Promise(r => setTimeout(r, {ms}))")


async def _calls(page):
    return [(c["m"], c["args"]) for c in await eval_js(page, "() => window.__fleet.calls")
            if c["m"] in ACTIONS]


async def _clear(page):
    await eval_js(page, "() => { window.__fleet.calls = []; }")


@pytest.mark.asyncio
async def test_every_device_action_names_the_panel_clicked():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            for what, selector, expected in GESTURES:
                await _select(page, A)
                await _clear(page)
                await eval_js(page, _CLICK, selector)
                await _select(page, B)   # the user moves on at once
                await _settle(page)
                sent = await _calls(page)
                assert {m for m, _ in sent} >= expected, f"{what} did not call {expected}: {sent}"
                wrong = [(m, args) for m, args in sent if not args or args[0] != A]
                assert wrong == [], f"{what} must name A, the panel clicked: {wrong}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_rename_ticker_and_gallery_push_name_the_panel_clicked():
    """The three gestures that take an input first: a name, a symbol, a tile."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, A)
            await _clear(page)
            await eval_js(page, "() => { document.getElementById('device-name-input').value = 'Desk 2';"
                                " document.getElementById('device-name-save').click(); }")
            await _select(page, B)
            await eval_js(page, "() => window.displayTicker('AAPL')")   # B is selected now
            await _select(page, A)
            await eval_js(page, "() => window.loadGallery()")
            await wait_js(page, "() => !!document.querySelector('.gallery-item')")
            # A user looks at a tile before clicking it. The pause is longer
            # than gallery.js's broken-tile removal (180ms fade), so a fixture
            # tile the app judges broken goes red here instead of racing it.
            await _settle(page, 400)
            await eval_js(page, _CLICK, ".gallery-item")
            await _select(page, B)
            await _settle(page)
            sent = await _calls(page)
            named = {m: args[0] for m, args in sent}
            assert named.get("set_device_name") == A, sent
            assert named.get("apply_stock_ticker") == B, sent
            assert named.get("play_gallery_art") == A, sent
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_debounced_alarm_write_names_the_panel_clicked_not_the_one_selected_when_it_leaves():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _select(page, A)
            await eval_js(page, "() => window.dispatchEvent(new CustomEvent('tab-changed', {detail: {tab: 'routines'}}))")
            await wait_js(page, "() => window.__fleet.calls.some(c => c.m === 'get_alarms')")
            await _settle(page)
            await _clear(page)
            await eval_js(page, _CLICK, "#alarms-add-btn")
            await wait_js(page, "() => !!document.querySelector('#alarms-list .alarm-day-cell')")
            await eval_js(page, _CLICK, "#alarms-list .alarm-day-cell")   # debounced 500 ms
            await _select(page, B)
            await _settle(page, 800)
            sent = [(m, args) for m, args in await _calls(page) if m == "set_alarm"]
            assert len(sent) == 2, f"the add and the debounced day toggle: {sent}"
            assert all(args[0] == A for _, args in sent), f"every alarm write must name A: {sent}"

            # An edit while B is selected and the table is still A's reloads
            # B's alarms instead of writing A's table to B.
            await _clear(page)
            await eval_js(page, _CLICK, "#alarms-add-btn")
            await _settle(page)
            sent = await eval_js(page, "() => window.__fleet.calls")
            assert [c for c in sent if c["m"] == "set_alarm"] == [], sent
            assert {"m": "get_alarms", "args": [B]} in sent, sent
        finally:
            await browser.close()


def test_every_device_action_resolves_its_panel_in_one_place():
    """No device action asks "which panel" by itself: the mac comes from
    `ChannelSettings` (P5.2/P5.6), and nothing calls the old mac-less form."""
    writers = ("settings_features.js", "alarms_editor.js", "widgets.js", "gallery.js",
               "gallery_hot.js", "custom_art.js")
    for name in writers:
        js = (WEB_UI / name).read_text(encoding="utf-8")
        assert "requireDevice" not in js, f"{name} checks for 'a' device instead of naming one"
        assert "ChannelSettings" in js, f"{name} does not resolve its panel through ChannelSettings"
