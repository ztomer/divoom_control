"""Saved places drawn at real panel sizes never overlap: `SpatialSnap.separate`.

The bench's saved places were laid out when every panel was drawn as the
generic 120 mm chassis; drawn at their real sizes (a Pixoo is 200 mm, a Tivoo
Max 184 mm) neighbours overlapped. The owner's arrangement is the thing to
keep, so the fix is not a re-layout: panels keep their rows (y), their
left-to-right order and every gap that was not an overlap; a panel that
overlaps one before it moves right just far enough to touch it, and every
panel after it moves by the same amount, so the arrangement only opens up.
The browser test is `tests/test_e2e_bench_overlap.py`.
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
const out = JSON.parse(casesJson).map(([rects, opts]) => ctx.window.SpatialSnap.separate(rects, opts));
process.stdout.write(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _separate(*cases):
    r = subprocess.run(
        ["node", "-e", _HARNESS, "--", str(SNAP_JS), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return json.loads(r.stdout)


def r(id_, x, y, w, h):
    return {"id": id_, "x": x, "y": y, "w": w, "h": h}


def _overlap(a, b):
    return (
        a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"]
    )


def _placed(rects, out):
    return [dict(x, **out[x["id"]]) for x in rects]


def test_a_layout_with_no_overlap_is_left_exactly_as_saved():
    rects = [r("a", 10, 20, 50, 50), r("b", 60, 20, 50, 50), r("c", 200, 0, 40, 40)]
    (out,) = _separate([rects, {}])
    assert out == {x["id"]: {"x": x["x"], "y": x["y"]} for x in rects}


def test_generic_places_drawn_at_real_sizes_open_up_and_keep_the_arrangement():
    # Places saved for 78 px generic drawings, 12 px apart; drawn at real sizes.
    saved = [
        r("ditoo", 20, 95, 59, 74),
        r("tivoo", 110, 63, 120, 106),
        r("pixoo", 200, 39, 130, 130),
        r("timoo", 290, 110, 54, 59),
    ]
    (out,) = _separate([saved, {}])
    placed = _placed(saved, out)
    for i, a in enumerate(placed):
        for b in placed[i + 1 :]:
            assert not _overlap(a, b), (a, b)
    # Rows kept, order kept, and the first panel did not move.
    assert all(out[x["id"]]["y"] == x["y"] for x in saved)
    xs = [out[k]["x"] for k in ("ditoo", "tivoo", "pixoo", "timoo")]
    assert xs == sorted(xs) and xs[0] == 20
    # Moved only as far as needed: each overlapping panel ends flush.
    assert out["tivoo"]["x"] == 110  # 20 + 59 = 79 < 110: no overlap
    assert out["pixoo"]["x"] == 110 + 120  # flush against the Tivoo
    assert out["timoo"]["x"] == 230 + 130  # flush against the Pixoo


def test_a_gap_after_an_overlap_is_kept():
    saved = [r("a", 0, 0, 100, 50), r("b", 50, 0, 100, 50), r("c", 300, 0, 50, 50)]
    (out,) = _separate([saved, {}])
    assert out["b"]["x"] == 100
    # c was 150 px clear of b's right edge; it moves with b, gap intact.
    assert out["c"]["x"] - (out["b"]["x"] + 100) == 300 - (50 + 100)


def test_panels_in_different_rows_do_not_push_each_other():
    saved = [r("top", 0, 0, 100, 40), r("bottom", 20, 40, 100, 40)]
    (out,) = _separate([saved, {}])
    assert out == {"top": {"x": 0, "y": 0}, "bottom": {"x": 20, "y": 40}}


def test_two_panels_on_one_spot_are_set_side_by_side():
    saved = [r("a", 10, 10, 60, 60), r("b", 10, 10, 60, 60)]
    (out,) = _separate([saved, {}])
    assert {out["a"]["x"], out["b"]["x"]} == {10, 70}


def test_a_panel_below_the_bench_floor_is_lifted_inside_it():
    # The Timoo the daemon had not described (off, out of range) is drawn at
    # the generic 78 px: saved at y=110 it hung 8 px below the 180 px bench.
    saved = [r("timoo", 448, 110, 78, 78), r("ditoo", 526, 95, 59, 74)]
    (out,) = _separate([saved, {"height": 180}])
    assert out["timoo"] == {"x": 448, "y": 102}
    assert out["ditoo"] == {"x": 526, "y": 95}


def test_the_bench_height_constant_is_the_stylesheet_s():
    import re

    css = (SNAP_JS.parent / "spatial_stage.css").read_text()
    block = re.search(r"\.spatial-bench \{([^}]*)\}", css).group(1)
    px = int(re.search(r"height:\s*(\d+)px", block).group(1))
    js = int(re.search(r"BENCH_HEIGHT = (\d+);", SNAP_JS.read_text()).group(1))
    assert px == js, f"the bench is {px}px tall in CSS and {js}px in spatial_snap.js"
