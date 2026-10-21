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
from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

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
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, 
        "() => !!window.DivoomState && !!window.renderDeviceDots"
        " && !!window.Divoom && !!window.Divoom.onDaemonEvent")
    return browser, page


def _dot_cls(page):
    return eval_js(page, 
        "() => document.getElementById('global-status-dot').className")


def _dot_info(page):
    # P7.2: the dot carries its state in the aria-label the funnel writes.
    # It has no `title`: the dot is pointer-events:none, so the pointer never
    # reached it and the browser never showed the title the funnel used to
    # write — a name no user had ever been able to see.
    return eval_js(page, """() => ({
        cls: document.getElementById('global-status-dot').className,
        label: document.getElementById('global-status-dot')
            .getAttribute('aria-label'),
        title: document.getElementById('global-status-dot').getAttribute('title'),
        connected: window.DivoomState.appConnected })""")


@pytest.mark.asyncio
async def test_status_dot_connected_ble():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, f"""() => {{
                window.DivoomState.discoveredDevices = [{{address:'AA:BB:CC', name:'Ditoo'}}];
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'connected', mac:'AA:BB:CC'}});
            }}""")
            info = await _dot_info(page)
            assert "transport-mark" in info["cls"]
            assert "mark-linked" in info["cls"] and "mark-ble" in info["cls"]
            assert info["label"] == "Connection status: connected — Bluetooth screen"
            assert info["title"] is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_connected_lan():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, f"""() => {{
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'connected', lan_ip:'10.0.0.5'}});
            }}""")
            cls = await _dot_cls(page)
            assert "mark-linked" in cls and "mark-lan" in cls
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
            await eval_js(page, "() => window.connectDevice('Virtual Wall', 'MatrixWall')")
            await wait_js(page, 
                "() => document.getElementById('global-status-dot')"
                ".className.includes('wall')", timeout=4000)
            cls = await _dot_cls(page)
            assert "mark-linked" in cls and "mark-wall" in cls
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_degraded_keeps_appconnected():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'degraded', mac:'AA'}});
            }}""")
            info = await _dot_info(page)
            assert "mark-fault" in info["cls"]
            assert info["connected"] is True           # self-heal may revive it
            assert "reconnect" in info["label"].lower()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_status_dot_disconnected_flips_appconnected():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:false}});
            }}""")
            info = await _dot_info(page)
            assert "mark-open" in info["cls"]
            assert info["connected"] is False          # UI stops claiming a link
            assert info["label"] == "Connection status: disconnected"
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
            await eval_js(page, f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:true,
                    state:'disconnected', mac:'AA'}});
            }}""")
            connected = await eval_js(page, "() => window.DivoomState.appConnected")
            cls = await _dot_cls(page)
            assert "mark-open" in cls
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
            await eval_js(page, f"""() => {{
                window.DivoomState.appConnected = true;
                const d = document.getElementById('global-status-dot');
                d.className = 'transport-mark mark-ble mark-linked';
                d.setAttribute('aria-label', 'pinned');
                {_STATUS_EVENT}(null);
                {_STATUS_EVENT}({{}});
            }}""")
            info = await _dot_info(page)
            assert info["cls"] == "transport-mark mark-ble mark-linked"   # unchanged
            assert info["label"] == "pinned"
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
            await eval_js(page, f"""() => {{
                window.DivoomState.appConnected = true;
                {_STATUS_EVENT}({{type:'status', connected:false}});
            }}""")
            res = await eval_js(page,
                "() => { const d=document.getElementById('global-status-dot');"
                " return {cls:d.className, hasOpen:d.classList.contains('mark-open'),"
                " hasLinked:d.classList.contains('mark-linked')}; }")
            assert res["hasOpen"] is True and res["hasLinked"] is False
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
            await eval_js(page, """() => {
                window.DivoomState.appConnected = true;
                document.getElementById('banner-device-mac').textContent = 'AA:BB:CC';
                window.__api.get_connection_state = () =>
                    JSON.stringify({connected:false, state:'disconnected'});
                return window.refreshConnectionState();
            }""")
            await wait_js(page,
                "() => document.getElementById('global-status-dot')"
                ".className.includes('mark-open')", timeout=4000)
            info = await _dot_info(page)
            assert "mark-open" in info["cls"]
            assert info["connected"] is False
        finally:
            await browser.close()
