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
    install_toast_recorder,
    launch as launch_browser,
    require_browser,
    toast_condition,
    wait_js,
    wait_toast,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

_MOCK_API = """
window.__calls = [];
window.__result = { ok: true, error: '', cause: '' };
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
    # Before goto: the recorder has to predate the app's own
    # assignment of window.showToast, or it misses toasts.
    await install_toast_recorder(page)
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
            await page.fill("#text-content-input", "hello")
            await page.click("#send-danmaku-btn")
            # Keyed on THIS toast's own message + kind, not on "a toast exists":
            # the app raises its own unasked (see the last test in this file).
            toast = await wait_toast(page, "Failed to send overlay", kind="error")

            assert "error" in toast["rendered"]["className"].split(), toast
            assert "Failed" in toast["rendered"]["text"], toast
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


@pytest.mark.asyncio
async def test_a_missing_capability_says_so_on_the_screen():
    """R71 P3.1 — the reason has to reach the USER, not just the return value.

    Unit tests pin that `send_danmaku_text` returns cause='no_lan_capability'.
    That is not the same claim as "a person sees why". R70 learned this on the
    cloud side: the daemon had carried the reason the whole time and the GUI
    discarded it at an `except`, and the fix was only real once an e2e asserted
    the text on screen.

    A Bluetooth-only device must not read as a broken feature.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => { window.__result = { ok: false, "
                                "error: 'Could not send the overlay: this device is "
                                "connected over Bluetooth, which has no LAN API', "
                                "cause: 'no_lan_capability' }; }")
            await page.fill("#text-content-input", "hello")
            await page.click("#send-danmaku-btn")
            # On the toast THIS click raises, keyed on the reason rather than on
            # a count: the app raises toasts nobody asked for, so "a toast
            # exists" is not a condition this test's claim can rest on.
            toast = await wait_toast(page, "Bluetooth", kind="error")

            # What the screen held when this toast fired.
            rendered = toast["rendered"]
            message = rendered["text"]
            # The REASON, in the user's words, not a generic failure.
            assert "Bluetooth" in message, message
            assert "no LAN API" in message, message
            # ...and what to do about it, from the shared HINTS table.
            assert "WiFi-capable" in message, message
            # ...raised as an ERROR, not dressed as a success.
            assert "error" in rendered["className"].split(), toast
            # ...and carrying the TRANSPORT marker, which is the half that stops
            # a Bluetooth-only device reading as a broken feature: the reason is
            # "this device has no LAN API", so the toast has to say LAN.
            assert rendered["transport"] == "LAN", toast
            # The old generic text must be gone: it is what made a missing
            # capability indistinguishable from a bug.
            assert message != "Failed to send overlay", message
        finally:
            await browser.close()


#: The old wait, verbatim, kept as the thing this file must not do again.
_COUNT_WAIT = "() => (window.__toasts || []).length > 0"

#: The old instrumentation, verbatim too. Note what it drops: ``showToast`` takes
#: three arguments and this forwards two, so the transport marker never reaches
#: the screen for the rest of the test — the LAN that says "this is a LAN-only
#: command", which is the whole claim of the test below.
_SPY_TWO_ARGS = """
window.__toasts = [];
const o = window.showToast;
window.showToast = (m, k) => {
    window.__toasts.push([m, k]);
    return o && o(m, k);
};
"""

#: Makes the app raise a toast of its own, on demand, through its own code path:
#: a BLE scan whose backend dies is exactly what ``app_init.js`` triggers on its
#: own at startup, and it lands wherever this is called instead of on a timer.
_RAISE_APP_TOAST = """
() => {
    window.__api.scan_devices = () => Promise.reject(new Error("backend gone"));
    window.runBleScan();
}
"""


@pytest.mark.asyncio
async def test_a_toast_this_test_did_not_create_cannot_satisfy_its_wait():
    """The order-dependent failure, made deterministic.

    The page raises toasts nobody asked for — ``app_init.js`` fires "Startup:
    Auto-scanning screens..." after load and the scan behind it answers with its
    own failure — on timers no test controls, in every e2e page. The wait these
    two tests used counted ``showToast`` calls, so any of those satisfied it and
    the test asserted on a toast it had never made: green in isolation, red in a
    full browser run, where the click's own toast loses the race to that noise.

    So force the race instead of hoping for it. This click's own toast is slow
    (a slow backend promise is what a loaded page looks like from in here) and
    the app raises one of its own toasts in between. The count goes true on the
    app's toast; the condition this file waits on does not move until the reason
    this click produced is on screen.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, "() => { window.__result = { ok: false, "
                                "error: 'Could not send the overlay: this device is "
                                "connected over Bluetooth, which has no LAN API', "
                                "cause: 'no_lan_capability' }; }")
            await eval_js(page, _SPY_TWO_ARGS)
            await eval_js(page, "() => { window.__api.send_danmaku_text = (text, color) =>"
                                " new Promise(r => setTimeout("
                                " () => r(window.__result), 3000)); }")
            await page.fill("#text-content-input", "hello")
            await page.click("#send-danmaku-btn")
            # The app's own toast, raised while this click's toast is still in
            # flight. Same code path, same message as its startup auto-scan.
            await eval_js(page, _RAISE_APP_TOAST)

            # The old wait: satisfied — and not by anything this test did.
            await wait_js(page, _COUNT_WAIT)
            recorded = await eval_js(page, "() => window.__toasts.map(t => String(t[0]))")
            assert any("Scan failed" in m for m in recorded), recorded
            assert not any("Bluetooth" in m for m in recorded), recorded
            # The condition this file now waits on, at that same moment: false.
            assert await eval_js(page, toast_condition("Bluetooth", kind="error")) is None

            # The new wait: still patient, and it lands on the right toast.
            toast = await wait_toast(page, "Bluetooth", kind="error")
            assert "no LAN API" in toast["rendered"]["text"], toast
            # ...and under the OLD instrumentation the transport marker never
            # reached the screen at all, so that shape could not have checked it
            # even if it had tried: the reason says "no LAN API" while the toast
            # beside it says nothing about which transport failed.
            assert toast["rendered"]["transport"] == "", toast
        finally:
            await browser.close()
