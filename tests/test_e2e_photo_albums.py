"""E2E — photo album browser (Photo/GetAlbumList), wired into the Pixel Art
panel's Photo Albums sub-tab. Drives the REAL web_ui in headless Chromium
with a mock ``window.pywebview.api``, same harness as test_e2e_playlists.py.

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
    get_photo_albums: () => [
        {AlbumType: 0, ClockId: 7, ClockName: "Trip"},
        {AlbumType: 0, ClockId: 9, ClockName: "Family"},
    ],
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open_photo_albums_tab(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    await page.click(".nav-btn[data-tab='pixel-art']")
    await page.click(".tab-btn[data-pixel-tab='pixel-photo-albums']")
    return browser, page


@pytest.mark.asyncio
async def test_photo_albums_tab_loads_the_devices_albums():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_photo_albums_tab(p)
        try:
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-photo-album-list .cloud-clock-row').length > 0")
            names = await page.eval_on_selector_all(
                "#cloud-photo-album-list .cloud-clock-name", "els => els.map(e => e.textContent)")
            assert names == ["Trip", "Family"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_play_without_a_device_shows_connect_prompt_and_does_not_call_play_album():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_photo_albums_tab(p)
        try:
            await eval_js(page, """() => {
                window.__playAlbumCalls = [];
                window.__api.play_album = (albumId) => { window.__playAlbumCalls.push(albumId); return true; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-photo-album-list .cloud-clock-row').length > 0")
            await page.click("#cloud-photo-album-list .cloud-clock-apply-btn")
            await wait_js(page, 
                "() => document.getElementById('toast')?.classList.contains('show')")
            toast = await eval_js(page, "() => document.getElementById('toast').textContent")
            assert "Connect a device first" in toast
            calls = await eval_js(page, "() => window.__playAlbumCalls")
            assert calls == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_play_with_a_device_calls_play_album_with_the_real_album_id():
    """The whole point of this feature: playing a browsed photo album
    reuses the LAN-only Photo/PlayAlbum path -- just the real ClockId from
    Photo/GetAlbumList."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_photo_albums_tab(p)
        try:
            await eval_js(page, """() => {
                window.DivoomState.appConnected = true;
                window.__playAlbumCalls = [];
                window.__api.play_album = (albumId) => { window.__playAlbumCalls.push(albumId); return true; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-photo-album-list .cloud-clock-row').length > 0")
            await page.click("#cloud-photo-album-list .cloud-clock-apply-btn")
            await wait_js(page, "() => (window.__playAlbumCalls || []).length > 0")
            calls = await eval_js(page, "() => window.__playAlbumCalls")
            assert calls == [7]  # first row: Trip, ClockId 7
            await wait_js(page, 
                "() => document.getElementById('toast')?.textContent.includes('Album playing')")
        finally:
            await browser.close()
