"""E2E -- the GUI sends ``set_device_activity`` only for a panel the daemon
reported (P5.9).

P5.8 made the daemon refuse an activity record for any id no link ever made
a fleet entry: ``MatrixWall`` (the wall surface, not a panel), a typo, a scan
result it never linked. The GUI kept sending them -- ``window.setDeviceActivity``
forwarded every kind but ``image`` to the bridge, whatever the mac -- so each
one was a round trip to a refusal. The playlist, photo-album and sleep-aid
writers name ``MatrixWall`` whenever the wall is the selected target.

What this pins, against a fake bridge that records every call: with one
panel reported and a wall placed, recording activity on the wall, on a mac
the daemon never reported, and on the reported panel sends exactly one
``set_device_activity``, for the reported panel. That one is the calibration:
the recorder sees the call when it is made, so the absence of the others is
not the recorder missing them.

Skipped if a browser isn't installed (runs with --run-browser).
"""
import json
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

REPORTED = "CC:00:00:00:00:03"
UNREPORTED = "DD:00:00:00:00:09"

_MOCK_API = """
window.__calls = [];
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    window.__calls.push({name: String(name), args: JSON.stringify(args)});
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _activity_macs(page):
    calls = await eval_js(page, "() => window.__calls")
    return [json.loads(c["args"])[0] for c in calls if c["name"] == "set_device_activity"]


@pytest.mark.asyncio
async def test_activity_is_sent_only_for_a_panel_the_daemon_reported():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await add_init_js(page, _MOCK_API)
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.setDeviceActivity && !!window.Divoom?.onOwnedDevices")
            await eval_js(page, """(m) => {
                window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
                    {address: m, name: 'Shelf', kind: 'clock', state: 'active'}]});
                // A wall is placed, so the GUI treats MatrixWall as a target.
                window.DivoomState.assignedSlots = {[m]: {x: 0, y: 0}};
                window.__calls = [];
            }""", REPORTED)
            assert await eval_js(page, "() => window.isKnownTarget('MatrixWall')"), (
                "the wall must be a GUI target for this to test anything")

            await eval_js(page, """([wall, stranger, mine]) => {
                window.setDeviceActivity(wall, 'playlist', {playId: 1});
                window.setDeviceActivity(stranger, 'clock', {});
                window.setDeviceActivity(mine, 'clock', {});
            }""", ["MatrixWall", UNREPORTED, REPORTED])
            # The thumbnail is rasterised asynchronously before the call goes.
            await wait_js(page, "() => window.__calls.some(c => c.name === 'set_device_activity')")
            await eval_js(page, "() => new Promise(r => setTimeout(r, 300))")

            sent = await _activity_macs(page)
            assert REPORTED in sent, f"calibration: the reported panel's record was not seen: {sent}"
            assert sent == [REPORTED], (
                f"set_device_activity named ids the daemon never reported: {sent}")
        finally:
            await browser.close()
