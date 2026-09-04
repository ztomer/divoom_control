"""The user's widget choice must survive the background reconciler.

`restoreActiveWidgetForDevice` polls the daemon's live-job list to restore what
a device is actually showing. It used to force `selectedWidget = "music"`
whenever no job was running — which meant clicking System Monitor selected it
for about 250ms before a poll took it straight back.

That was not a cosmetic flicker. The Live (5s) refresh only runs while its own
widget is selected, so the System Monitor card sat frozen on the single reading
it managed before being deselected, with its Live toggle still showing ON.
Measured at 250ms resolution against the real page: true at 0ms, false at 250ms,
and the numbers never moved again.

House rule: resolve user intent at interaction time, and never silently swallow
a click. A running job is real state worth ADOPTING; "no job running" is not
evidence about what the user wants — most often it just means no device is
connected yet, which is exactly when someone is clicking around the widgets.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch as launch_browser, require_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

# A device is present (so the reconciler does NOT early-return on a falsy mac)
# and it has no live jobs — the exact combination that used to clobber.
_MOCK_API = """
window.__api = {
    live_job_list: () => JSON.stringify({success: true, jobs: []}),
    get_system_stats_preview: () => JSON.stringify({
        ok: true, size: 16, stats: {cpu: 11, mem: 22, battery: 33}, preview: ""}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.selectedWidgetIs")
    await page.click('.nav-btn[data-tab="data-sources"]')
    await page.wait_for_selector("#widget-card-sysmon")
    return browser, page


@pytest.mark.asyncio
async def test_selecting_a_widget_survives_the_reconciler_with_no_active_job():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => document.getElementById('widget-card-sysmon').click()")
            assert await eval_js(page, "() => window.selectedWidgetIs('sysmon')") is True

            # Run the reconciler the way the app does, with a device present and
            # no jobs. This is the call that used to undo the click.
            await eval_js(page, "() => window.restoreActiveWidgetForDevice('AA:BB:CC:DD:EE:FF')")
            await page.wait_for_timeout(400)

            assert await eval_js(page, "() => window.selectedWidgetIs('sysmon')") is True, (
                "the reconciler must not override an explicit selection when the "
                "device simply has no live job running"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_selected_card_keeps_its_active_styling():
    """The class drives the visible highlight, so it must track the selection."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => document.getElementById('widget-card-sysmon').click()")
            await eval_js(page, "() => window.restoreActiveWidgetForDevice('AA:BB:CC:DD:EE:FF')")
            await page.wait_for_timeout(400)
            active = await eval_js(
                page,
                "() => document.getElementById('widget-card-sysmon')"
                ".classList.contains('widget-active')")
            assert active is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_running_job_is_still_adopted():
    """The reconciler's real purpose must survive the fix.

    If the device IS running a job, that is authoritative state and the UI
    should follow it — otherwise this change would have traded one wrong
    behaviour for another.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => document.getElementById('widget-card-sysmon').click()")
            await eval_js(page, """() => {
                window.__api.live_job_list = () => JSON.stringify(
                    {success: true, jobs: [{kind: 'weather', done: false, cancelled: false}]});
            }""")
            await eval_js(page, "() => window.restoreActiveWidgetForDevice('AA:BB:CC:DD:EE:FF')")
            await page.wait_for_timeout(400)

            assert await eval_js(page, "() => window.selectedWidgetIs('weather')") is True, (
                "a live job on the device is authoritative and must be adopted"
            )
        finally:
            await browser.close()
