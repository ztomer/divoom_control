"""E2E -- a room on the Spatial Bench lists exactly the panels assigned to it (U.4).

The owner, 2026-10-26: "when removing a device from a location, it should not
show there (I moved the timoo device to a new location and all the devices show
up everywhere, grayed out)."

Two defects made that, and both are one class -- a panel's room was decided in
more than one place:

1. **A room filter only DIMMED.** ``refreshBenchNodes`` drew every panel the
   fleet has in every room and greyed out the ones not in it, so each room
   showed all four panels, three of them grey, and Desk showed four grey ones.
2. **The bench kept its own copy of the room map**, refreshed with
   ``Object.assign`` -- which adds and overwrites but never removes. Taking a
   panel out of a room (the Devices popover's checkbox) deleted it from the
   store, the copy kept it, the bench went on showing it in the room, and the
   next drag, Center or Snap wrote the copy back over the removal. Meanwhile
   the daemon sync filled an unassigned panel in as "Desk", and the wall's
   slot list did the same, so "no room" meant three different things.

The fix is one reader (``SpatialRooms.roomOf``) and one writer
(``SpatialRooms.assignRoom``); these tests drive the real web UI through the
real gestures (the deck's room select, the add-room pill, the Devices popover,
a drag) and read what the bench draws.

Skipped if a browser isn't installed (runs with --run-browser).
"""
import json

import pytest

from tests.support.browser import add_init_js, eval_js, install_toast_recorder, launch, require_browser, wait_js
from tests.test_e2e_bench_snap import INDEX_HTML, _drag, _panel

A, B, T = "aa000000-0000-4000-8000-000000000001", "bb000000-0000-4000-8000-000000000002", \
    "cc000000-0000-4000-8000-000000000003"
NAMES = {A: "Pixoo-1", B: "Ditoo-light-2", T: "Timoo-light-4"}

_MOCK_API = """
window.__panels = %PANELS%;
window.__topology = %TOPOLOGY%;
window.__calls = [];
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: window.__panels}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  get_topology: () => ({success: true, topology: window.__topology}),
  set_topology: (t) => { window.__calls.push({m: 'set_topology', args: [t]}); return {success: true}; },
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""

_ON_BENCH = """() => [...document.querySelectorAll('#spatial-bench .spatial-node')]
    .map(n => n.id.slice('spatial-node-'.length)).sort()"""


async def _open(p, macs, topology=None, stored_rooms=None):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    # The daemon's copy is the bench's one store; a test that names none gets
    # the daemon's default layout. `stored_rooms` is a STALE page-storage copy
    # (what the owner's machine held), seeded before load: it must count for
    # nothing.
    topology = topology or {"rooms": ["Desk", "Shelf", "Wall"], "wall_linked": True, "devices": {}}
    init = (_MOCK_API.replace("%PANELS%", json.dumps([_panel(m) for m in macs]))
            .replace("%TOPOLOGY%", json.dumps(topology)))
    if stored_rooms:
        init = (f"try {{ localStorage.setItem('divoom_stage_rooms', {json.dumps(json.dumps(stored_rooms))}); }}"
                " catch (_) {}\n" + init)
    await add_init_js(page, init)
    await install_toast_recorder(page)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage && !!window.SpatialRooms")
    await wait_js(page, "() => window.SpatialRooms.isLoaded()")
    owned = [{"address": m, "name": NAMES[m], "kind": "clock", "state": "active"} for m in macs]
    await eval_js(page, "(devs) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: devs})", owned)
    await eval_js(page, "() => window.refreshPanelFacts()")
    for mac in macs:
        await wait_js(page, f"() => !!document.getElementById('spatial-node-{mac}')")
    return browser, page


async def _select(page, mac):
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", mac)
    await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{mac}'")


async def _assign(page, mac, room):
    """The deck's room select: what the owner used to move the Timoo."""
    await _select(page, mac)
    await page.select_option("#deck-room-select", room)


async def _add_room(page, name):
    await page.click(".stage-room-add-btn")
    await page.fill(".stage-room-input", name)
    await page.click(".stage-room-confirm-btn")
    await wait_js(page, f"() => !!document.querySelector('.stage-room-pill[data-room=\"{name}\"]')")


async def _show(page, room):
    await page.click(f'.stage-room-pill[data-room="{room}"]')
    await wait_js(page, f"() => document.querySelector('.stage-room-pill.active')?.dataset.room === '{room}'")
    return await eval_js(page, _ON_BENCH)


@pytest.mark.asyncio
async def test_a_panel_moved_to_another_room_shows_only_there():
    """The owner's gesture exactly: three panels on the Shelf, the Timoo moved to
    a new room. Each room draws its own panels and no others -- not greyed, absent."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [A, B, T])
        try:
            for mac in (A, B, T):
                await _assign(page, mac, "Shelf")
            await _add_room(page, "Ethan")
            await _assign(page, T, "Ethan")

            assert await _show(page, "Shelf") == sorted([A, B]), "the Shelf lists its two panels, not the Timoo"
            assert await _show(page, "Ethan") == [T], "the new room lists the Timoo alone"
            assert await _show(page, "Desk") == [], "a room with no panels draws none"
            empty = await eval_js(page, "() => document.getElementById('spatial-bench-room-empty')?.textContent")
            assert empty and "Desk" in empty, f"an empty room says so, by name: {empty!r}"
            assert await _show(page, "all") == sorted([A, B, T]), "All is every panel"
            counts = await eval_js(page, """() => Object.fromEntries([...document.querySelectorAll('.stage-room-pill')]
                .map(p => [p.dataset.room, p.querySelector('.stage-room-pill-count').textContent]))""")
            assert counts["Shelf"] == "(2)" and counts["Ethan"] == "(1)" and counts["Desk"] == "(0)", counts
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_panel_taken_out_of_a_room_stays_out_after_a_drag():
    """The Devices popover's checkbox removes a panel from the room; the bench
    stops drawing it there, and a drag afterwards (which saves the layout) does
    not write the old room back -- locally or to the daemon."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [A, B, T])
        try:
            for mac in (A, B):
                await _assign(page, mac, "Shelf")
            assert await _show(page, "Shelf") == sorted([A, B])

            await page.click(".stage-room-manage-btn")
            await page.locator(".room-device-item", has_text=NAMES[B]).locator("input").uncheck()
            await wait_js(page, f"() => !document.getElementById('spatial-node-{B}')")
            assert await eval_js(page, _ON_BENCH) == [A], "a panel taken out of the room is not drawn in it"

            before = await eval_js(page, "() => window.__calls.length")
            await _drag(page, A, 40, 0)
            await wait_js(page, f"() => window.__calls.length > {before}")
            assert await eval_js(page, _ON_BENCH) == [A], "the drag must not put it back"
            assert await eval_js(page, f"() => window.SpatialRooms.roomOf('{B}')") == "", (
                "the stored room stays empty after the drag saved the layout")
            sent = [c["args"][0] for c in await eval_js(page, "() => window.__calls")]
            # What the daemon holds is each panel's LAST entry sent (it replaces
            # an entry whole): fold the writes.
            held = {}
            for w in sent:
                held.update(w.get("devices", {}))
            assert held[A]["room"] == "Shelf", held
            assert B in held and held[B].get("room") is None, (
                f"the daemon is told the panel has no room -- not Shelf, and not an invented Desk: {held}")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_rooms_the_daemon_stored_are_read_as_stored():
    """The owner's stored topology, shape for shape (2026-10-31): the Timoo in its
    new room, three panels on the Shelf, four placements left from the invented
    fleet in Desk, and one key in another letter case. A stale local room the
    daemon no longer holds is dropped, and a placement that names no panel the
    daemon reports is drawn nowhere."""
    require_browser()
    from playwright.async_api import async_playwright

    ghosts = {f"11:22:33:44:55:0{i}": {"room": "Desk", "x": 50 * i, "y": 100} for i in range(1, 5)}
    topology = {"rooms": ["Desk", "Shelf", "Wall", "Ethan"], "wall_linked": True, "devices": {
        **ghosts,
        A: {"room": "Shelf", "x": 681, "y": 39},
        B.upper(): {"room": "Shelf", "x": 502, "y": 95},
        T: {"room": "Ethan", "x": 448, "y": 110},
    }}
    async with async_playwright() as p:
        browser, page = await _open(p, [A, B, T], topology, stored_rooms={T: "Shelf"})
        try:
            await eval_js(page, "() => window.SpatialRooms.loadTopology()")
            assert await _show(page, "Ethan") == [T]
            assert await _show(page, "Shelf") == sorted([A, B]), (
                "the Shelf lists its panels, the upper-case key included, and not the Timoo's stale local room")
            assert await _show(page, "Desk") == [], "the placements of panels nobody reports are drawn nowhere"
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["divoom:rooms-updated", "divoom:topology-loaded"])
async def test_an_open_add_room_form_survives_a_redraw_of_the_pills(event):
    """The add-room form lived inside the pills' container, and every redraw of
    the pills (`renderFilterPills` clears it) destroyed it: a room assignment's
    announcement, a topology load or a fleet refresh arriving between "+" and
    "Add" took the typed name with it. CI saw it three times as a 60 s timeout
    on `.stage-room-confirm-btn` (runs 41325215656 and 41357616000, and under
    -n 4 locally) -- the click waited for a button no longer in the page. A
    redraw must give the form back, with what was typed."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [A, B, T])
        try:
            await page.click(".stage-room-add-btn")
            await page.fill(".stage-room-input", "Ethan")
            await eval_js(page, "(e) => window.dispatchEvent(new CustomEvent(e, {detail: {}}))", event)
            assert await eval_js(page, "() => document.querySelector('.stage-room-input')?.value") == "Ethan", (
                "the redraw took the open form and its typed name")
            await page.click(".stage-room-confirm-btn")
            await wait_js(page, "() => !!document.querySelector('.stage-room-pill[data-room=\"Ethan\"]')")
            assert await eval_js(page, "() => document.querySelector('.stage-room-input')") is None, (
                "the form closes once the room is added")
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [".stage-room-add-btn", '.stage-room-pill[data-room="Shelf"]'])
async def test_a_redraw_between_press_and_release_does_not_swallow_the_click(target):
    """A click is a press and a release on ONE element. The pills' redraw rebuilt
    every button, so a redraw landing between the two (a scan result, a room
    announcement) left the release on a new button and the browser fired no
    click at all: "+" opened no form, a pill selected nothing -- a dead button.
    The redraw keeps each control's element, so the click still lands."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, [A, B, T])
        try:
            box = await page.locator(target).bounding_box()
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.down()
            await eval_js(page, "() => window.dispatchEvent(new CustomEvent('divoom:rooms-updated', {detail: {}}))")
            await page.mouse.up()
            if target == ".stage-room-add-btn":
                await wait_js(page, "() => !!document.querySelector('.stage-room-input')")
            else:
                await wait_js(page, "() => document.querySelector('.stage-room-pill.active')?.dataset.room === 'Shelf'")
        finally:
            await browser.close()
