"""Both directions of tools/_empty_scope.py, plus the wiring that uses it.

Six gates reported "OK — 0 files clean" over a skeleton tree on 2026-09-07:
compliance asserted over a population of nobody. `test_repo_gates.py` was red on
exactly that, and had been for long enough that the failure read as scenery.

The shared helper is what fixed them, so it needs the calibration every gate
needs: it must stay quiet on a real scope, bite on an empty one, and stay quiet
for `--staged` (a commit touching none of a gate's file kinds legitimately has
nothing to inspect).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

guard = pytest.importorskip("_empty_scope")

#: Every gate wired to the helper. If one is added without the guard,
#: `check_empty_scope.py` catches it; this list keeps the wiring visible here too.
GUARDED = [
    "check_gui_is_a_client.py",
    "check_positional_args.py",
    "check_scripts.py",
    "check_applescript_launch.py",
]

#: The gates that are EXCUSED instead of guarded, and why each is a different thing. Kept beside
#: GUARDED because the two lists must not be confused: a gate in neither is either a gate nobody
#: added a decision about, or one whose decision was lost.
EXCUSED = {
    "check_built_binaries.py": (
        "its subject is build OUTPUT -- a fresh clone and a CI job that builds only what it "
        "needs both legitimately have none, so passing over an empty tree is the correct answer "
        "there, not compliance over an empty set"
    ),
}


def test_a_real_scope_is_not_empty():
    assert guard.scope_is_empty("g", 1) is False
    assert guard.scope_is_empty("g", 500) is False


def test_an_empty_full_tree_scope_bites(capsys):
    assert guard.scope_is_empty("g", 0) is True
    out = capsys.readouterr().out
    assert "inspected 0 files" in out
    assert "scope is gone, not clean" in out


def test_staged_scope_may_legitimately_be_empty():
    """Otherwise the pre-commit hook fires on every unrelated commit."""
    assert guard.scope_is_empty("g", 0, staged=True) is False


def test_the_unit_is_reported_so_the_message_names_what_is_missing(capsys):
    guard.scope_is_empty("positional", 0, unit="cross-language handlers")
    assert "0 cross-language handlers" in capsys.readouterr().out


@pytest.mark.parametrize("gate", GUARDED)
def test_each_guarded_gate_imports_the_shared_helper(gate):
    """One implementation, not six. A copy would drift from the wording a
    future reader has to act on."""
    src = (REPO / "tools" / gate).read_text()
    assert "from _empty_scope import scope_is_empty" in src, gate
    assert "scope_is_empty(" in src, f"{gate} imports the guard but never calls it"


@pytest.mark.parametrize("gate", GUARDED)
def test_each_guarded_gate_still_passes_on_the_real_tree(gate):
    """Calibration in the other direction: the guard must not have broken them."""
    r = subprocess.run(
        [sys.executable, f"tools/{gate}"], cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_blind_list_is_empty():
    """`known_blind` may only ever SHRINK, so it is asserted empty.

    Every gate that was blind on 2026-09-07 was FIXED the same day with `tools/_empty_scope.py`
    rather than excused. An entry here is how that would quietly reverse, which is why this one
    keeps the strict form and `legitimate` below does not."""
    data = json.loads((REPO / "tools" / "empty_scope_allow.json").read_text())
    blind = {k for k in data["known_blind"] if not k.startswith("_")}
    assert blind == set(), (
        f"a blind gate is excused instead of guarded: {sorted(blind)}. It belongs in GUARDED with "
        "tools/_empty_scope.scope_is_empty, not in the allowlist."
    )


def test_every_excused_gate_is_excused_deliberately():
    """`legitimate` is NOT a burn-down list, and this is the property that keeps it honest.

    The file's own header: "`legitimate` is a gate that SHOULD pass over an empty tree and always
    will; `known_blind` is a defect with a name on it, awaiting a guard, and may only ever
    SHRINK." So the assertion is not "the section is empty" -- that was the ratchet before
    2026-10-14, and it was simply wrong about what the section means. It is that every entry
    matches a decision recorded here WITH its reason, and that a gate cannot excuse itself by
    being the only one that thinks so.
    """
    data = json.loads((REPO / "tools" / "empty_scope_allow.json").read_text())
    legit = {k for k in data["legitimate"] if not k.startswith("_")}
    reasons = {k: v for k, v in data["legitimate"].items() if not k.startswith("_")}
    assert legit == set(EXCUSED), (
        f"an excused gate is not a decision this file records: {sorted(legit - set(EXCUSED))}; "
        f"and {sorted(set(EXCUSED) - legit)} are decided here but no longer excused. "
        "A gate moves between GUARDED and EXCUSED deliberately, in one commit, both lists."
    )
    for name in sorted(legit):
        assert len(reasons[name].split()) >= 15, (
            f"{name} is excused with no reason; an excuse without a reason is a permanent "
            "permission, which is what this file is for"
        )
