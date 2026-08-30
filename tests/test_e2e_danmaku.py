"""E2E — the Danmaku overlay button in the Text channel panel (P2.4).

Drives the REAL web_ui with a mock ``window.pywebview.api``, same harness as
test_e2e_clock_faces.py.

The button REUSES the panel's text and colour inputs rather than growing a
second set — it is a different delivery mechanism (the device's own overlay
layer) for the same message, not a different message. These tests pin that
reuse, the guards around it, and the fact that the "not verified on hardware"
caveat is actually on screen.
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
window.__calls = [];
window.__result = true;
window.__api = {
    send_danmaku_text: (text, color) => {
        window.__calls.push(["danmaku", text, color]);
        return window.__result;
    },
    push_text: (...a) => { window.__calls.push(["push_text", ...a]); return true; },
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open(p, *, with_device=True):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.requireDevice")
    if with_device:
        # requireDevice() gates every device action; stub it rather than
        # simulating a full connect, which is another suite's subject.
        await eval_js(page, "() => { window.requireDevice = () => true; }")
    else:
        await eval_js(page, "() => { window.requireDevice = () => false; }")
    # The Text panel is not the default (Clock is). The channel tabs are
    # `.tab-btn[data-channel=...]`, and clicking one is what fires
    # channels_core.js's showChannelPanel.
    await page.click('.tab-btn[data-channel="text"]')
    await page.wait_for_selector("#send-danmaku-btn", state="visible")
    return browser, page


@pytest.mark.asyncio
async def test_the_overlay_button_reuses_the_panels_text_and_colour():
    """Not a second set of inputs — the same message, a different delivery."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.fill("#text-content-input", "hello wall")
            await eval_js(
                page,
                "() => { document.getElementById('text-color-input')"
                ".value = '#ff0000'; }")
            await page.click("#send-danmaku-btn")
            await wait_js(page, "() => window.__calls.length > 0")

            call = await eval_js(page, "() => window.__calls[0]")
            assert call == ["danmaku", "hello wall", "#ff0000"], call
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_empty_text_does_not_call_the_backend():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.fill("#text-content-input", "   ")
            await page.click("#send-danmaku-btn")
            await page.wait_for_timeout(300)
            assert await eval_js(page, "() => window.__calls.length") == 0
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_no_device_does_not_call_the_backend():
    """requireDevice() gates it, same as the push button beside it."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, with_device=False)
        try:
            await page.fill("#text-content-input", "hello")
            await page.click("#send-danmaku-btn")
            await page.wait_for_timeout(300)
            assert await eval_js(page, "() => window.__calls.length") == 0
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_overlay_button_does_not_also_push_text():
    """Two buttons, two mechanisms. Firing both would push a bitmap AND an
    overlay for one click, which is not what either label promises."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await page.fill("#text-content-input", "hello")
            await page.click("#send-danmaku-btn")
            await wait_js(page, "() => window.__calls.length > 0")
            await page.wait_for_timeout(200)

            names = await eval_js(page, "() => window.__calls.map(c => c[0])")
            assert names == ["danmaku"], names
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_failed_send_is_reported_as_a_failure():
    """"Sent" and "worked" must not be the same signal (R67/C4)."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => { window.__result = false; }")
            await eval_js(page, "() => { window.__toasts = []; "
                                "const o = window.showToast; "
                                "window.showToast = (m, k) => { "
                                "window.__toasts.push([m, k]); return o && o(m, k); }; }")
            await page.fill("#text-content-input", "hello")
            await page.click("#send-danmaku-btn")
            await wait_js(page, "() => (window.__toasts || []).length > 0")

            toast = await eval_js(page, "() => window.__toasts[0]")
            assert toast[1] == "error", toast
            assert "Failed" in toast[0], toast
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_unverified_caveat_is_visible_next_to_the_button():
    """Honest placeholders: this command ACKs cleanly and nobody has watched it
    draw on a matrix. The caveat must be ON SCREEN, not just in a comment."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            assert await page.is_visible("#danmaku-hint") is True
            text = await eval_js(
                page, "() => document.getElementById('danmaku-hint').textContent")
            assert "Not yet verified on real hardware" in text
        finally:
            await browser.close()
