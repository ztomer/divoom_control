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
    "check_file_size.py",
    "check_gui_is_a_client.py",
    "check_no_allow.py",
    "check_positional_args.py",
    "check_scripts.py",
    "check_applescript_launch.py",
]


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
        [sys.executable, f"tools/{gate}"], cwd=REPO, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_camoufox_is_the_only_excused_gate():
    """The allowlist is a ratchet. `known_blind` must stay empty — the six gates
    that were blind were FIXED, not excused, and an entry here is how that
    would quietly reverse."""
    import json

    data = json.loads((REPO / "tools" / "empty_scope_allow.json").read_text())
    legit = {k for k in data["legitimate"] if not k.startswith("_")}
    blind = {k for k in data["known_blind"] if not k.startswith("_")}
    assert legit == {"check_camoufox_installed.py"}, legit
    assert blind == set(), f"a gate is excused instead of guarded: {blind}"
