"""Channel panels must never ALL be hidden, and the Custom Art panel must
never be hidden by channel navigation.

Defect #5 (2026-09-12): "channels -> clock is empty (not always); custom art
- same". Root cause was one class of bug with two instances:

* ``showChannelPanel(kind)`` toggled ``active`` on every ``.channel-panel`` in
  the document by ``id === panel-<kind>``. The activity vocabulary it is fed
  (``image``, ``sysmon``, ``custom``, ``hot``, ``playlist`` ...) is far wider
  than the seven panels, so an unmatched kind hid EVERY panel and the Clock
  tab sat highlighted over an empty card.
* ``#panel-design`` (Custom Art, moved to the Pixel Art tab in R42) still
  carried the ``channel-panel`` class, so the same toggle hid it whenever any
  other kind arrived -- and nothing calls it with ``design`` any more.

Class invariant pinned here: exactly one Channels-tab panel is visible at all
times, and it is the one whose tab button is highlighted; Custom Art is
untouched by channel activity.
"""
from pathlib import Path

import pytest

from tests.support.browser import eval_js, launch as launch_browser, wait_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"

# Every kind the daemon, the menubar, the widgets and the GUI itself can put
# on the activity bus. Only the CHANNEL_PANELS subset has a panel.
ACTIVITY_KINDS = [
    "clock", "vj", "visualizer", "ambient", "scoreboard", "text", "sessions",
    "design", "custom", "hot", "eq", "lighting", "cloud", "image", "sysmon",
    "music", "stocks", "weather", "playlist", "photo_album", "aid_sleep",
]
CHANNEL_PANELS = {"clock", "vj", "visualizer", "ambient", "scoreboard", "text", "sessions"}

PANEL_STATE_JS = """() => {
    const vis = (el) => !!el && getComputedStyle(el).display !== 'none';
    const panels = {};
    document.querySelectorAll('#control-panel .channel-panel, .channel-panels .channel-panel')
        .forEach(p => { panels[p.id] = vis(p); });
    const activeBtn = document.querySelector('.tab-btn.active[data-channel]');
    return {
        panels,
        visibleChannelPanels: Object.keys(panels).filter(k => panels[k]),
        activeTab: activeBtn ? activeBtn.getAttribute('data-channel') : null,
        designVisible: vis(document.getElementById('panel-design')),
    };
}"""


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 850})
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.Divoom?.onActivity && !!window.SpatialStage")
    return browser, page


def _assert_one_visible_matching_tab(state, where):
    vis = state["visibleChannelPanels"]
    assert len(vis) == 1, f"{where}: expected exactly one visible channel panel, got {vis}"
    assert vis[0] == f"panel-{state['activeTab']}", (
        f"{where}: visible panel {vis[0]} does not match highlighted tab {state['activeTab']}"
    )


@pytest.mark.asyncio
async def test_every_activity_kind_leaves_one_matching_panel_visible():
    """Feed every kind on the bus through onActivity for the active device."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        mac = "44:55:66:77:88:99"
        await eval_js(page, """(mac) => {
            window.DivoomState.discoveredDevices = [{ address: mac, name: "Pixoo-Test", room: "Desk" }];
            window.SpatialStage.refresh();
        }""", mac)

        initial = await eval_js(page, PANEL_STATE_JS)
        _assert_one_visible_matching_tab(initial, "initial load")
        assert initial["designVisible"], "Custom Art panel hidden on initial load"

        for kind in ACTIVITY_KINDS:
            state = await eval_js(page, """([mac, kind]) => {
                window.Divoom.onActivity({ type: 'activity', mac, kind });
                return (%s)();
            }""" % PANEL_STATE_JS, [mac, kind])
            _assert_one_visible_matching_tab(state, f"after kind={kind!r}")
            if kind in CHANNEL_PANELS:
                assert state["activeTab"] == kind, f"kind={kind!r} did not select its own tab"
            assert state["designVisible"], f"kind={kind!r} hid the Custom Art panel"

        await browser.close()


@pytest.mark.asyncio
async def test_saved_non_panel_channel_rehydrates_without_blanking():
    """A device whose last activity was a gallery push ('image') must not
    blank the Channels card when it is selected on the bench."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        mac = "55:66:77:88:99:AA"
        state = await eval_js(page, """([mac, stateJs]) => {
            window.saveDeviceChannel(mac, 'image', { src: '' });
            window.DivoomState.discoveredDevices = [{ address: mac, name: "Ditoo-Test", room: "Desk" }];
            window.SpatialStage.refresh();
            if (window.syncChannelControlsToDisplay) window.syncChannelControlsToDisplay(mac);
            return (%s)();
        }""" % PANEL_STATE_JS, [mac, None])
        _assert_one_visible_matching_tab(state, "after rehydrating a saved 'image' channel")
        assert state["designVisible"], "rehydrating 'image' hid the Custom Art panel"
        await browser.close()


@pytest.mark.asyncio
async def test_channel_tab_click_never_touches_custom_art():
    """Clicking through the Channels tabs must leave Custom Art visible."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        for ch in sorted(CHANNEL_PANELS):
            state = await eval_js(page, """([ch, _]) => {
                document.querySelector(`.tab-btn[data-channel="${ch}"]`).click();
                return (%s)();
            }""" % PANEL_STATE_JS, [ch, None])
            _assert_one_visible_matching_tab(state, f"after clicking tab {ch!r}")
            assert state["activeTab"] == ch
            assert state["designVisible"], f"clicking tab {ch!r} hid the Custom Art panel"
        await browser.close()
