"""E2E — cloud AidSleep sound library browser (AidSleep/GetAllList), wired
into the Schedule panel's Sleep Sounds sub-tab. Drives the REAL web_ui in
headless Chromium with a mock ``window.pywebview.api``, same harness as
test_e2e_playlists.py.

Skipped if Playwright / a browser isn't installed.
"""
import pytest
from pathlib import Path
from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

_MOCK_API = """
window.__api = {
    get_aid_sleep_list: (sleepType) => {
        if (sleepType === 0) return [
            {SleepId: 256, Name: "Gentle Rain"},
            {SleepId: 258, Name: "Window Rain"},
        ];
        if (sleepType === 1) return [{SleepId: 400, Name: "Fan Hum"}];
        return [];
    },
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open_sleep_sounds_tab(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    await page.click(".nav-btn[data-tab='routines']")
    await page.click(".tab-btn[data-routines-tab='routines-sleep-sounds']")
    return browser, page


@pytest.mark.asyncio
async def test_sleep_sounds_tab_loads_the_default_type_on_open():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_sleep_sounds_tab(p)
        try:
            await wait_js(page, 
                "() => document.querySelectorAll('#aid-sleep-list .cloud-clock-row').length > 0")
            names = await page.eval_on_selector_all(
                "#aid-sleep-list .cloud-clock-name", "els => els.map(e => e.textContent)")
            assert names == ["Gentle Rain", "Window Rain"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_switching_sound_type_reloads_the_list():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_sleep_sounds_tab(p)
        try:
            await wait_js(page, 
                "() => document.querySelectorAll('#aid-sleep-list .cloud-clock-row').length > 0")
            await page.click("#aid-sleep-type-tabs .tab-btn[data-sleep-type='1']")
            await wait_js(page, 
                "() => document.querySelector('#aid-sleep-list .cloud-clock-name')?.textContent === 'Fan Hum'")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_play_without_a_device_shows_connect_prompt_and_does_not_call_play_aid_sleep():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_sleep_sounds_tab(p)
        try:
            await eval_js(page, """() => {
                window.__playAidSleepCalls = [];
                window.__api.play_aid_sleep = (sleepId, type) => { window.__playAidSleepCalls.push([sleepId, type]); return true; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#aid-sleep-list .cloud-clock-row').length > 0")
            await page.click("#aid-sleep-list .cloud-clock-apply-btn")
            await wait_js(page, 
                "() => document.getElementById('toast')?.classList.contains('show')")
            toast = await eval_js(page, "() => document.getElementById('toast').textContent")
            assert "Connect a device first" in toast
            calls = await eval_js(page, "() => window.__playAidSleepCalls")
            assert calls == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_play_with_a_device_calls_play_aid_sleep_with_the_real_sleep_id():
    """The whole point of this feature: playing a browsed cloud sleep sound
    reuses the AidSleep/Play BLE-only path (no cloud round-trip) -- just the
    real SleepId from AidSleep/GetAllList."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_sleep_sounds_tab(p)
        try:
            await eval_js(page, """() => {
                window.DivoomState.appConnected = true;
                window.__playAidSleepCalls = [];
                window.__api.play_aid_sleep = (sleepId, type) => { window.__playAidSleepCalls.push([sleepId, type]); return true; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#aid-sleep-list .cloud-clock-row').length > 0")
            await page.click("#aid-sleep-list .cloud-clock-apply-btn")
            await wait_js(page, "() => (window.__playAidSleepCalls || []).length > 0")
            calls = await eval_js(page, "() => window.__playAidSleepCalls")
            assert calls == [[256, 0]]  # first row: Gentle Rain, SleepId 256, type 0
            await wait_js(page, 
                "() => document.getElementById('toast')?.textContent.includes('Playing on device')")
        finally:
            await browser.close()
