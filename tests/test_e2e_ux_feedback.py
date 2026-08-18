"""E2E UX-feedback tests — the user must always be able to see WHAT IS HAPPENING.

Every meaningful state transition (scanning, connecting, connected, failed, a
device streaming a live widget, a degraded link, a configured wall) must surface
visible feedback in the UI. These drive the REAL web_ui in headless Chromium with
a mock ``window.pywebview.api`` and assert the feedback element appears — closing
"knowledge gaps" where the app does something but says nothing.

Skipped if Playwright / a browser isn't installed.
"""
import pytest
from pathlib import Path
from tests.support.browser import launch as launch_browser, require_browser

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

# Injected before any page script: a permissive mock daemon API. `get_*` calls
# return "{}" (valid JSON the app parses), everything else resolves truthy.
# Tests override individual methods via window.__api[name].
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
    await page.add_init_script(_MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_function("() => !!window.DivoomState && !!window.renderDeviceDots")
    return browser, page


@pytest.mark.asyncio
async def test_scan_shows_progress_then_result():
    """While scanning, a 'Scanning…' indicator is visible; afterwards it hides and
    a result toast reports the count — the user is never left wondering."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate("""() => {
                window.__api.scan_devices = () => new Promise(r => setTimeout(
                    () => r(JSON.stringify([{address:'AA',name:'Ditoo'},
                                            {address:'BB',name:'Pixoo'}])), 150));
                window.runBleScan();
            }""")
            # During the scan the indicator must be visible.
            assert await page.evaluate(
                "() => document.getElementById('scan-indicator').hidden") is False
            # Afterwards: hidden again + a 'Discovered 2' toast that's actually shown.
            await page.wait_for_function(
                "() => document.getElementById('scan-indicator').hidden === true",
                timeout=4000)
            toast = await page.evaluate(
                "() => ({c: document.getElementById('toast').className,"
                "        t: document.getElementById('toast').textContent})")
            assert "show" in toast["c"]
            assert "Discovered" in toast["t"] and "2" in toast["t"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_connect_shows_connecting_then_connected():
    """Connecting raises an immediate 'Connecting…' toast + a connecting pulse, and
    success flips to a 'Connected' toast, an active dot, and the device banner."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate("""() => {
                window.__api.connect_single_device = () =>
                    new Promise(r => setTimeout(() => r(true), 120));
                window.__api.get_device_name = () => 'Ditoo';   // realistic readback
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.renderDeviceDots();
                window.connectDevice('Ditoo', 'AA');
            }""")
            # Immediately: feedback that a connect is in flight.
            mid = await page.evaluate("""() => ({
                toast: document.getElementById('toast').textContent,
                connecting: !!document.querySelector('#device-dots .device-chip.connecting')
                          || (document.getElementById('global-status-dot')||{}).className
                             ?.includes('connecting')
            })""")
            assert "Connecting to Ditoo" in mid["toast"]
            assert mid["connecting"]
            # After success: connected toast + active state + banner names the device.
            await page.wait_for_function(
                "() => window.DivoomState.appConnected === true", timeout=4000)
            done = await page.evaluate("""() => ({
                toast: document.getElementById('toast').textContent,
                active: !!document.querySelector('#device-dots .device-chip.chip-active'),
                banner: document.getElementById('banner-device-name').textContent
            })""")
            assert "Connected to Ditoo" in done["toast"]
            assert done["active"] is True
            assert done["banner"] == "Ditoo"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_connect_failure_surfaces_the_reason():
    """A failed connect must explain WHY (the daemon's actionable reason), not fail
    silently — and reset the banner so nothing looks connected."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate("""() => {
                window.__api.connect_single_device = () => Promise.resolve(false);
                window.__api.get_last_connect_error = () =>
                    'Asleep or out of range — wake the screen and retry.';
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.renderDeviceDots();
                window.connectDevice('Ditoo', 'AA');
            }""")
            await page.wait_for_function(
                "() => /Asleep or out of range/.test(document.getElementById('toast').textContent)",
                timeout=4000)
            res = await page.evaluate("""() => ({
                toastClass: document.getElementById('toast').className,
                banner: document.getElementById('banner-device-name').textContent,
                connected: window.DivoomState.appConnected
            })""")
            assert "error" in res["toastClass"]
            assert res["banner"] == "None"          # nothing looks connected
            assert res["connected"] is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_action_without_device_guides_the_user():
    """Triggering a device action with nothing connected must tell the user what to
    do, not no-op silently."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await page.evaluate("""() => {
                window.DivoomState.appConnected = false;
                const ok = window.requireDevice();
                return { ok, toast: document.getElementById('toast').textContent,
                         cls: document.getElementById('toast').className };
            }""")
            assert res["ok"] is False
            assert "Connect a device first" in res["toast"]
            assert "error" in res["cls"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_streaming_and_degraded_devices_are_visibly_distinct():
    """A daemon-owned device streaming a live widget shows a 'streaming' ring; a
    degraded link shows a distinct 'reconnecting' state — so a busy or struggling
    screen is never indistinguishable from an idle one."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            streaming = await page.evaluate("""() => {
                window.DivoomState.discoveredDevices = [{
                    address:'AA', name:'Ditoo', daemonOwned:true,
                    activityKind:'music', activityState:'connected'}];
                window.renderDeviceDots();
                const d = document.querySelector('#device-dots .device-chip');
                return { streaming: d.classList.contains('chip-streaming'),
                         state: d.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert streaming["streaming"] is True
            assert "music" in streaming["state"]

            degraded = await page.evaluate("""() => {
                window.DivoomState.discoveredDevices[0].activityState = 'degraded';
                window.renderDeviceDots();
                const d = document.querySelector('#device-dots .device-chip');
                return { degraded: d.classList.contains('chip-degraded'),
                         state: d.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert degraded["degraded"] is True
            assert "reconnecting" in degraded["state"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_scan_failure_is_surfaced_not_silent():
    """If the scan backend dies, the user is told (error toast) and the spinner is
    cleared — not left spinning forever."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.evaluate("""() => {
                window.__api.scan_devices = () => Promise.reject(new Error('backend gone'));
                window.runBleScan();
            }""")
            await page.wait_for_function(
                "() => /Scan failed/i.test(document.getElementById('toast').textContent)",
                timeout=4000)
            res = await page.evaluate("""() => ({
                cls: document.getElementById('toast').className,
                spinnerHidden: document.getElementById('scan-indicator').hidden
            })""")
            assert "error" in res["cls"]
            assert res["spinnerHidden"] is True   # not stuck "scanning…"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_degraded_link_shows_distinct_state():
    """A link that reports connected-but-failing (DEGRADED) shows a distinct amber
    state + a 'reconnecting' hint on the appbar dot — not a misleading solid OK."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await page.evaluate("""() => {
                window.DivoomState.appConnected = true;
                window.__api.get_connection_state = () =>
                    JSON.stringify({connected:true, state:'degraded'});
                return window.refreshConnectionState();
            }""")
            await page.wait_for_function(
                "() => (document.getElementById('global-status-dot')||{}).className"
                "        ?.includes('degraded')", timeout=4000)
            title = await page.evaluate(
                "() => document.getElementById('global-status-dot').title")
            assert "degraded" in title.lower() or "reconnect" in title.lower()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_gallery_requests_the_active_device_resolution():
    """Regression: the community gallery must fetch art at the active device's
    panel size — not always 16px. (banner-device-res moved to Settings, so the old
    reader always hit the 16x16 fallback, shipping 16px art to a 64px Pixoo.)"""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.wait_for_function("() => typeof window.readGalleryTargetSize === 'function'")
            sizes = await page.evaluate("""() => {
                const banner = document.getElementById('banner-device-name');
                const out = {};
                banner.textContent = 'Pixoo64'; out.pixoo64 = window.readGalleryTargetSize();
                banner.textContent = 'Ditoo';   out.ditoo   = window.readGalleryTargetSize();
                return out;
            }""")
            assert sizes["pixoo64"] == 64    # was always 16 before the fix
            assert sizes["ditoo"] == 16
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_wall_button_communicates_screen_count():
    """The Virtual Wall affordance only appears when a wall is configured and tells
    the user how many screens it drives."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            hidden0 = await page.evaluate("""() => {
                window.DivoomState.assignedSlots = {};
                window.renderWallButton();
                return document.getElementById('wall-button').hidden;
            }""")
            assert hidden0 is True   # no empty control

            shown = await page.evaluate("""() => {
                window.DivoomState.assignedSlots = {AA:{}, BB:{}, CC:{}};
                window.renderWallButton();
                const host = document.getElementById('wall-button');
                return { hidden: host.hidden, text: host.textContent,
                         hasGlyph: !!host.querySelector('svg') };
            }""")
            assert shown["hidden"] is False
            assert "Wall" in shown["text"] and "3" in shown["text"]
            assert shown["hasGlyph"] is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_known_but_undetected_device_shows_distinct_state():
    """A device seen in a previous session but missed by the current scan must
    still appear in the sidebar as a distinct 'known' chip — not vanish. Closing
    the "known device that wasn't detected" gap (R50)."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            # Render the current scan result synchronously...
            await page.evaluate("""() => {
                window.DivoomState.discoveredDevices = [
                    {address:'AA', name:'Ditoo'}, {address:'BB', name:'Pixoo'}];
                window.renderDeviceDots();
            }""")
            # ...then trigger the async known-devices fetch.
            await page.evaluate("""() => {
                window.__api.get_known_devices = () =>
                    JSON.stringify([{address:'CC', name:'Tivoo', detected:false}]);
                window.refreshKnownDevices();
            }""")
            # Wait for the async fetch + re-render to land the CC chip.
            await page.wait_for_function(
                "() => !!document.querySelector('#device-dots .device-chip[data-value=\"CC\"]')",
                timeout=4000)
            res = await page.evaluate("""() => {
                const chips = [...document.querySelectorAll('#device-dots .device-chip')];
                const cc = chips.find(c => c.dataset.value === 'CC');
                const aa = chips.find(c => c.dataset.value === 'AA');
                return {
                    count: chips.length,
                    ccExists: !!cc,
                    ccKnown: cc ? cc.classList.contains('chip-known') : false,
                    ccText: cc ? cc.textContent.trim() : '',
                    aaKnown: aa ? aa.classList.contains('chip-known') : null,
                };
            }""")
            assert res["count"] == 3              # AA + BB + CC (not dropped)
            assert res["ccExists"] is True
            assert res["ccKnown"] is True         # distinct 'known' state
            assert "Tivoo" in res["ccText"]
            assert res["aaKnown"] is False         # a detected device is NOT known
        finally:
            await browser.close()
