"""E2E — "Sync Now" (Routines > Auto-Sync): manually push hot-channel content
to every toggled sync target immediately, with per-device progress.

Drives the real web_ui with a mocked ``window.pywebview.api.sync_now`` and
the ``onSyncNowProgress``/``onSyncNowComplete`` events the backend fires
(see divoom_gui/gallery_hot_api.py::sync_now).
"""
import pytest
from pathlib import Path
from tests.support.browser import launch as launch_browser, require_browser

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

_MOCK_API = """
window.__syncNowCalls = 0;
window.__syncTargets = [
    {address: "AA:BB", name: "Pixoo", selected: true},
    {address: "CC:DD", name: "Timoo", selected: true},
];
window.__api = {
    sync_now: () => { window.__syncNowCalls++; return true; },
    get_sync_candidates: () => JSON.stringify(window.__syncTargets),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open_auto_sync_tab(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await page.add_init_script(_MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_function("() => !!window.DivoomState && !!window.renderSyncTargets")
    await page.click('.nav-btn[data-tab="routines"]')
    await page.wait_for_selector("#routines-schedule.active")
    await page.evaluate("""() => {
        window.renderSyncTargets([
            {address: "AA:BB", name: "Pixoo", selected: true},
            {address: "CC:DD", name: "Timoo", selected: true},
        ]);
    }""")
    return browser, page


@pytest.mark.asyncio
async def test_sync_now_button_calls_backend_and_disables_while_running():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_auto_sync_tab(p)
        try:
            await page.click("#sync-now-btn")
            calls = await page.evaluate("() => window.__syncNowCalls")
            assert calls == 1
            await page.wait_for_function(
                "() => document.getElementById('sync-now-btn').disabled === true")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_sync_now_progress_updates_the_right_device_row():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_auto_sync_tab(p)
        try:
            await page.click("#sync-now-btn")

            # Fire the progress/complete events and read the resulting row
            # text in ONE synchronous evaluate. The app's 1500ms
            # auto-refresh timer (gallery.js) can re-render the targets
            # list; collapsing render→assert into a single JS turn makes
            # the test immune to that race.
            result = await page.evaluate("""() => {
                window.renderSyncTargets(window.__syncTargets);
                window.onSyncNowProgress({address: "AA:BB", phase: "connecting"});
                window.onSyncNowProgress({address: "CC:DD", phase: "error", error: "unreachable"});
                const aa = document.querySelector('.sync-now-row-status[data-addr="AA:BB"]').textContent;
                const cc = document.querySelector('.sync-now-row-status[data-addr="CC:DD"]').textContent;
                window.onSyncNowProgress({address: "AA:BB", phase: "done", served: 3});
                window.onSyncNowComplete({total: 2, ok: 1, failed: 1});
                const aaDone = document.querySelector('.sync-now-row-status[data-addr="AA:BB"]').textContent;
                return { aa, cc, aaDone };
            }""")

            assert "Connecting" in result["aa"]
            assert "unreachable" in result["cc"]
            assert "3" in result["aaDone"]

            await page.wait_for_function(
                "() => document.getElementById('sync-now-btn').disabled === false")
            status = await page.text_content("#sync-now-status")
            assert "1/2" in status
        finally:
            await browser.close()
