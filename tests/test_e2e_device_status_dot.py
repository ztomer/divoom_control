"""E2E device-status reporting — the appbar connection-state dot.

Drives the real web_ui in headless Chromium with a mock ``pywebview.api`` and
asserts the global status dot always reflects the device's REAL link state
(connected / degraded / disconnected) and never a stale or misleading one.

The dot is driven by the EVENT path R59 shipped: the GUI subscribes to the
daemon and forwards every ``status`` event to ``window.Divoom.onDaemonEvent``
(see divoom_gui/web_ui/connection_events.js). The old 4s ``refreshConnectionState``
polling heartbeat is gone (kept only as a documented safety net — one test
below still exercises it). Backend honesty (ScannerMixin.get_connection_state)
is in ``test_device_status.py``; per-device chips in
``test_e2e_device_status_chips.py``. Skipped if Playwright / a browser isn't
installed.
"""
import pytest
from pathlib import Path
from tests.support.browser import launch as launch_browser, require_browser

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

# A permissive mock daemon API. `get_*` calls return "{}" (valid JSON the app
# parses); tests override individual methods via window.__api[name]. Non-get
# calls (e.g. connect_single_device) resolve to `true` so connectDevice takes
# its success path.
_MOCK_API = """
window.__api = {};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""

# R59 live handler the daemon status events are forwarded to.
_STATUS_EVENT = "window.Divoom.onDaemonEvent"


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await page.add_init_script(_MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_function(
        "() => !!window.DivoomState && !!window.renderDeviceDots"
        " && !!window.Divoom && !!window.Divoom.onDaemonEvent")
    return browser, page


def _dot_cls(page):
    return page.evaluate(
        "() => document.getElementById('global-status-dot').className")


def _dot_info(page):
    return page.evaluate("""() => ({
        cls: document.getElementById('global-status-dot').className,
        title: document.getElementById('global-status-dot').title,
        connected: window.DivoomState.appConnected })""")


@pytest.mark.asyncio
async def test_status_dot_connected_ble():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                window.DivoomState.discoveredDevices = [{{address:'AA:BB:CC', name:'Ditoo'}}];
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'connected', mac:'AA:BB:CC'}});
            }}""")
            info = await _dot_info(page)
            assert "transport-dot" in info["cls"]
            assert "active" in info["cls"] and "ble" in info["cls"]
            assert info["title"] == "Connected"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_connected_lan():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'connected', lan_ip:'10.0.0.5'}});
            }}""")
            cls = await _dot_cls(page)
            assert "active" in cls and "lan" in cls
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_connected_wall():
    # The wall has no daemon `status` event of its own — its dot is set by the
    # real connectDevice path (connection_events.js:53), which is the live code.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate("() => window.connectDevice('Virtual Wall', 'MatrixWall')")
            await page.wait_for_function(
                "() => document.getElementById('global-status-dot')"
                ".className.includes('wall')", timeout=4000)
            cls = await _dot_cls(page)
            assert "active" in cls and "wall" in cls
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_degraded_keeps_appconnected():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'degraded', mac:'AA'}});
            }}""")
            info = await _dot_info(page)
            assert "degraded" in info["cls"]
            assert info["connected"] is True           # self-heal may revive it
            assert "reconnect" in info["title"].lower()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_disconnected_flips_appconnected():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:false}});
            }}""")
            info = await _dot_info(page)
            assert "inactive" in info["cls"]
            assert info["connected"] is False          # UI stops claiming a link
            assert info["title"] == "Disconnected"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_state_disconnected_overrides_stale_connected():
    """Regression: a daemon reporting connected:true but state:disconnected must
    show DISCONNECTED (amber/green would lie). This is the honest-state fix."""
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'disconnected', mac:'AA'}});
            }}""")
            connected = await page.evaluate("() => window.DivoomState.appConnected")
            cls = await _dot_cls(page)
            assert "inactive" in cls
            assert connected is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_malformed_event_leaves_dot_untouched():
    # onDaemonEvent guards on a null/non-object event and returns early, so the
    # dot keeps whatever the last valid event set.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                window.DivoomState.appConnected = true;
                const d = document.getElementById('global-status-dot');
                d.className = 'transport-dot active ble';
                d.title = 'pinned';
                {_STATUS_EVENT}(null);
                {_STATUS_EVENT}({{}});
            }}""")
            info = await _dot_info(page)
            assert info["cls"] == "transport-dot active ble"   # unchanged
            assert info["title"] == "pinned"
            assert info["connected"] is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_event_is_authoritative():
    # In the event model a disconnect event ALWAYS wins (it's the source of
    # truth), even if the UI currently thinks it's connected — there's no
    # appConnected gate like the old polling safety net had.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate(f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:false}});
            }}""")
            res = await page.evaluate(
                "() => { const d=document.getElementById('global-status-dot');"
                " return {cls:d.className, hasActive:d.classList.contains('active'),"
                " hasInactive:d.classList.contains('inactive')}; }")
            assert res["hasInactive"] is True and res["hasActive"] is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_safety_net_refresh_connection_state():
    # The 4s polling heartbeat was removed, but refreshConnectionState is kept
    # as a documented fallback. This guards it still flips the dot honestly when
    # driven directly (e.g. a future re-enable).
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate("""() => {
                window.DivoomState.appConnected = true;
                document.getElementById('banner-device-mac').textContent = 'AA:BB:CC';
                window.__api.get_connection_state = () =>
                    JSON.stringify({connected:false, state:'disconnected'});
                return window.refreshConnectionState();
            }""")
            await page.wait_for_function(
                "() => document.getElementById('global-status-dot')"
                ".className.includes('inactive')", timeout=4000)
            info = await _dot_info(page)
            assert "inactive" in info["cls"]
            assert info["connected"] is False
        finally:
            await browser.close()
