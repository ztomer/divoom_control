"""E2E — Hot Channel "Update" button re-enables after a completed sync.

Regression: `window.Divoom.onHotProgress` calls `window.applyProgress`/
`window.finishProgress`, but those were closure-local in gallery_hot.js (never
exposed on `window`), so both calls silently no-op'd and `resetButton()`
(only reachable via `finishProgress`) never ran — the button stayed disabled
forever after the first click. Drives the real event path end to end:
click -> hot_channel_update() -> window.Divoom.onHotProgress("done") -> the
button must re-enable.
"""
import pytest
from pathlib import Path
from tests.support.browser import launch as launch_browser, require_browser

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

_MOCK_API = """
window.__api = {
    hot_channel_update: () => true,
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open_hot_channel_tab(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await page.add_init_script(_MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_function("() => !!window.DivoomState && !!window.Divoom")
    await page.click('.nav-btn[data-tab="pixel-art"]')
    await page.click('[data-pixel-tab="pixel-hot-channel"]')
    await page.wait_for_selector("#pixel-hot-channel.active")
    return browser, page


@pytest.mark.asyncio
async def test_hot_channel_button_reenables_after_done_event():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_hot_channel_tab(p)
        try:
            await page.evaluate("() => { window.DivoomState.appConnected = true; }")
            await page.click("#hot-update-btn")
            await page.wait_for_function(
                "() => document.getElementById('hot-update-btn').disabled === true")

            # Simulate the daemon's real completion event.
            await page.evaluate("""() => {
                window.Divoom.onHotProgress({
                    type: "hot_progress", phase: "done",
                    result: { served: ["a.gif"], manifest: 1, downloaded: 1 },
                });
            }""")

            await page.wait_for_function(
                "() => document.getElementById('hot-update-btn').disabled === false",
                timeout=5000)
            disabled = await page.evaluate(
                "() => document.getElementById('hot-update-btn').disabled")
            assert disabled is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_hot_channel_button_reenables_after_error_event():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_hot_channel_tab(p)
        try:
            await page.evaluate("() => { window.DivoomState.appConnected = true; }")
            await page.click("#hot-update-btn")
            await page.wait_for_function(
                "() => document.getElementById('hot-update-btn').disabled === true")

            await page.evaluate("""() => {
                window.Divoom.onHotProgress({ type: "hot_progress", phase: "error", error: "boom" });
            }""")

            await page.wait_for_function(
                "() => document.getElementById('hot-update-btn').disabled === false",
                timeout=5000)
        finally:
            await browser.close()
