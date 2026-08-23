"""Playwright regression test for Hot Channel update button visibility.

Verifies the hot-update-btn stays visible at the bottom of the Hot Channel
card. Requires `playwright` and `--run-integration`.
"""

import pytest
from pathlib import Path
from tests.support.browser import (
    UI_TIMEOUT_MS,
    launch as launch_browser,
    require_browser,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"


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
        seeded = await page.evaluate("""
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
        await page.click('[data-pixel-tab="pixel-gallery"]', timeout=UI_TIMEOUT_MS)
        await page.wait_for_selector("#pixel-gallery.active", timeout=UI_TIMEOUT_MS)

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
        injected = await page.evaluate("""
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
        # Wait for layout to settle and scroll height to exceed client height
        await page.wait_for_function("""
            () => {
                const g = document.getElementById('gallery-container');
                return g && g.scrollHeight > g.clientHeight;
            }
        """, timeout=UI_TIMEOUT_MS)

        gallery_scroll = await page.evaluate("""
            () => {
                const g = document.getElementById('gallery-container');
                return { scrollHeight: g.scrollHeight, clientHeight: g.clientHeight };
            }
        """)

        await browser.close()
