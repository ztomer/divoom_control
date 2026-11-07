"""Shared page fixture for the device-chip E2E suites
(test_e2e_device_status_chips.py, test_e2e_device_chips_scan_merge.py)."""

from pathlib import Path

from tests.support.browser import add_init_js, launch as launch_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent.parent / "divoom_gui" / "web_ui" / "index.html"

# A permissive mock daemon API. `get_*` calls return "{}" (valid JSON the app
# parses); tests override individual methods via window.__api[name].
_MOCK_API = """
window.__api = {};
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
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    return browser, page
