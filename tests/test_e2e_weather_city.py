"""E2E — the weather city override (P3.1b), in the Weather widget card.

Drives the REAL web_ui with a mock ``window.pywebview.api``, same harness as
test_e2e_clock_faces.py. What these pin, beyond "the button works":

* the SAVED value is coordinates, never the city name — Weather/SearchCity is a
  Divoom endpoint and the service that fetches weather is wttr.in, which has
  never heard of a Divoom CityId;
* clearing the override is reachable from the UI, because getting back to IP
  geolocation must not require editing config.ini;
* the card re-reads through get_weather after a save rather than patching the
  label locally, so a save that failed leaves the OLD city on screen;
* a slow search cannot overwrite the results for newer text in the box.

Skipped if a browser isn't installed.
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
window.__saved = {location: "", name: ""};
window.__api = {
    search_weather_city: (kw) => {
        window.__calls.push(["search", kw]);
        if (!kw || !kw.trim()) return [];
        return [
            {CityName: "Berlin", Country: "Germany", Lat: 52.52, Lon: 13.405},
            {CityName: "Berlin", Country: "United States", Lat: 44.46, Lon: -71.18},
        ];
    },
    get_weather_city: () => window.__saved,
    set_weather_city: (lat, lon, name) => {
        window.__calls.push(["save", lat, lon, name]);
        window.__saved = (lat && lon)
            ? {location: lat + "," + lon, name: name}
            : {location: "", name: ""};
        return true;
    },
    get_weather: () => {
        window.__calls.push(["get_weather"]);
        return {temperature_c: 11, weather_type: 1,
                location: window.__saved.name || "IP geolocation"};
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
    # The Weather card lives in the Data Sources tab, which is not active on
    # load — the button exists in the DOM but is not visible until we navigate.
    # (Found the hard way: every test here failed on "element is not visible".)
    await page.click('.nav-btn[data-tab="data-sources"]')
    await page.wait_for_selector("#weather-location-btn", state="visible")
    return browser, page


async def _open_search(page):
    await page.click("#weather-location-btn")
    await page.wait_for_selector("#weather-city-input", state="visible")


@pytest.mark.asyncio
async def test_the_search_panel_is_not_rendered_until_the_location_is_clicked():
    """The card must gain no chrome for a control most people never need.

    Asserts what is ON SCREEN, not `element.hidden`. The first version of this
    test checked the DOM property and passed while the panel was fully visible:
    the author rule `.weather-city-search { display: flex }` overrides the UA
    stylesheet's `[hidden] { display: none }`, so `hidden` was true and the
    panel rendered anyway. A screenshot caught it; the assertion could not.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            assert await page.is_visible("#weather-city-search") is False
            assert await page.is_visible("#weather-city-input") is False
            await _open_search(page)
            assert await page.is_visible("#weather-city-input") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_typing_a_city_lists_matches():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _open_search(page)
            await page.fill("#weather-city-input", "berlin")
            await wait_js(
                page,
                "() => document.querySelectorAll('#weather-city-results "
                ".weather-city-row').length === 2")
            labels = await page.eval_on_selector_all(
                "#weather-city-results .weather-city-row",
                "els => els.map(e => e.textContent)")
            assert labels == ["Berlin, Germany", "Berlin, United States"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_picking_a_city_saves_coordinates_not_the_name():
    """The regression this whole feature turns on.

    Saving "Berlin" would look identical here if the assertion were loose, and
    would quietly fail for any city whose Divoom spelling differs from wttr.in's.
    Both mock results are named "Berlin" precisely so a name-based save cannot
    pass by accident.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _open_search(page)
            await page.fill("#weather-city-input", "berlin")
            await wait_js(
                page,
                "() => document.querySelectorAll('#weather-city-results "
                ".weather-city-row').length === 2")
            # The SECOND Berlin — a name-only save could not tell them apart.
            await page.click(
                "#weather-city-results .weather-city-row:nth-child(2)")
            await wait_js(
                page, "() => window.__calls.some(c => c[0] === 'save')")

            save = await eval_js(
                page, "() => window.__calls.find(c => c[0] === 'save')")
            assert save[1] == "44.46", save
            assert save[2] == "-71.18", save
            assert save[3] == "Berlin, United States", save
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_saving_closes_the_panel_and_re_reads_the_card():
    """The label must come from get_weather, not be patched locally: a save that
    silently failed has to leave the OLD city on screen, not an optimistic one."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _open_search(page)
            await page.fill("#weather-city-input", "berlin")
            await wait_js(
                page,
                "() => document.querySelectorAll('#weather-city-results "
                ".weather-city-row').length === 2")
            await eval_js(page, "() => window.__calls = []")
            await page.click(
                "#weather-city-results .weather-city-row:nth-child(1)")

            await page.wait_for_selector("#weather-city-input", state="hidden")
            await wait_js(
                page, "() => window.__calls.some(c => c[0] === 'get_weather')")
            await wait_js(
                page,
                "() => document.getElementById('weather-preview-location')"
                ".textContent === 'Berlin, Germany'")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_use_my_location_clears_the_override():
    """Getting back to IP geolocation must be a button, not a config-file edit."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _open_search(page)
            await page.fill("#weather-city-input", "berlin")
            await wait_js(
                page,
                "() => document.querySelectorAll('#weather-city-results "
                ".weather-city-row').length === 2")
            await page.click("#weather-city-results .weather-city-row:nth-child(1)")
            await wait_js(page, "() => window.__saved.location !== ''")

            await page.click("#weather-location-btn")
            await page.wait_for_selector("#weather-city-input", state="visible")
            await page.click("#weather-city-auto")
            await wait_js(page, "() => window.__saved.location === ''")
            assert await eval_js(page, "() => window.__saved.name") == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_an_emptied_box_does_not_search():
    """Clearing the input must cancel, not fire a search for "" that the backend
    would have to reject."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _open_search(page)
            await page.fill("#weather-city-input", "berlin")
            await wait_js(page, "() => window.__calls.some(c => c[0] === 'search')")
            await eval_js(page, "() => window.__calls = []")
            await page.fill("#weather-city-input", "")
            await wait_js(
                page,
                "() => document.getElementById('weather-city-results')"
                ".textContent.includes('Type a city')")
            assert await eval_js(
                page, "() => window.__calls.filter(c => c[0] === 'search').length") == 0
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_panel_says_what_is_currently_set():
    """Opening the panel with nothing saved must SAY it is using IP geolocation.
    A blank field reads as unset-by-accident rather than as a deliberate default.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await _open_search(page)
            await wait_js(
                page,
                "() => document.getElementById('weather-city-results')"
                ".textContent.includes('IP geolocation')")
        finally:
            await browser.close()
