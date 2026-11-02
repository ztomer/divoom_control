"""The test browser's window holds every viewport the suites ask for, so it never
moves under a gesture.

camoufox draws a random fingerprint per launch, window size included. When the
drawn outer window was SHORTER than the page's viewport plus the browser's
chrome (outerHeight 744 or 860 against a 900 px viewport), Firefox later laid
the window out to that height by moving the content's screen origin up
(``mozInnerScreenY`` 89 -> -152 / -36). Playwright had already turned the
test's page coordinates into screen coordinates with the OLD origin, so the
first pointer event landed that many pixels above its target. Under load the
move arrived mid-test:

- CI run 41367764353: the brightness drag pressed ``#nav-menu`` 241 px above
  the 4 px slider; the thumb stayed at 50 ("calibration: the gesture moved the
  thumb (50)").
- CI run 41370988097: the click on the room "+" missed, no form opened, and
  ``Page.fill`` waited 60 s for ``.stage-room-input``.

Measured 2026-11-01 under 8 spinners: 2 of 32 launches drew such a window and
both moved; the other 30 never did. The fix is at the one launch seam
(``tests/support/browser_options.py``): a fixed window, on a screen big
enough to hold it, larger than every viewport any suite asks for.

Imports playwright, so scripts/browser_e2e.sh collects it with the other
browser suites.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from tests.support.browser import eval_js, launch
from tests.support.browser_options import BROWSER_CHROME, HARNESS_WINDOW, launch_options_for

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_VIEWPORT = re.compile(r'"width":\s*(\d+),\s*"height":\s*(\d+)')


def _viewports() -> list[tuple[int, int]]:
    """Every viewport a suite or script asks a page for."""
    found = []
    for path in [*ROOT.glob("tests/**/*.py"), *ROOT.glob("scripts/**/*.py")]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "viewport" in line:
                found += [(int(w), int(h)) for w, h in _VIEWPORT.findall(line)]
    return found


def _window(opts: dict) -> tuple[int, int]:
    raw = "".join(v for k, v in sorted(opts["env"].items()) if k.startswith("CAMOU_CONFIG"))
    cfg = json.loads(raw)
    return (cfg["window.outerWidth"], cfg["window.outerHeight"],
            cfg["screen.availWidth"], cfg["screen.availHeight"])


def test_the_scan_finds_the_viewports_it_guards() -> None:
    """Calibration: a scan that found nothing would pass the test below vacuously."""
    assert (1280, 900) in _viewports() and len(_viewports()) >= 20, _viewports()


def test_every_launch_draws_a_window_that_holds_every_viewport() -> None:
    """Without a browser: 200 draws, every one big enough. Before the fix about
    one draw in 16 was smaller (and the screen must hold the window, or camoufox
    clamps it) than the largest viewport plus chrome."""
    need_w = max(w for w, _ in _viewports()) + BROWSER_CHROME[0]
    need_h = max(h for _, h in _viewports()) + BROWSER_CHROME[1]
    assert HARNESS_WINDOW[0] >= need_w and HARNESS_WINDOW[1] >= need_h, (HARNESS_WINDOW, need_w, need_h)
    small = [w for w in (_window(launch_options_for(network=False)) for _ in range(200))
             if w[0] < need_w or w[1] < need_h or w[2] < w[0] or w[3] < w[1]]
    assert not small, f"windows that cannot hold a {need_w}x{need_h} page: {sorted(set(small))}"


@pytest.mark.asyncio
async def test_the_window_does_not_move_under_an_open_page() -> None:
    """The real shape: the page's screen origin is where it was when it opened."""
    from tests.support.browser import require_browser

    require_browser()
    w, h = max(_viewports(), key=lambda v: v[0] * v[1])
    async with async_playwright() as p:
        for _ in range(4):
            browser = await launch(p)
            try:
                page = await browser.new_page(viewport={"width": w, "height": h})
                await page.goto("about:blank")
                probe = "() => [mozInnerScreenX, mozInnerScreenY, outerWidth, outerHeight]"
                first = await eval_js(page, probe)
                await asyncio.sleep(1.0)
                later = await eval_js(page, probe)
                assert first[:2] == later[:2], f"the window moved under the page: {first} -> {later}"
                assert later[3] >= h and later[2] >= w, f"the window is smaller than the page: {later}"
            finally:
                await browser.close()
