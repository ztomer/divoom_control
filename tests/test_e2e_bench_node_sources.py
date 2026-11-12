"""E2E -- what a bench node draws, and what its status says, come from the daemon's meaning.

DV.CLOCKTHUMB (2026-11-11): the GUI records a panel's channel with
`set_device_activity` and a 36 px PNG for the menubar's tile; the daemon echoed
that PNG back as the `activity` event's `preview`, and `onActivity` drew it as
the node's frame. The Ditoo node showed a blurred, upscaled clock instead of
the crisp one the shared renderer draws at node size. The echo is marked
`preview_is: "thumbnail"` now (divoomd `set_device_activity`), the node keeps
its own render, and a live job's frame (no mark) still draws.

DV.DEVICECOUNT (2026-11-11): the daemon said 3 owned panels and the bench drew
4. Neither was wrong: `owned_devices` is the set the daemon has LINKED, and
`get_topology` reports the fourth (Timoo-light-4, a real scanned panel placed
in a room) with `connected: false`. The bench drew it with a grey dot, the only
thing that said it was not linked -- one channel, colour. The jewel is a
hollow ring with a name for a panel the daemon does not own, so the linked
count the bench shows is the daemon's owned count.

Skipped if a browser isn't installed (runs with --run-browser).
"""

import pytest

from tests.support.browser import eval_js, require_browser, wait_js
from tests.test_e2e_bench_preview_never_blank import PANELS, _bench

DITOO = PANELS[0][0]
# A 2x2 PNG: what the menubar tile is, in miniature.
THUMB = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFklEQVR42mP8z8DwnwEJ"
    "MDGgAcICAJ/OAgM0+8xzAAAAAElFTkSuQmCC"
)
UNLINKED = "f90d2cc9-420e-65f9-9e06-f9554470fced"

_SOURCE = """(mac) => { const p = window.DisplayPreviewRegistry.get(mac);
    return {mode: p.mode, src: p.frameSrc}; }"""


@pytest.mark.asyncio
async def test_a_menubar_thumbnail_echo_does_not_replace_the_nodes_own_render():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _bench(p)
        try:
            await eval_js(
                page,
                "(a) => window.Divoom.onActivity({type: 'activity', mac: a[0], kind: 'clock', "
                "name: 'Ditoo-light-2', preview: a[1], preview_is: 'thumbnail'})",
                [DITOO, THUMB],
            )
            got = await eval_js(page, _SOURCE, DITOO)
            assert got == {"mode": "glyph", "src": None}, f"the node drew the 36 px echo: {got}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_live_jobs_frame_still_draws_on_its_node():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _bench(p)
        try:
            await eval_js(
                page,
                "(a) => window.Divoom.onActivity({type: 'activity', mac: a[0], kind: 'sysmon', preview: a[1]})",
                [DITOO, THUMB],
            )
            got = await eval_js(page, _SOURCE, DITOO)
            assert got == {"mode": "frame", "src": THUMB}, got
        finally:
            await browser.close()


_JEWELS = """() => Object.fromEntries([...document.querySelectorAll('#spatial-bench .spatial-node')].map(n => {
    const j = n.querySelector('.spatial-jewel');
    const s = getComputedStyle(j);
    return [n.id.slice('spatial-node-'.length),
            {label: j.getAttribute('aria-label') || '', title: j.getAttribute('title') || '',
             hollow: s.backgroundColor === 'rgba(0, 0, 0, 0)' && parseFloat(s.borderTopWidth) > 0}];
}))"""


@pytest.mark.asyncio
async def test_a_placed_panel_the_daemon_has_not_linked_says_so_in_shape_and_text():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _bench(p)
        try:
            # The scan cache's fourth panel, placed in the room, never linked.
            await eval_js(
                page,
                """(mac) => { window.DivoomState.discoveredDevices.push({address: mac, name: 'Timoo-light-4'});
                window.SpatialStage.refresh(); }""",
                UNLINKED,
            )
            await wait_js(page, "() => document.querySelectorAll('#spatial-bench .spatial-node').length === 3")
            jewels = await eval_js(page, _JEWELS)
            assert jewels[UNLINKED]["hollow"], jewels
            assert "not linked" in jewels[UNLINKED]["label"].lower(), jewels
            assert jewels[UNLINKED]["title"] == jewels[UNLINKED]["label"], jewels
            linked = [m for m, j in jewels.items() if j["label"].lower().startswith("linked")]
            # The bench's linked panels are exactly the daemon's owned ones.
            assert sorted(linked) == sorted(m for m, _, _ in PANELS), jewels
            assert not any(jewels[m]["hollow"] for m in linked), jewels
        finally:
            await browser.close()
