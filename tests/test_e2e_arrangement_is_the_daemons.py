"""E2E -- the bench's arrangement is the daemon's, and nothing else (2026-11-01).

The owner: "divoom control seems to be forgetting the device arrangements on
each restart... is this only when the devices are not connected?" It was not.
Three things made it, and they are one class -- the arrangement had a second
store that could speak for the first:

1. **The page's storage was the bench's source.** Places, rooms and the room
   list lived in localStorage, which pywebview's default private mode wipes at
   every launch, so the bench drew from an empty store.
2. **The daemon's copy was read once, and a failure was silent.** One
   ``get_topology`` on load, ``catch -> null``, never retried; the bench drew
   from the empty store meanwhile.
3. **A write before that read sent the GUI's guesses over the daemon's copy.**
   ``getRooms()`` fell back to Desk/Shelf/Wall, every sync sent ``rooms``,
   and the daemon REPLACED its list with it -- the custom room "Ethan" was
   erased for good.

The fix: ``spatial_rooms.js`` holds the daemon's copy and nothing else; the
bench shows a loading state until it is here; the read is retried; every
write is refused before it; writes send only what changed, and a room list
merges (a removal is ``remove_rooms``). These drive the real web UI with a
fake bridge whose ``get_topology`` the test controls.

Skipped if a browser isn't installed (runs with --run-browser).
"""

import json

import pytest

from tests.support.browser import add_init_js, eval_js, install_toast_recorder, launch, require_browser, wait_js
from tests.test_e2e_bench_snap import INDEX_HTML, _drag, _panel

A, B = "aa000000-0000-4000-8000-000000000001", "bb000000-0000-4000-8000-000000000002"
OFF = "cc000000-0000-4000-8000-000000000003"  # placed, off, never seen this session
NAMES = {A: "Pixoo-1", B: "Ditoo-light-2"}
OWNERS = {
    "rooms": ["Desk", "Shelf", "Wall", "Ethan"],
    "wall_linked": True,
    "devices": {
        A: {"room": "Shelf", "x": 300, "y": 40},
        B: {"room": "Ethan", "x": 140, "y": 60},
        OFF: {"room": "Wall", "x": 420, "y": 30},
    },
}
# What the page's storage held on the owner's machine: an invented fleet and
# stale places. None of it may reach the bench or the daemon.
STALE = {
    "divoom_stage_room_list": ["Desk", "Shelf", "Wall"],
    "divoom_stage_positions": {A: {"x": 5, "y": 5}, "11:22:33:44:55:01": {"x": 50, "y": 100}},
    "divoom_stage_rooms": {A: "Desk", "11:22:33:44:55:01": "Desk"},
}

_MOCK_API = """
window.__panels = %PANELS%;
window.__topology = %TOPOLOGY%;
window.__failTopology = %FAILS%;   // answers this many reads with a failure first
window.__topologyReads = 0;
window.__calls = [];
const __stale = %STALE%;
try { Object.keys(__stale).forEach(k => localStorage.setItem(k, JSON.stringify(__stale[k]))); } catch (_) {}
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: window.__panels}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  get_topology: () => {
    window.__topologyReads += 1;
    if (window.__topologyReads <= window.__failTopology) return {success: false, error: 'daemon unavailable'};
    return {success: true, topology: window.__topology, screens: []};
  },
  set_topology: (t) => { window.__calls.push({m: 'set_topology', args: [t]}); return {success: true}; },
  update_wall_slots: (s) => { window.__calls.push({m: 'update_wall_slots', args: [s]}); return null; },
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""

_WRITES = "() => window.__calls.filter(c => c.m === 'set_topology').map(c => c.args[0])"


async def _open(p, fails, macs=(A, B)):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    init = (
        _MOCK_API.replace("%PANELS%", json.dumps([_panel(m) for m in macs]))
        .replace("%TOPOLOGY%", json.dumps(OWNERS))
        .replace("%FAILS%", str(fails))
        .replace("%STALE%", json.dumps(STALE))
    )
    await add_init_js(page, init)
    await install_toast_recorder(page)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage && !!window.SpatialRooms")
    owned = [{"address": m, "name": NAMES[m], "kind": "clock", "state": "active"} for m in macs]
    await eval_js(page, "(devs) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: devs})", owned)
    await eval_js(page, "() => window.refreshPanelFacts()")
    return browser, page


async def _place(page, mac):
    return await eval_js(
        page,
        """(m) => { const n = document.getElementById('spatial-node-' + m);
        return n ? {x: n.offsetLeft, y: n.offsetTop} : null; }""",
        mac,
    )


@pytest.mark.asyncio
async def test_the_bench_waits_for_the_daemon_and_writes_nothing_meanwhile():
    """The daemon does not answer at first: the bench says it is loading, and
    why, draws no panel from the page's stale storage, and every gesture that
    would write is refused. When the daemon answers, its copy is drawn."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, fails=3)
        try:
            await wait_js(page, "() => !!document.getElementById('spatial-bench-loading')")
            assert await eval_js(page, "() => document.querySelectorAll('#spatial-bench .spatial-node').length") == 0
            # Gestures that wrote before the read landed.
            await eval_js(page, "() => window.SpatialRooms.addRoom('Guess')")
            await eval_js(page, "(m) => window.SpatialRooms.assignRoom(m, 'Desk')", A)
            await eval_js(page, "(m) => window.SpatialRooms.savePositions({[m]: {x: 1, y: 1}})", A)
            await eval_js(page, "() => document.getElementById('stage-snap-btn')?.click()")
            await eval_js(page, "() => window.syncArrangerToPython && window.syncArrangerToPython()")
            await wait_js(
                page, "() => /try [2-9]/.test(document.getElementById('spatial-bench-loading')?.textContent || '')"
            )
            text = await eval_js(page, "() => document.getElementById('spatial-bench-loading').textContent")
            assert "daemon unavailable" in text and "Retrying" in text, f"the loading state says why: {text!r}"
            assert await eval_js(page, _WRITES) == [], "nothing is written before the daemon's copy is read"
            assert await eval_js(page, "() => window.__calls.filter(c => c.m === 'update_wall_slots').length") == 0

            # The daemon answers (the 4th read): its copy is the bench.
            await wait_js(page, f"() => !!document.getElementById('spatial-node-{A}')")
            assert await eval_js(page, "() => !document.getElementById('spatial-bench-loading')")
            assert await _place(page, A) == {"x": 300, "y": 40}, "the daemon's place, not the stale one"
            assert await eval_js(page, "() => window.SpatialRooms.getRooms()") == ["Desk", "Shelf", "Wall", "Ethan"]
            assert await eval_js(page, "(m) => window.SpatialRooms.roomOf(m)", B) == "Ethan"
            gone = await eval_js(page, "(ks) => ks.filter(k => localStorage.getItem(k) !== null)", list(STALE))
            assert gone == [], f"the page's old copies are dropped: {gone}"
            assert await eval_js(page, _WRITES) == [], "reading the daemon's copy writes nothing back"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_write_sends_what_changed_and_never_the_room_list():
    """After the read: a drag sends that panel's whole entry (its room kept);
    adding a room sends that room alone; removing one names it. No write
    carries a room list the daemon could replace its own with."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, fails=0)
        try:
            await wait_js(page, f"() => !!document.getElementById('spatial-node-{A}')")
            await _drag(page, A, 40, 0)
            await wait_js(page, f"() => ({_WRITES})().length >= 1")
            drag = (await eval_js(page, _WRITES))[-1]
            assert list(drag) == ["devices"] and list(drag["devices"]) == [A], drag
            assert drag["devices"][A]["room"] == "Shelf", f"a drag keeps the panel's room: {drag}"
            assert drag["devices"][A]["x"] != 300, drag

            await eval_js(page, "() => window.SpatialRooms.addRoom('Den')")
            assert (await eval_js(page, _WRITES))[-1] == {"rooms": ["Den"]}

            await eval_js(page, "() => window.SpatialRooms.removeRoom('Ethan')")
            last = (await eval_js(page, _WRITES))[-1]
            assert last["remove_rooms"] == ["Ethan"], last
            assert last["devices"][B]["room"] == "Desk", last
            assert all("rooms" not in w or w["rooms"] == ["Den"] for w in await eval_js(page, _WRITES))
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_panel_that_is_off_keeps_its_wall_slot():
    """A panel the daemon's layout places but this session has not seen (off,
    or out of range) keeps its slot: the wall is the arrangement, not the scan."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, fails=0)
        try:
            await wait_js(page, f"() => !!document.getElementById('spatial-node-{A}')")
            slots = await eval_js(page, "() => window.SpatialRooms.getWallSlots()")
            assert OFF in slots, f"the off panel keeps its slot: {sorted(slots)}"
            assert (slots[OFF]["x"], slots[OFF]["y"], slots[OFF]["room"]) == (420, 30, "Wall"), slots[OFF]
            assert sorted(slots) == sorted([A, B, OFF]), sorted(slots)
        finally:
            await browser.close()
