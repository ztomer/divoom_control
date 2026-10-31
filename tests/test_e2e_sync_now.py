"""E2E — "Sync Now" (Routines > Auto-Sync): manually push hot-channel content
to every toggled sync target immediately, with per-device progress.

Drives the real web_ui with a mocked ``window.pywebview.api.sync_now`` and
the ``onSyncNowProgress``/``onSyncNowComplete`` events the backend fires
(see divoom_gui/gallery_hot_api.py::sync_now).
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
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderSyncTargets")
    await page.click('.nav-btn[data-tab="routines"]')
    await page.wait_for_selector("#routines-schedule.active")
    await eval_js(page, """() => {
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
            calls = await eval_js(page, "() => window.__syncNowCalls")
            assert calls == 1
            await wait_js(page, 
                "() => document.getElementById('sync-now-btn').disabled === true")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_sync_now_rows_show_checking_then_the_panels_record():
    """U.5: while a panel is being checked its row says so; when its run ends
    the row is the daemon's record of that panel -- the short verdict line --
    and nothing of it vanishes on the next render."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_auto_sync_tab(p)
        try:
            await page.click("#sync-now-btn")
            result = await eval_js(page, """async () => {
                const now = Math.floor(Date.now() / 1000);
                window.__verdicts = {};
                window.__api.hot_verdict = (mac) => JSON.stringify(window.__verdicts[mac] || {});
                window.__api.hot_verdicts = () => JSON.stringify(window.__verdicts);
                const row = (m) => document.querySelector(`.sync-now-row-status[data-addr="${m}"]`);
                window.onSyncNowProgress({address: "AA:BB", phase: "checking", index: 1, total: 2});
                const checking = row("AA:BB").textContent;
                window.__verdicts["AA:BB"] = {at: now - 60, by: "sync_now", outcome: "ok",
                                              offered: 23, fetched: 23, delivered: 3};
                window.__verdicts["CC:DD"] = {at: now - 30, by: "sync_now", outcome: "failed",
                                              error: "device 'CC:DD' not connected"};
                window.onSyncNowProgress({address: "AA:BB", phase: "finished"});
                window.onSyncNowProgress({address: "CC:DD", phase: "finished"});
                window.onSyncNowComplete({total: 2});
                await new Promise(r => setTimeout(r, 50));
                window.renderSyncTargets(window.__syncTargets);   // a re-render keeps it
                await new Promise(r => setTimeout(r, 50));
                return {checking, aa: row("AA:BB").textContent, aaKind: row("AA:BB").dataset.kind,
                        cc: row("CC:DD").textContent, ccKind: row("CC:DD").dataset.kind};
            }""")
            assert "Checking now (1 of 2)" in result["checking"], result
            assert result["aa"].startswith("↓") and "3 new" in result["aa"], result
            assert result["aaKind"] == "new", result
            assert result["cc"].startswith("✗") and "Failed" in result["cc"], result
            assert result["ccKind"] == "fail", result
            await wait_js(page,
                "() => document.getElementById('sync-now-btn').disabled === false")
        finally:
            await browser.close()
