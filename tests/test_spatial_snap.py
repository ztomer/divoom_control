"""Where a dragged panel lands: `SpatialSnap.snap` (P6.1), run under node.

A wall slices one image by each slot's place on the bench, so panels meant to be
one surface must touch edge to edge. The geometry is one pure function; these
pin its edge cases -- a near-miss within the threshold, one just past it, a drop
ON another panel, panels of different sizes, a chain of three, corners, and the
bench's bounds. The browser test that drags a real node is
`tests/test_e2e_bench_snap.py`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SNAP_JS = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "spatial_snap.js"

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const [jsPath, casesJson] = process.argv.slice(-2);
const ctx = { window: {} };
vm.runInNewContext(fs.readFileSync(jsPath, "utf8"), ctx);
const out = JSON.parse(casesJson).map(([m, others, opts]) => ctx.window.SpatialSnap.snap(m, others, opts));
process.stdout.write(JSON.stringify({ out, threshold: ctx.window.SpatialSnap.THRESHOLD }));
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _snap(*cases):
    r = subprocess.run(["node", "-e", _HARNESS, "--", str(SNAP_JS), json.dumps(cases)],
                       capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    return json.loads(r.stdout)


def rect(x, y, w=50, h=50):
    return {"x": x, "y": y, "w": w, "h": h}


def _land(moving, others, opts=None):
    got = _snap([moving, others, opts or {}])["out"][0]
    return got["x"], got["y"], got["snapped"]


def test_a_near_miss_within_the_threshold_snaps_flush_and_lines_up():
    a = rect(100, 100)
    # 8 px short of A's right edge and 5 px low: flush, top-aligned.
    assert _land(rect(158, 105), [a]) == (150, 100, True)
    # The same from the other three sides.
    assert _land(rect(42, 96), [a]) == (50, 100, True)       # left of A
    assert _land(rect(103, 41), [a]) == (100, 50, True)      # above A
    assert _land(rect(97, 159), [a]) == (100, 150, True)     # below A


def test_just_past_the_threshold_stays_where_it_was_dropped():
    t = _snap([rect(0, 0), [], {}])["threshold"]
    a = rect(100, 100)
    assert _land(rect(150 + t + 1, 100), [a]) == (150 + t + 1, 100, False)
    assert _land(rect(150 + t, 100), [a]) == (150, 100, True), "the threshold itself snaps"


def test_a_drop_on_another_panel_is_pushed_to_the_nearest_flush_spot():
    a = rect(100, 100)
    # Mostly over A's right half: out to the right, lined up.
    assert _land(rect(130, 104), [a]) == (150, 100, True)
    # Mostly over A's top half: out above.
    assert _land(rect(102, 70), [a]) == (100, 50, True)


def test_panels_of_different_sizes_meet_edge_to_edge():
    big = rect(100, 100, 100, 100)          # a 64x64 panel's chassis next to...
    small = rect(206, 140, 40, 40)          # ...a 16x16's, dropped 6 px off
    assert _land(small, [big]) == (200, 140, True), "flush, kept where it was along the edge"
    assert _land(rect(206, 104, 40, 40), [big]) == (200, 100, True), "top-aligned when near the top"
    assert _land(rect(206, 157, 40, 40), [big]) == (200, 160, True), "bottom-aligned when near the bottom"


def test_a_chain_of_three_is_one_contiguous_row():
    a = rect(0, 0)
    b = rect(50, 0)                          # already flush right of A
    x, y, snapped = _land(rect(107, 3), [a, b])
    assert (x, y, snapped) == (100, 0, True), "C joins the row after B"
    # Dropped onto the A|B seam, C is pushed out to the nearest flush spot --
    # under the seam, touching both -- never into either.
    assert _land(rect(30, 10), [a, b]) == (30, 50, True)


def test_a_corner_is_not_a_contact():
    a = rect(100, 100)
    # Off A's corner on both axes: no edge is shared, and lining one up is
    # further than the threshold, so it stays where it was dropped.
    assert _land(rect(155, 155), [a]) == (155, 155, False)
    # Past the corner along the edge, it touches the edge it now overlaps.
    assert _land(rect(155, 140), [a]) == (150, 140, True)


def test_nothing_lands_outside_the_bench():
    a = rect(0, 0)
    # Left of A would be x=-50: off the bench, so not a candidate.
    assert _land(rect(-4, 0), [a], {"bounds": {"w": 400, "h": 300}})[:2] != (-50, 0)
    x, y, _ = _land(rect(46, 2), [a], {"bounds": {"w": 400, "h": 300}})
    assert (x, y) == (50, 0)
