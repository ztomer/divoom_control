"""E2E — the weather card shows the frame the panel shows (P5.4).

Drives the REAL web_ui with a mock ``window.pywebview.api`` (the harness of
test_e2e_weather_city.py). The card used to draw its own SVG icon and a
temperature from ``get_weather`` -- a second renderer for a widget the panel
draws with ``render_widget {kind: "weather"}``. What these pin:

* the card's picture IS the PNG ``get_weather_preview`` returned, and the card
  holds no vector drawing of its own to fall back on;
* the reading is text beside the frame, from the same reply;
* loading and failure are placeholders that SAY so, are visibly distinct from
  each other and from a frame, and leave no stale reading dressed as current.

Skipped if a browser isn't installed.
"""
import base64
import io
from pathlib import Path

import pytest

from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"


def _png_data_url() -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.frombytes("RGB", (2, 2), b"\xff\x00\x00\x00\xff\x00\x00\x00\xff\xff\xff\xff").save(
        buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


FRAME = _png_data_url()

_MOCK_API = """
window.__weather = {mode: "ok", calls: 0};
window.__api = {
    get_weather_city: () => ({location: "", name: ""}),
    get_weather_preview: (size) => {
        window.__weather.calls += 1;
        const w = window.__weather;
        if (w.mode === "hang") return new Promise(() => {});
        if (w.mode === "fail")
            return JSON.stringify({ok: false, error: "weather: wttr.in returned 503"});
        return JSON.stringify({ok: true, size: 16, preview: "%FRAME%",
                               temperature_c: -3, weather: 8, location: "Oslo"});
    },
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
""".replace("%FRAME%", FRAME)

_CARD_STATE = """() => {
    const wrap = document.getElementById('weather-device-preview');
    const img = document.getElementById('weather-frame');
    const note = document.getElementById('weather-frame-note');
    const shown = el => !!el && getComputedStyle(el).display !== 'none'
                         && el.getBoundingClientRect().width > 0;
    return {
        state: wrap && wrap.dataset.state,
        imgShown: shown(img),
        imgSrc: img ? (img.getAttribute('src') || '') : null,
        noteShown: shown(note),
        note: note ? note.textContent.trim() : null,
        temp: (document.getElementById('weather-reading-temp') || {}).textContent,
        location: (document.getElementById('weather-preview-location') || {}).textContent,
        svgs: wrap ? wrap.querySelectorAll('svg').length : -1,
        border: wrap ? getComputedStyle(wrap).borderStyle : null,
    };
}"""


async def _open(p, mode: str):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API.replace('mode: "ok"', f'mode: "{mode}"'))
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    await page.click('.nav-btn[data-tab="data-sources"]')
    await page.wait_for_selector("#widget-card-weather", state="visible")
    return browser, page


@pytest.mark.asyncio
async def test_the_card_shows_the_frame_and_the_reading_beside_it():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "ok")
        try:
            await wait_js(page, "() => document.getElementById('weather-device-preview')"
                                "?.dataset.state === 'ok'")
            s = await eval_js(page, _CARD_STATE)
            assert s["imgShown"] and s["imgSrc"] == FRAME, s
            assert not s["noteShown"], s
            assert s["temp"].strip() == "-3°C", s
            assert s["location"] == "Oslo", s
            assert s["svgs"] == 0, "the card still draws a weather picture of its own"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_failed_frame_says_why_and_shows_no_reading():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "fail")
        try:
            await wait_js(page, "() => document.getElementById('weather-device-preview')"
                                "?.dataset.state === 'failed'")
            s = await eval_js(page, _CARD_STATE)
            assert not s["imgShown"] and s["imgSrc"] == "", s
            assert s["noteShown"] and "503" in s["note"], s
            assert "unavailable" in s["note"].lower(), s
            assert s["temp"].strip() in ("–", "--"), "a failed reading must not show a number"
            assert s["svgs"] == 0, s
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_loading_is_its_own_placeholder_distinct_from_failure():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "hang")
        try:
            await wait_js(page, "() => window.__weather.calls > 0")
            loading = await eval_js(page, _CARD_STATE)
            assert loading["state"] == "loading", loading
            assert not loading["imgShown"], loading
            assert loading["noteShown"] and "loading" in loading["note"].lower(), loading
            assert loading["temp"].strip() in ("–", "--"), loading

            # Same card, now failed: the text differs AND the box differs, so the
            # two states are told apart without relying on colour.
            await eval_js(page, "() => { window.__weather.mode = 'fail'; "
                                "window.refreshWeatherPreview(); }")
            await wait_js(page, "() => document.getElementById('weather-device-preview')"
                                "?.dataset.state === 'failed'")
            failed = await eval_js(page, _CARD_STATE)
            assert failed["note"] != loading["note"], (loading, failed)
            assert failed["border"] != loading["border"], (loading, failed)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_failure_after_a_frame_takes_the_stale_frame_down():
    """A frame that stays up after the reading failed is a stale picture dressed
    as the panel's current one."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "ok")
        try:
            await wait_js(page, "() => document.getElementById('weather-device-preview')"
                                "?.dataset.state === 'ok'")
            await eval_js(page, "() => { window.__weather.mode = 'fail'; "
                                "window.refreshWeatherPreview(); }")
            await wait_js(page, "() => document.getElementById('weather-device-preview')"
                                "?.dataset.state === 'failed'")
            s = await eval_js(page, _CARD_STATE)
            assert not s["imgShown"] and s["imgSrc"] == "", s
            assert s["temp"].strip() in ("–", "--"), s
        finally:
            await browser.close()
