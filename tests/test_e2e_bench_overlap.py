"""E2E -- saved places drawn at real panel sizes do not overlap on the bench.

Found 2026-11-01: the bench's saved places were laid out when every panel was
drawn as the generic 120 mm chassis; drawn at the daemon's real sizes (a Pixoo
is 200 mm, a Tivoo Max 184 mm) neighbours overlapped. The arrangement is the
owner's, so it opens up rather than being re-laid-out
(`SpatialSnap.separate`, pinned in `tests/test_spatial_separate.py`): rows and
order are kept, nothing is written to the daemon until the owner moves a
panel, and the wall's slots are cut where the bench draws.

Skipped if a browser isn't installed (runs with --run-browser).
"""

import json

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js
from tests.test_e2e_room_lists_its_panels import _MOCK_API
from tests.test_e2e_bench_snap import INDEX_HTML

CHASSIS = {"ditoo": (90.0, 114.0, 64.0), "tivoo_max": (184.0, 163.0, 110.0), "pixoo": (200.0, 200.0, 158.0)}
PANELS = [
    ("aa000000-0000-4000-8000-000000000001", "Ditoo-light-2", "DITOO", "ditoo"),
    ("bb000000-0000-4000-8000-000000000002", "Tivoo-Max-light-3", "TivooMax", "tivoo_max"),
    ("cc000000-0000-4000-8000-000000000003", "Pixoo-1", "Pixoo", "pixoo"),
]
# 78 px generic drawings, 12 px apart: the places the old bench saved.
SAVED = {PANELS[0][0]: (20, 95), PANELS[1][0]: (110, 63), PANELS[2][0]: (200, 39)}


def _panel(mac, model, family):
    w, h, screen = CHASSIS[family]
    return {
        "mac": mac,
        "connected": True,
        "selected": False,
        "model": model,
        "width": 16,
        "height": 16,
        "model_source": "name",
        "features": {"speaker": False},
        "chassis": {"family": family, "w_mm": w, "h_mm": h, "screen_mm": screen},
        "wall_refusal": None,
    }


_RECTS = """() => [...document.querySelectorAll('#spatial-bench .spatial-node')].map(n => {
    const r = n.getBoundingClientRect();
    return {id: n.id.slice('spatial-node-'.length), x: r.left, y: r.top, w: r.width, h: r.height}; })"""


@pytest.mark.asyncio
async def test_generic_places_at_real_sizes_open_up_without_a_write():
    require_browser()
    from playwright.async_api import async_playwright

    topology = {
        "rooms": ["Shelf"],
        "wall_linked": True,
        "devices": {m: {"room": "Shelf", "x": x, "y": y} for m, (x, y) in SAVED.items()},
    }
    init = _MOCK_API.replace("%PANELS%", json.dumps([_panel(m, mo, f) for m, _, mo, f in PANELS])).replace(
        "%TOPOLOGY%", json.dumps(topology)
    )
    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await add_init_js(page, init)
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialRooms?.isLoaded()")
            owned = [{"address": m, "name": n, "kind": "clock", "state": "active"} for m, n, _, _ in PANELS]
            await eval_js(page, "(d) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: d})", owned)
            await eval_js(page, "() => window.refreshPanelFacts()")
            # Drawn at the real Pixoo size (200 mm * 0.65), not the generic 78 px.
            await wait_js(page, f"() => document.getElementById('spatial-node-{PANELS[2][0]}')?.offsetWidth === 130")
            rects = await eval_js(page, _RECTS)
            by = {r["id"]: r for r in rects}
            assert len(by) == 3, rects
            for i, a in enumerate(rects):
                for b in rects[i + 1 :]:
                    assert not (
                        a["x"] < b["x"] + b["w"] - 0.5
                        and b["x"] < a["x"] + a["w"] - 0.5
                        and a["y"] < b["y"] + b["h"] - 0.5
                        and b["y"] < a["y"] + a["h"] - 0.5
                    ), (a, b)
            order = [m for m, *_ in PANELS]
            assert [by[m]["x"] for m in order] == sorted(by[m]["x"] for m in order), rects
            # Rows kept: each panel's top is where it was saved.
            tops = {m: by[m]["y"] - by[order[0]]["y"] for m in order}
            assert tops == {m: SAVED[m][1] - SAVED[order[0]][1] for m in order}, tops
            # Opening up is the drawing's; the owner's store is not written.
            calls = await eval_js(page, "() => window.__calls.filter(c => c.m === 'set_topology')")
            assert calls == [], calls
            # The wall cuts where the bench draws.
            slots = await eval_js(page, "() => window.SpatialRooms.getWallSlots()")
            left = by[order[0]]["x"]
            for m in order:
                assert slots[m]["x"] - SAVED[order[0]][0] == round(by[m]["x"] - left), (m, slots[m], by[m])
        finally:
            await browser.close()
