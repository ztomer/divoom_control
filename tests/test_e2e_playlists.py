"""E2E — cloud playlist browser (Playlist/GetMyList), wired into the Pixel
Art panel's Playlists sub-tab. Drives the REAL web_ui in headless Chromium
with a mock ``window.pywebview.api``, same harness as test_e2e_clock_faces.py.

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
    get_my_playlists: () => [
        {PlayId: 42, Name: "Chill", Count: 3},
        {PlayId: 7, Name: "Party", Count: 12},
    ],
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open_playlists_tab(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    await page.click(".nav-btn[data-tab='pixel-art']")
    await page.click(".tab-btn[data-pixel-tab='pixel-playlists']")
    return browser, page


@pytest.mark.asyncio
async def test_playlists_tab_loads_the_users_cloud_playlists():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_playlists_tab(p)
        try:
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-playlist-list .cloud-clock-row').length > 0")
            names = await page.eval_on_selector_all(
                "#cloud-playlist-list .cloud-clock-name", "els => els.map(e => e.textContent)")
            assert names == ["Chill (3 items)", "Party (12 items)"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_push_without_a_device_shows_connect_prompt_and_does_not_call_push_playlist():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_playlists_tab(p)
        try:
            await eval_js(page, """() => {
                window.__pushPlaylistCalls = [];
                window.__api.push_playlist = (playId) => { window.__pushPlaylistCalls.push(playId); return { ok: true, error: '', cause: '' }; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-playlist-list .cloud-clock-row').length > 0")
            await page.click("#cloud-playlist-list .cloud-clock-apply-btn")
            await wait_js(page, 
                "() => document.getElementById('toast')?.classList.contains('show')")
            toast = await eval_js(page, "() => document.getElementById('toast').textContent")
            assert "Connect a device first" in toast
            calls = await eval_js(page, "() => window.__pushPlaylistCalls")
            assert calls == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_push_with_a_device_calls_push_playlist_with_the_real_play_id():
    """The whole point of this feature: pushing a browsed cloud playlist
    reuses the existing LAN Playlist/SendDevice path -- no new device-apply
    plumbing, just the real PlayId from Playlist/GetMyList."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_playlists_tab(p)
        try:
            await eval_js(page, """() => {
                window.DivoomState.appConnected = true;
                window.__pushPlaylistCalls = [];
                window.__api.push_playlist = (playId) => { window.__pushPlaylistCalls.push(playId); return { ok: true, error: '', cause: '' }; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-playlist-list .cloud-clock-row').length > 0")
            await page.click("#cloud-playlist-list .cloud-clock-apply-btn")
            await wait_js(page, "() => (window.__pushPlaylistCalls || []).length > 0")
            calls = await eval_js(page, "() => window.__pushPlaylistCalls")
            assert calls == [42]  # first row: Chill, PlayId 42
            await wait_js(page, 
                "() => document.getElementById('toast')?.textContent.includes('Playlist pushed')")
        finally:
            await browser.close()
