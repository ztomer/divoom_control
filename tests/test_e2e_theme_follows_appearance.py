"""E2E -- the web UI follows the light appearance (DV.WEBUILIGHT).

Found 2026-11-14 (DV.BGLAUNCH captures): forcing Divoom.app to the Aqua appearance left the window
exactly as dark as before. The page drew its "dark" default whenever no theme was stored, and the
boot SAVED that default back on every launch (`aesthetic-theme`), so every installed app carried a
"dark" nobody chose and never consulted prefers-color-scheme. The light rules for "system" were also
a second copy (`body.theme-system` inside a media query) that had already drifted: tabs.css drew its
light tints in the dark system theme.

Now the choice defaults to system, the boot writes nothing, the legacy key is dropped, "system" is
resolved in ONE place (theme_boot.js) to the same `theme-light`/`theme-dark` classes a choice
draws, and it follows the appearance live.

TEETH (each watched red): default the choice to "dark" and the default rows go red; honour the
legacy key and the legacy row goes red; drop the change listener and the live row goes red; write
a `theme-system` rule into any stylesheet and the single-rule-set row goes red.

Drives the real web UI with a mocked bridge; skipped without --run-browser.
"""

from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

WEB_UI = Path(__file__).parent.parent / "divoom_gui" / "web_ui"
INDEX_HTML = WEB_UI / "index.html"
_MOCK_API = """
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) =>
    Promise.resolve(String(name).startsWith('get_') ? '{}' : true) })};
"""
LIGHT_BG = "rgb(244, 244, 246)"  # --bg-base of body.theme-light
DARK_BG = "rgb(18, 19, 22)"  # --bg-base of :root


async def _open(p, scheme: str, storage: dict[str, str] | None = None):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme=scheme)
    seed = "".join(f"localStorage.setItem({k!r}, {v!r});" for k, v in (storage or {}).items())
    await add_init_js(page, _MOCK_API + f"\ntry {{ {seed} }} catch (e) {{}}\n")
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.DivoomTheme && !!window.DivoomState")
    return browser, page


async def _drawn(page) -> tuple[str, str]:
    return tuple(
        await eval_js(
            page,
            "() => [document.body.classList.contains('theme-light') ? 'light'"
            " : document.body.classList.contains('theme-dark') ? 'dark' : 'none',"
            " getComputedStyle(document.body).backgroundColor]",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("scheme", "want"), [("light", ("light", LIGHT_BG)), ("dark", ("dark", DARK_BG))])
async def test_with_no_choice_the_page_draws_the_appearance(scheme, want):
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, scheme)
        try:
            assert await _drawn(page) == want
            assert await eval_js(page, "() => localStorage.getItem('divoom-theme')") is None, "boot wrote a choice"
            active = await eval_js(
                page, "() => [...document.querySelectorAll('.theme-mode-btn.active')].map(b => b.dataset.theme)"
            )
            assert active == ["system"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_dark_every_old_boot_saved_is_not_a_choice():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "light", {"aesthetic-theme": "dark"})
        try:
            assert await _drawn(page) == ("light", LIGHT_BG)
            assert await eval_js(page, "() => localStorage.getItem('aesthetic-theme')") is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_system_follows_the_appearance_live():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "light")
        try:
            assert (await _drawn(page))[0] == "light"
            await page.emulate_media(color_scheme="dark")
            await wait_js(page, "() => document.body.classList.contains('theme-dark')")
            assert await _drawn(page) == ("dark", DARK_BG)
            await page.emulate_media(color_scheme="light")
            await wait_js(page, "() => document.body.classList.contains('theme-light')")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_chosen_theme_holds_against_the_appearance_and_is_kept():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "light")
        try:
            await page.click('.nav-btn[data-tab="device-settings"]')
            await eval_js(page, "() => document.querySelector('.theme-mode-btn[data-theme=\"dark\"]').click()")
            assert await _drawn(page) == ("dark", DARK_BG)
            assert await eval_js(page, "() => localStorage.getItem('divoom-theme')") == "dark"
            await page.emulate_media(color_scheme="light")
            assert (await _drawn(page))[0] == "dark"
            sel = await eval_js(
                page,
                "() => [...document.querySelectorAll('.theme-mode-btn')]"
                ".map(b => b.dataset.theme + ':' + b.getAttribute('aria-selected'))",
            )
            assert sel == ["dark:true", "light:false", "system:false"]
        finally:
            await browser.close()


def test_the_light_rules_are_one_set():
    """ "System" is resolved in theme_boot.js, so no stylesheet keeps a copy of the light rules for it."""
    offenders = [
        f"{css.name}: {needle}"
        for css in sorted(WEB_UI.glob("*.css"))
        for needle in ("theme-system", "prefers-color-scheme")
        if needle in css.read_text()
    ]
    assert not offenders, offenders


def test_a_colour_well_draws_its_own_edge():
    """The clock's white well vanished on the light theme's white card: every well carries the
    theme's input border, in both engines' pseudo-elements."""
    css = (WEB_UI / "style.css").read_text()
    for pseudo in ("::-webkit-color-swatch {", "::-moz-color-swatch {"):
        rule = css[css.index('input[type="color"]' + pseudo) :]
        assert "border: 1px solid var(--input-border)" in rule[: rule.index("}")], pseudo
