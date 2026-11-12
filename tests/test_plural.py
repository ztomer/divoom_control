"""DV.HEDGE: a count meets its noun; no divoom message hedges its plural.

The helper twins (`divoom_lib.utils.plural` for shipped Python, `divoomd/src/plural.rs` for the
daemon) follow goh's `tui.lib.counted` contract; the sweep is held by `goh plural-hedge`, which
reads this repo's string literals and must find nothing (the seed file is gone).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from divoom_lib.utils.plural import counted, noun

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_exactly_one_is_singular():
    assert counted(1, "file") == "1 file"
    assert counted(0, "file") == "0 files"
    assert counted(2, "file") == "2 files"


def test_an_irregular_plural_is_named():
    assert counted(1, "entry", "entries") == "1 entry"
    assert counted(3, "entry", "entries") == "3 entries"
    assert noun(1, "process", "processes") == "process"
    assert noun(0, "process", "processes") == "processes"


def test_no_plural_hedge_seed_is_left_for_this_repo():
    seed = ROOT / "plural_hedge_seed.json"
    assert not seed.exists(), "plural_hedge_seed.json still names hedged plurals: sweep them (DV.HEDGE)"
