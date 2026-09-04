"""Playwright regression tests for sidebar/appbar layout:

- R32: the bottom-right connectivity indicator pill (`.corner-transports`) was
  removed — the per-device sidebar dots convey state now. (Was #57: the
  transport-dot tooltip opening upward.)
- #58 (R32 revision): Settings moved out of the sidebar into an appbar gear pill;
  the device panel is now the bottom element of the sidebar. The sidebar must NOT
  contain a Settings nav button, and the appbar must carry a #appbar-settings-btn
  with data-tab="settings".
- R33: device switch dots (#device-dots) are now the bottom element (below the
  device panel glass card).

Loads the real index.html via file:// in headless Chromium. Skipped if Playwright
/ a browser isn't available (these run when a browser is installed).
"""
import pytest
from pathlib import Path
from tests.support.browser import eval_js, launch as launch_browser, require_browser

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"


@pytest.mark.asyncio
async def test_settings_moved_to_appbar_gear():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        try:
            page = await browser.new_page()
            await page.goto(f"file://{INDEX_HTML}")
            await page.wait_for_load_state("domcontentloaded")
            result = await eval_js(page, 
                """() => {
                    const sidebarSettings = [...document.querySelectorAll('.sidebar .nav-btn[data-tab]')]
                        .some(b => b.getAttribute('data-tab') === 'settings');
                    const gear = document.querySelector('header .appbar-gear[data-tab="settings"]');
                    const sidebar = document.querySelector('.sidebar');
                    const lastChild = sidebar && sidebar.lastElementChild;
                    return {
                        sidebarSettings,
                        hasGear: !!gear,
                        lastId: lastChild ? lastChild.id : null,
                    };
                }"""
            )
            assert not result["sidebarSettings"], "Settings nav button should be removed from the sidebar (R32)"
            assert result["hasGear"], "appbar must have a Settings gear pill with data-tab='settings'"
            # R33/R52: the device-selector cluster stays pinned to the bottom.
            # The scan indicator is now the lowest element (its space is always
            # reserved so a scan doesn't reflow the preview); the wall button and
            # device dots sit just above it.
            assert result["lastId"] in ("scan-indicator", "device-dots", "wall-button"), \
                "device-selector cluster (dots / wall button / scan indicator) should be the bottom of the sidebar (R33/R52)"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_corner_transport_indicator_removed():
    """R32: the bottom-right connectivity indicator pill (.corner-transports
    with the four #tr-*-dot dots) was removed — the per-device sidebar dots
    convey state now. Assert none of it survives in the rendered DOM."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        try:
            page = await browser.new_page(viewport={"width": 1100, "height": 720})
            await page.goto(f"file://{INDEX_HTML}")
            await page.wait_for_load_state("domcontentloaded")
            counts = await eval_js(page, 
                """() => ({
                    pill: document.querySelectorAll('.corner-transports, .appbar-transports').length,
                    dots: ['tr-ble-dot','tr-lan-dot','tr-cloud-dot','tr-ext-dot']
                        .filter(id => document.getElementById(id)).length,
                })"""
            )
            assert counts["pill"] == 0, "the corner connectivity pill should be gone"
            assert counts["dots"] == 0, "the corner transport dots should be gone"
        finally:
            await browser.close()
