"""Playwright regression tests for the Hot Channel and the Gallery panels.

Verifies the hot-update-btn stays visible at the bottom of the Hot Channel
card, and that the Gallery scrolls INSIDE its own grid rather than scrolling
the whole card. Requires `playwright` and `--run-integration`.
"""

import asyncio
import time
from pathlib import Path

import pytest
from tests.support.browser import (
    POLL_INTERVAL_MS,
    eval_js,
    launch as launch_browser,
    require_browser,
    UI_TIMEOUT_MS,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

#: How long the gallery container must be untouched before the test measures it.
#:
#: The app rewrites that container wholesale: clicking the Gallery sub-tab
#: schedules `window.loadGallery` (`settings_features.js`), and `loadGallery`
#: replaces the container's contents. The window below is measured from the
#: app's LAST write and not from the click, so it means "the app has been
#: silent for this long" -- which is what makes the test independent of how
#: long the app defers its load. 250ms is four times the app's own 50ms
#: deferral; the watch resets the clock on every write, so a longer deferral
#: costs the test time and never correctness.
GALLERY_QUIET_MS = 250


async def _watch_gallery(page) -> None:
    """Record when the app last rewrote the gallery container.

    A MutationObserver on `#gallery-container`, installed before the sub-tab
    click that schedules the app's gallery load. The app's write is a
    wholesale replacement of the container's contents, so the observer is how
    the test learns that the write has happened -- the container's own text
    cannot say it (the app's placeholder is replaced again by the render, and
    a test that waited for a particular string would be waiting for the
    app's copy, not for the app to be done).
    """
    watched = await eval_js(page, """
        () => {
            const g = document.getElementById('gallery-container');
            if (!g) return false;
            window.__galleryWatch = { last: Date.now(), writes: 0 };
            new MutationObserver(() => {
                window.__galleryWatch.writes += 1;
                window.__galleryWatch.last = Date.now();
            }).observe(g, {
                childList: true, subtree: true, characterData: true, attributes: true,
            });
            return true;
        }
    """)
    assert watched, (
        "#gallery-container is not in the page, so the watch cannot be "
        "installed and the test would measure nothing"
    )


async def _wait_for_gallery_quiet(page, *, quiet_ms: int = GALLERY_QUIET_MS) -> dict:
    """Wait until the app has taken the gallery container over and stopped.

    TWO conditions, and the first one is the one that matters: the app must
    have WRITTEN at least once since the watch went up, and the container must
    then have been still for `quiet_ms`.

    "Still for a while" alone is not enough, and the CI run proved it: the
    gallery's own load is scheduled with `setTimeout(window.loadGallery, 50)`,
    and a timer fires when the MAIN THREAD is free -- which on a loaded runner
    was 450ms later. The container had therefore been quiet for the whole of
    that time (it had never been written), the test read "quiet", injected, and
    the app's load landed 20ms later and emptied the container underneath it.

    So the wait is for the app's OWN write -- the one that says "this
    container is mine now" -- and only then for stillness. The write is
    watched, not guessed at: the observer counts them.
    """
    deadline = time.monotonic() + UI_TIMEOUT_MS / 1000
    state = None
    while True:
        state = await eval_js(page, """
            () => {
                const w = window.__galleryWatch;
                if (!w) return null;
                return { idleMs: Date.now() - w.last, writes: w.writes };
            }
        """)
        if state and state["writes"] >= 1 and state["idleMs"] >= quiet_ms:
            return state
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"the gallery never settled: {state} — the app's gallery load "
                f"must write the container once and then stop; a test that "
                f"measures before that measures a container the app is about "
                f"to replace"
            )
        await asyncio.sleep(POLL_INTERVAL_MS / 1000)


@pytest.mark.asyncio
async def test_hot_channel_button_visible_with_many_preview_items():
    """Update button stays at the bottom of the Hot Channel card
    when many preview items are rendered."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page()
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")

        # R39+: Hot Channel is a Pixel Art sub-tab.
        await page.click('.nav-btn[data-tab="pixel-art"]', timeout=UI_TIMEOUT_MS)
        await page.wait_for_selector("#pixel-art.active", timeout=UI_TIMEOUT_MS)
        await page.click('[data-pixel-tab="pixel-hot-channel"]', timeout=UI_TIMEOUT_MS)
        await page.wait_for_selector("#pixel-hot-channel.active", timeout=UI_TIMEOUT_MS)

        # Inject 50 fake preview items into the hot preview list.
        #
        # Same silent-no-op class as the gallery injector below, but this one
        # fails WORSE: the assertions after it only mean anything if the list
        # is actually overflowing. A no-op left an EMPTY card, in which the
        # button is trivially inside its bounds -- so the test passed while
        # measuring nothing. A vacuous pass is worse than a timeout.
        await page.wait_for_selector("#hot-preview-list", timeout=UI_TIMEOUT_MS)
        seeded = await eval_js(page, """
            () => {
                const list = document.getElementById('hot-preview-list');
                if (!list) return -1;
                list.innerHTML = '';
                for (let i = 0; i < 50; i++) {
                    const item = document.createElement('div');
                    item.className = 'hot-preview-item';
                    item.style.height = '120px';  // realistic thumb height
                    item.textContent = 'Preview ' + (i + 1);
                    list.appendChild(item);
                }
                return list.children.length;
            }
        """)
        assert seeded == 50, (
            f"preview injection did not take effect (returned {seeded}) — "
            "#hot-preview-list was missing. The layout assertions below would "
            "have passed vacuously against an empty card."
        )
        await page.wait_for_timeout(200)

        card_box = await page.locator("#pixel-hot-channel .card.glass-card").first.bounding_box()
        button_box = await page.locator("#hot-update-btn").bounding_box()

        assert card_box is not None, "Hot Channel card not found"
        assert button_box is not None, "hot-update-btn not found"

        button_top = button_box["y"]
        button_bottom = button_box["y"] + button_box["height"]
        card_top = card_box["y"]
        card_bottom = card_box["y"] + card_box["height"]

        assert card_top <= button_top, (
            f"Button top ({button_top}) is above card top ({card_top})"
        )
        assert button_bottom <= card_bottom, (
            f"Button bottom ({button_bottom}) is below card bottom ({card_bottom}). "
            f"Button is being pushed out of view."
        )

        slack = 50
        card_bottom_anchor = card_bottom - slack
        assert button_bottom >= card_bottom_anchor, (
            f"Button bottom ({button_bottom}) is not at card bottom "
            f"({card_bottom}). Card bottom anchor (with {slack}px slack): "
            f"{card_bottom_anchor}. Button is not pinned to the bottom."
        )

        await browser.close()


@pytest.mark.asyncio
async def test_gallery_scrolls_internally_not_whole_card():
    """The gallery scrolls internally, not the whole card."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page()
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")

        # R39+: Gallery is a Pixel Art sub-tab.
        await page.click('.nav-btn[data-tab="pixel-art"]', timeout=UI_TIMEOUT_MS)
        await page.wait_for_selector("#pixel-art.active", timeout=UI_TIMEOUT_MS)

        # WATCH THE CONTAINER BEFORE THE APP IS TOLD TO REWRITE IT.
        #
        # P1.16. Clicking the Gallery sub-tab schedules the app's gallery
        # load, and that load replaces the container's contents wholesale.
        # The old test injected its tiles straight after the click, so it was
        # measuring a container the app was about to empty: on CI run
        # 39542787961 the tiles were gone before the measurement and the
        # failure read "gallery never overflowed: scrollHeight 316,
        # clientHeight 316" -- the numbers of an EMPTY container, which name
        # the symptom and not the cause. It reproduced here (the same
        # message) whenever the app's write landed between the injection and
        # the first poll, which is a window of one browser round trip.
        #
        # The watch is installed BEFORE the sub-tab click, so the app's write
        # is seen; the test then waits for the app to go quiet before it
        # injects anything.
        await _watch_gallery(page)
        await page.click('[data-pixel-tab="pixel-gallery"]', timeout=UI_TIMEOUT_MS)
        await page.wait_for_selector("#pixel-gallery.active", timeout=UI_TIMEOUT_MS)
        await _wait_for_gallery_quiet(page)

        # Inject 100 items to ensure overflow.
        #
        # The injector used to end its missing-container branch with a bare
        # `return` -- a silent no-op. With the container not yet in the DOM
        # nothing was injected, and the wait below then blocked on a condition
        # that could never become true, dying at the timeout with an opaque
        # TimeoutError that named nothing. That is what the 2026-08-23 release
        # flake looked like from the outside: a 5s (then 20s) timeout on a
        # layout check that is normally instant. Fail AT the injection instead,
        # where the cause is still visible.
        await page.wait_for_selector("#gallery-container", timeout=UI_TIMEOUT_MS)
        injected = await eval_js(page, """
            () => {
                const grid = document.getElementById('gallery-container');
                if (!grid) return -1;
                grid.innerHTML = '';
                for (let i = 0; i < 100; i++) {
                    const item = document.createElement('div');
                    item.className = 'gallery-item';
                    item.style.height = '140px';  // realistic tile height
                    item.textContent = 'Item ' + (i + 1);
                    grid.appendChild(item);
                }
                return grid.children.length;
            }
        """)
        assert injected == 100, (
            f"gallery injection did not take effect (returned {injected}) — "
            "#gallery-container was missing or unwritable. The scroll wait "
            "below would have timed out for this reason, naming nothing."
        )

        # THE TILES MUST SURVIVE THE MEASUREMENT. The wait above says the app
        # has stopped writing; this says the app did not write again while the
        # measurement was taken. Without it, a late write would empty the
        # container and the numbers below would be an empty container's --
        # which is exactly how this test failed on CI.
        await _wait_for_gallery_quiet(page)
        gallery_scroll = await eval_js(page, """
            () => {
                const g = document.getElementById('gallery-container');
                const main = g ? g.closest('.gallery-main') : null;
                return {
                    children: g ? g.children.length : -1,
                    scrollHeight: g && g.scrollHeight,
                    clientHeight: g && g.clientHeight,
                    mainScrollHeight: main && main.scrollHeight,
                    mainClientHeight: main && main.clientHeight,
                    docScrollHeight: document.documentElement.scrollHeight,
                    winHeight: window.innerHeight,
                };
            }
        """)
        assert gallery_scroll["children"] == 100, (
            f"the app rewrote the gallery container while the test measured it "
            f"({gallery_scroll['children']} children left, expected 100) — the "
            f"measurement below would be an empty container's"
        )
        assert gallery_scroll["scrollHeight"] > gallery_scroll["clientHeight"], (
            f"the gallery does not scroll internally: scrollHeight "
            f"{gallery_scroll['scrollHeight']} <= clientHeight "
            f"{gallery_scroll['clientHeight']} — {gallery_scroll}"
        )
        # ...and the whole card must NOT scroll: the gallery is a grid inside
        # a card, and the card clips what does not fit.
        assert gallery_scroll["mainScrollHeight"] <= gallery_scroll["mainClientHeight"], (
            f"the gallery's card scrolls as a whole: scrollHeight "
            f"{gallery_scroll['mainScrollHeight']} > clientHeight "
            f"{gallery_scroll['mainClientHeight']} — {gallery_scroll}"
        )
        assert gallery_scroll["docScrollHeight"] <= gallery_scroll["winHeight"], (
            f"the page scrolls as a whole: document scrollHeight "
            f"{gallery_scroll['docScrollHeight']} > window height "
            f"{gallery_scroll['winHeight']} — {gallery_scroll}"
        )

        await browser.close()
