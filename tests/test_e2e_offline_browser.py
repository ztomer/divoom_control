"""The e2e browser is hermetic: an off-machine request fails fast, a page loads fast.

index.html links Google Fonts and `page.goto` waits for that stylesheet, so a
networked test browser spent 2.7-6.0 s of every goto on the internet and, under
load, crossed goto's 30 s cap -- 8 to 17 Page.goto timeouts per eight-wide run
at load 100-160, different tests each time (2026-10-19, P1.13). The fix lives at
the one launch seam (tests/support/browser.py -> browser_options.py).

Imports playwright, so scripts/browser_e2e.sh collects it with the other
browser suites.
"""

from __future__ import annotations

import time

import pytest

from tests.support.browser import launch
from tests.support.browser_options import OFFLINE_PROXY, launch_options_for

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

FONTS_CSS = "https://fonts.googleapis.com/css2?family=Inter:wght@400&display=swap"


def test_the_default_launch_is_offline_and_a_networked_one_is_not() -> None:
    """The seam's two directions, without a browser: tests offline, gui_pov networked."""
    assert launch_options_for(network=False)["proxy"] == OFFLINE_PROXY
    assert "proxy" not in launch_options_for(network=True)


@pytest.mark.asyncio
async def test_a_page_linking_web_fonts_loads_without_the_internet() -> None:
    """The real shape: a <link> to Google Fonts must not hold `goto` hostage.

    Offline, the stylesheet fails in milliseconds and `load` fires at once. The
    request must also never return a body -- a stylesheet that arrived means
    the browser reached the internet.
    """
    html = f'<html><head><link rel="stylesheet" href="{FONTS_CSS}"></head><body>x</body></html>'
    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page()
            failed: list[str] = []
            finished: list[str] = []
            page.on("requestfailed", lambda r: failed.append(r.url))
            page.on("requestfinished", lambda r: finished.append(r.url))
            started = time.monotonic()
            await page.goto("data:text/html," + html)
            elapsed = time.monotonic() - started
        finally:
            await browser.close()
    assert FONTS_CSS in failed, f"the font request was not refused offline (finished: {finished})"
    assert FONTS_CSS not in finished
    assert elapsed < 10, f"goto took {elapsed:.1f}s offline"
