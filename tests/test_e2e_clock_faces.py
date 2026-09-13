"""E2E — cloud clock-face browser (Channel/GetDialType + GetDialList), wired
into the Clock channel panel. Drives the REAL web_ui in headless Chromium
with a mock ``window.pywebview.api``, same harness as test_e2e_ux_feedback.py.

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
    get_dial_types: () => ["Social", "Normal"],
    get_dial_list: (dialType) => {
        if (dialType === "Social") return [
            {ClockId: 26, Name: "Facebook Video"},
            {ClockId: 38, Name: "YouTube Account"},
        ];
        if (dialType === "Normal") return [{ClockId: 10, Name: "Classic Digital Clock"}];
        return [];
    },
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
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    return browser, page


@pytest.mark.asyncio
async def test_clock_panel_loads_dial_types_and_first_list_on_open():
    """The Clock panel is active by default -- the cloud browser must load
    without any tab click (this was a real gap: showChannelPanel() only
    fires on click, so an init-time-only trigger was required)."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-clock-type-select option').length > 0")
            options = await page.eval_on_selector_all(
                "#cloud-clock-type-select option", "els => els.map(e => e.value)")
            assert options == ["Social", "Normal"]
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-clock-list .cloud-clock-row').length > 0")
            names = await page.eval_on_selector_all(
                "#cloud-clock-list .cloud-clock-name", "els => els.map(e => e.textContent)")
            assert names == ["Facebook Video", "YouTube Account"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_switching_dial_type_reloads_the_list():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-clock-type-select option').length > 0")
            await page.select_option("#cloud-clock-type-select", "Normal")
            await wait_js(page, 
                "() => document.querySelector('#cloud-clock-list .cloud-clock-name')?.textContent === 'Classic Digital Clock'")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_apply_without_a_device_shows_connect_prompt_and_does_not_call_set_clock():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, """() => {
                window.__setClockCalls = [];
                window.__api.set_clock = (style, color) => { window.__setClockCalls.push([style, color]); return true; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-clock-list .cloud-clock-row').length > 0")
            await page.click("#cloud-clock-list .cloud-clock-apply-btn")
            await wait_js(page, 
                "() => document.getElementById('toast')?.classList.contains('show')")
            toast = await eval_js(page, "() => document.getElementById('toast').textContent")
            assert "Connect a device first" in toast
            calls = await eval_js(page, "() => window.__setClockCalls")
            assert calls == []
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_apply_with_a_device_calls_set_clock_with_the_real_clock_id():
    """The whole point of this feature: applying a browsed cloud clock face
    reuses the existing set_clock() -> display.show_clock() path -- no new
    device-apply plumbing, just the real ClockId from GetDialList."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, """() => {
                window.DivoomState.appConnected = true;
                window.__setClockCalls = [];
                window.__api.set_clock = (style, color) => { window.__setClockCalls.push([style, color]); return true; };
            }""")
            await wait_js(page, 
                "() => document.querySelectorAll('#cloud-clock-list .cloud-clock-row').length > 0")
            await page.click("#cloud-clock-list .cloud-clock-apply-btn")
            await wait_js(page, "() => (window.__setClockCalls || []).length > 0")
            calls = await eval_js(page, "() => window.__setClockCalls")
            assert calls == [[26, "#ffffff"]]  # first row: Facebook Video, ClockId 26
            await wait_js(page, 
                "() => document.getElementById('toast')?.textContent.includes('Clock face applied')")
        finally:
            await browser.close()


# ── R70 P2.4: a failed browse must SAY WHY, on screen ────────────────────────

_MOCK_API_UNREACHABLE = """
window.__api = {
    get_dial_types: () => ({ok: false, items: [],
        error: "Could not load clock face categories: the background service is not running",
        cause: "unreachable"}),
    get_dial_list: () => ({ok: false, items: [],
        error: "Could not load clock faces: the background service is not running",
        cause: "unreachable"}),
    get_store_clock_faces: () => ({ok: false, items: [],
        error: "Could not load clock face store: the background service is not running",
        cause: "unreachable"}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open_with(p, mock):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, mock)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    return browser, page


@pytest.mark.asyncio
async def test_an_unreachable_daemon_names_the_reason_instead_of_showing_nothing():
    """The user-visible half of R70 P2.4.

    Before this, a browse that could not run rendered the same "nothing found"
    as an empty catalog. The daemon knew the reason the whole time; the GUI
    discarded it at an `except`. This asserts the reason reaches the SCREEN,
    which is the only place it matters — the Python-level test can pass while
    the panel still renders a blank list.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open_with(p, _MOCK_API_UNREACHABLE)
        try:
            await wait_js(page, """() => {
                const el = document.querySelector('.cloud-problem-reason');
                return !!el && el.textContent.includes('background service');
            }""")
            # The hint must ADD something, not echo the reason. Seen on screen
            # during the P6.2 pass, "Could not load ...: the background service
            # is not running" followed by "The background service is not
            # running." read as a stutter — so the hint is now what to DO, and
            # `cloud_result.js` drops any hint the reason already contains.
            hint = await eval_js(page, """() => {
                const el = document.querySelector('.cloud-problem-hint');
                return el ? el.textContent : '';
            }""")
            reason = await eval_js(page, """() => {
                const el = document.querySelector('.cloud-problem-reason');
                return el ? el.textContent : '';
            }""")
            assert hint, "an unreachable service should say what to do"
            assert "Reopen" in hint, hint
            assert hint.rstrip(".").lower() not in reason.lower(), (
                f"the hint only restates the reason: {hint!r} / {reason!r}")
        finally:
            await browser.close()


# ── 2026-09-13: the store's faces, with pictures, at the panel's resolution ──

_FACE_PNG = (Path(__file__).parent / "fixtures" / "clock_face_128.txt")


async def test_store_faces_show_the_picture_as_drawn_and_at_the_panels_resolution():
    """The user asked to see how a cloud face will look on the target panel.
    The store card shows the daemon's decoded picture (as drawn) beside the
    same picture rasterized to the SELECTED panel's diode count -- one
    source, two zoom levels -- and Apply on it sends that face's ClockId."""
    require_browser()
    from playwright.async_api import async_playwright

    face_url = _FACE_PNG.read_text().strip()
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => {" + f"const faceUrl = {face_url!r};" + """
                window.__previews = [];
                window.__api.get_store_clock_faces = () => [
                    {clock_id: 998, name: "Digital Tech", image_file_id: "group1/x", clock_type: 0, category: "Normal"},
                    {clock_id: 999, name: "No Picture", image_file_id: "", clock_type: 0, category: "Normal"}];
                window.__api.get_animated_preview = (fid) => { window.__previews.push(fid); return faceUrl; };
                window.DivoomState.discoveredDevices = [{ address: 'E9:DITOO', name: 'Ditoo-light-2' }];
                window.DivoomState.appConnected = true;
                window.__setClockCalls = [];
                window.__api.set_clock = (style, color) => { window.__setClockCalls.push([style, color]); return true; };
                window.DivoomState.cloudClockStoreLoaded = false;
                window.loadCloudClockTypes();
            }""")
            await wait_js(page, "() => document.querySelectorAll('#cloud-clock-store .clock-face-card').length === 2")
            # The picture arrives from the daemon by file id; the device view is rasterized from it.
            await wait_js(page, """() => {
                const c = document.querySelector('#cloud-clock-store .clock-face-card[data-clock-id="998"]');
                return c && c.querySelector('.clock-face-original').src.startsWith('data:image/png')
                         && c.querySelector('.clock-face-device').src.startsWith('data:image/png');
            }""")
            info = await eval_js(page, """() => {
                const c = document.querySelector('#cloud-clock-store .clock-face-card[data-clock-id="998"]');
                const dev = c.querySelector('.clock-face-device');
                const img = new Image(); img.src = dev.src;
                return { previews: window.__previews, caption: c.children[1].querySelector('.clock-face-caption')?.textContent,
                         devNatural: [img.naturalWidth, img.naturalHeight], origSrcLen: c.querySelector('.clock-face-original').src.length };
            }""")
            assert info["previews"] == ["group1/x"], info
            assert "16x16" in (info["caption"] or ""), info
            # The device view is a real 16x16 raster (the rasterizer decoded synchronously from a data URL).
            await wait_js(page, """() => { const d = document.querySelector('#cloud-clock-store .clock-face-card[data-clock-id="998"] .clock-face-device'); return d.naturalWidth === 16 && d.naturalHeight === 16; }""")
            # A face without a picture still lists, honestly, with no image.
            no_pic = await eval_js(page, """() => document.querySelector('#cloud-clock-store .clock-face-card[data-clock-id="999"] .clock-face-original').getAttribute('src')""")
            assert not no_pic
            await page.click('#cloud-clock-store .clock-face-card[data-clock-id="998"] .cloud-clock-apply-btn')
            await wait_js(page, "() => (window.__setClockCalls || []).length > 0")
            assert await eval_js(page, "() => window.__setClockCalls") == [[998, "#ffffff"]]
        finally:
            await browser.close()
