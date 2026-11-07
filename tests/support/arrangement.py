"""The daemon's arrangement, answered for a page that has no bridge of its own.

Since 2026-11-01 the bench draws nothing until it has read the daemon's
topology (`divoom_gui/web_ui/spatial_rooms.js`): the daemon is the
arrangement's one store, and a bench drawn from a guess is the defect that
lost the owner's rooms. A suite that loads `index.html` without a fake bridge
therefore sees the loading state, exactly as the app would with no daemon.
`answer_arrangement` stands in for the daemon's one reply: it gives the page a
bridge that answers `get_topology`, waits for the read to land, and puts the
page's own `window.pywebview` back (none, for most of these suites).
"""

from __future__ import annotations

import json

from tests.support.browser import eval_js

DEFAULT_TOPOLOGY = {"rooms": ["Desk", "Shelf", "Wall"], "wall_linked": True, "devices": {}}

_JS = """async (top) => {
    const had = Object.prototype.hasOwnProperty.call(window, 'pywebview'), prior = window.pywebview;
    window.pywebview = { api: { get_topology: () => Promise.resolve({ success: true, topology: top, screens: [] }),
                                set_topology: () => Promise.resolve({ success: true }) } };
    await window.SpatialRooms.loadTopology();
    if (had) window.pywebview = prior; else delete window.pywebview;
    return window.SpatialRooms.isLoaded();
}"""


async def answer_arrangement(page, topology: dict | None = None) -> None:
    """Async API: the daemon's arrangement read lands on `page`."""
    loaded = await eval_js(page, _JS, json.loads(json.dumps(topology or DEFAULT_TOPOLOGY)))
    assert loaded, "the bench did not take the daemon's arrangement"


def answer_arrangement_sync(page, topology: dict | None = None) -> None:
    """Sync API counterpart of :func:`answer_arrangement`."""
    loaded = eval_js(page, _JS, json.loads(json.dumps(topology or DEFAULT_TOPOLOGY)))
    assert loaded, "the bench did not take the daemon's arrangement"
