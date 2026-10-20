"""The tooling must not use a name it never defines — and must say so.

`scripts/hw_smoke.py` and `scripts/hw_walk_modes.py` printed their results
with the house TUI's module-private colour names (`_GRAY`, `_DIM`, `_BOLD`,
`_RED`, `_RESET`). Those live inside `tui/lib.py` and exist nowhere else, so
every code path that PRINTED a result raised NameError. The scan worked — four
panels answered — and the reporting of that fact died:

    ✓ 4 device(s):
    ✗ scan failed: NameError: name '_GRAY' is not defined

Worse, the raise was caught and reported as a warning, so the script exited 0:
a run that had found four panels was announced as a clean run whose reporting
had failed. `tools/check_scripts.py` was green throughout, because it only
checked that scripts PARSE, and a file with a NameError in it parses
perfectly.

These tests pin the three things that must not regress:
  1. the pass finds an undefined name (and finds the right one),
  2. the gate is RED on a file that has one — the pre-fix file, verbatim,
  3. the pass is not a one-trick pony: a SECOND, different undefined name is
     caught too, and a name that IS defined is not reported.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from _undefined_names import undefined_names  # noqa: E402

# The pre-fix hw_smoke.py, verbatim, reduced to the shape that broke: a name
# that is used and never defined. Keeping it as a FIXTURE rather than as a
# git dependency means this test still means something in a shallow clone.
PRE_FIX_SNIPPET = """
import json
from tui.lib import info, step, ok, err, warn


def discover(c, timeout):
    ok("4 device(s):")
    for d in c:
        step(f"{d['name']}  {_GRAY}{d['address']}{_RESET}")
    return c
"""


def test_the_pass_finds_a_name_that_is_used_and_never_defined():
    problems = undefined_names(PRE_FIX_SNIPPET)
    names = {name for name, _ in problems}
    assert "_GRAY" in names, problems
    assert "_RESET" in names, problems


def test_the_pass_reports_the_line_the_name_is_used_on():
    problems = undefined_names(PRE_FIX_SNIPPET)
    expected = {i for i, line in enumerate(PRE_FIX_SNIPPET.splitlines(), 1)
                if "_GRAY" in line}
    lines = {lineno for name, lineno in problems if name == "_GRAY"}
    assert lines == expected, (problems, expected)


def test_a_second_different_undefined_name_is_also_caught():
    """The pass must not be a lookup table for the one bug it was written for."""
    source = PRE_FIX_SNIPPET + "\n\nprint(calibration_probe_total)\n"
    names = {name for name, _ in undefined_names(source)}
    assert "calibration_probe_total" in names, names
    assert "_GRAY" in names, names


def test_names_that_ARE_defined_are_not_reported():
    source = """
import os
from pathlib import Path

CONSTANT = 1


def f(argument):
    local = argument + CONSTANT
    with open("x") as handle:
        local += len(handle.read())
    return [item for item in range(local) if item]
"""
    assert undefined_names(source) == []


def test_a_name_bound_in_an_except_block_is_defined():
    """`except` is a block, not a scope: a name bound in it is bound."""
    source = """
def f():
    try:
        pass
    except ValueError as exc:
        message = str(exc)
    return message
"""
    assert undefined_names(source) == []


def test_the_gate_is_red_on_a_file_with_an_undefined_name(tmp_path):
    """The gate must FAIL, not warn, on a script that would raise at runtime."""
    planted = tmp_path / "planted_script.py"
    planted.write_text("def f():\n    return _GRAY\n", encoding="utf-8")

    failures: list[str] = []
    import check_scripts

    # The gate's own check, pointed at the planted file.
    original = check_scripts.tooling_python_files
    try:
        check_scripts.tooling_python_files = lambda: [planted]
        check_scripts.check_undefined_names(failures)
    finally:
        check_scripts.tooling_python_files = original

    assert failures, "the gate said nothing about a file that would NameError"
    assert "_GRAY" in failures[0], failures


def test_the_gate_is_green_on_the_real_tooling():
    """The tooling as it stands must pass its own gate — no planted names."""
    failures: list[str] = []
    import check_scripts

    check_scripts.check_undefined_names(failures)
    assert not failures, failures


def test_the_two_scripts_no_longer_reach_for_the_tuis_private_colours():
    """The house rule: scripts use the PUBLIC helpers, never raw colour names.

    `tui/lib.py` exports `_C_GRAY`, `_C_DIM`, `_C_BOLD`, `_C_RED`, `_C_RESET` —
    module-private. A script that names `_GRAY` is naming a name that does not
    exist, which is what the pass above catches; this test says so in the
    words of the rule rather than in the words of the tool.
    """
    banned = ("_GRAY", "_DIM", "_BOLD", "_RED", "_RESET", "_GREEN", "_YELLOW")
    for name in ("hw_smoke.py", "hw_walk_modes.py"):
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        assert not (used & set(banned)), f"{name} uses {used & set(banned)}"


def test_the_gate_runs_and_is_green_on_this_tree():
    """The gate itself must still run — a check that cannot fail is not a gate."""
    r = subprocess.run([sys.executable, str(REPO / "tools" / "check_scripts.py")],
                       capture_output=True, text=True, cwd=str(REPO),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
