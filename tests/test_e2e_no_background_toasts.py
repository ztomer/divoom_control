"""E2E -- a page nobody touched raises no toast (UI rule 4: alarm is for faults).

Found in the U.5 inventory (``docs/assets/hot-status-today.png``): every row of
the Hot tab carried "Scan failed (device backend unavailable). See logs." --
the app's own startup scan, which nobody asked for, toasting its outcome over
whatever screen was open. The harness had learned to live with it
(``tests/support/browser.py`` keyed every toast wait on its own text because
"the app raises toasts on its own"). That is the class: work the app starts by
itself reporting through the one channel that means "you did something, here
is what happened". Its outcome belongs where the work lives (the scan card's
``#scan-result``); a real fault (the daemon gone) has its own indicator.

So: load the real web UI against a bridge that answers "nothing here" to every
read (so startup runs all the way through, including its scan) and FAILS the
scan, touch nothing, and no toast may appear. (A bridge that fails EVERY call
is a blind instrument: startup stops at its first read, the scan never runs,
and the old code passed.)
"""

import pytest

from tests.support.browser import (
    add_init_js,
    eval_js,
    install_toast_recorder,
    launch,
    require_browser,
    wait_js,
)
from tests.support.browser_startup import wait_startup_scan
from tests.test_e2e_hot_channel_sync_button import INDEX_HTML

_FAILING_API = """
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (name === 'scan_devices') return Promise.reject(new Error('backend gone: scan_devices'));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


@pytest.mark.asyncio
async def test_an_untouched_page_raises_no_toast_even_when_its_scan_fails():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch(p)
        page = await browser.new_page()
        await add_init_js(page, _FAILING_API)
        await install_toast_recorder(page)
        await page.goto(f"file://{INDEX_HTML}")
        try:
            await wait_js(page, "() => !!window.DivoomState && !!window.runBleScan")
            # The startup scan has run and reported (it toasted in the same
            # call, before the report, if it toasted at all) -- the event, not
            # a 4 s sleep a loaded machine can finish before the scan starts.
            await wait_startup_scan(page)
            toasts = await eval_js(page, "() => window.__divoomToasts.map(t => t.message)")
            assert toasts == [], f"background work toasted: {toasts}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_startup_scans_failure_is_said_in_the_scan_card():
    """Not toasted is not silent: the scan card says what the scan did."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch(p)
        page = await browser.new_page()
        await add_init_js(page, _FAILING_API)
        await page.goto(f"file://{INDEX_HTML}")
        try:
            await wait_js(page, "() => !!window.runBleScan")
            await eval_js(page, "() => window.runBleScan({auto: true})")
            await wait_js(
                page, "() => (document.getElementById('scan-result')?.textContent || '').includes('Scan failed')"
            )
            text = await eval_js(page, "() => document.getElementById('scan-result').textContent")
            assert text.startswith("✗ Scan failed: backend gone"), text
        finally:
            await browser.close()
