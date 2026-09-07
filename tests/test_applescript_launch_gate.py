"""Regression tests for tools/check_applescript_launch.py.

The gate exists because `tell application "Python" to activate` in
`gui_main.main()` asked LaunchServices to resolve the NAME "Python" and launch
whatever answered to it. On 2026-09-07 that was TeX Live Utility's embedded
Python 3.9.10 app bundle, which Gatekeeper app-translocated into $TMPDIR --
breaking its `@rpath/Versions/3.9/Python` and producing four dyld crash reports,
while the window it meant to focus never moved.

Both directions are pinned: the gate must bite on the exact line that shipped,
and must stay quiet on the two forms that cannot launch anything (System Events,
and a tell guarded by `is running`). It must also ignore prose -- it failed on
its own subject matter the first time it was run, matching a docstring in
`divoom_lib/utils/media_players.py` that merely quotes `tell application "..."`.

check-applescript-launch: fixtures
    This file is the gate's calibration set, so it holds real violating source
    on purpose. The marker is honoured only under tests/ -- shipped code has no
    opt-out -- and this is the only file in the repo that carries it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

gate = pytest.importorskip("check_applescript_launch")


# ---------------------------------------------------------------- calibration

def test_the_exact_shipped_line_is_caught():
    """The instrument must produce the failing answer on the real defect."""
    bad = gate.scan_text(
        'subprocess.run(["osascript", "-e", \'tell application "Python" to activate\'])\n',
        ".py",
    )
    assert bad == ["Python"]


def test_bundle_id_form_is_caught():
    bad = gate.scan_text('s = \'tell application id "org.python.python" to activate\'\n', ".py")
    assert bad == ["org.python.python"]


def test_shell_script_is_caught():
    bad = gate.scan_text('osascript -e \'tell application "Music" to play\'\n', ".sh")
    assert bad == ["Music"]


def test_rust_is_caught():
    bad = gate.scan_text('let s = r#"tell application "Finder" to activate"#;\n', ".rs")
    assert bad == ["Finder"]


# ------------------------------------------------------------- the safe forms

def test_system_events_is_permitted():
    """Addressing by unix id can only front an existing process."""
    assert gate.scan_text(
        'script = (\n'
        '    \'tell application "System Events"\\n\'\n'
        '    \'    set procs to (every process whose unix id is 42)\\n\'\n'
        '    \'end tell\'\n'
        ')\n',
        ".py",
    ) == []


def test_is_running_guard_is_permitted():
    """The divoom_gui/permissions.py shape: never launches Music or Spotify."""
    assert gate.scan_text(
        'script = (\n'
        '    f\'if application "{app}" is running then\\n\'\n'
        '    f\'    tell application "Music" to get player state\\n\'\n'
        '    \'end if\'\n'
        ')\n'
        'guard = \'application "Music" is running\'\n',
        ".py",
    ) == []


def test_guard_for_a_different_app_does_not_excuse_it():
    """A guard is per app name, not a blanket amnesty for the file."""
    bad = gate.scan_text(
        'a = \'application "Music" is running\'\n'
        'b = \'tell application "Spotify" to pause\'\n',
        ".py",
    )
    assert bad == ["Spotify"]


# ------------------------------------------------------- prose is not code

def test_python_docstring_is_not_a_violation():
    assert gate.scan_text('"""Uses `tell application "Python" to activate`."""\n', ".py") == []


def test_attribute_docstring_is_not_a_violation():
    """The exact shape that reddened the gate's own first run."""
    assert gate.scan_text(
        'class P:\n'
        '    name: str\n'
        '    """The macOS name used in `tell application "..."`."""\n',
        ".py",
    ) == []


def test_python_comment_is_not_a_violation():
    assert gate.scan_text('# once ran tell application "Python" to activate\nx = 1\n', ".py") == []


def test_rust_comment_is_not_a_violation():
    assert gate.scan_text('// historical: tell application "Python" to activate\nfn f() {}\n', ".rs") == []


def test_shell_comment_is_not_a_violation():
    assert gate.scan_text('# tell application "Python" to activate\necho hi\n', ".sh") == []


def test_unparseable_python_is_skipped_not_crashed():
    assert gate.scan_text("def (:\n", ".py") == []


# --------------------------------------------- f-strings and computed names

def test_fstring_fragments_do_not_glue_into_a_false_positive():
    """The gate failed on ITSELF this way.

    `f'{rel}: tell application "{name}" (unguarded)'` reaches the AST as the
    fragments `: tell application "` and `" (unguarded)`. Joining every literal
    in the file made those adjacent, reading as a tell of an app named newline.
    A concrete name must be found inside one literal.
    """
    src = 'x = f"{rel}: tell application \\"{name}\\" (unguarded)"\n'
    assert gate.scan_text(src, ".py") == []


def test_a_computed_app_name_is_a_documented_blind_spot():
    """Pinned as a LIMIT, not as a capability.

    A first cut flagged any fragment ending at the open quote, and could not
    distinguish AppleScript from a log line -- the gate's own diagnostic
    tripped it. That rule was removed. If someone re-adds computed-name
    detection, this test should change deliberately, not silently.

    The one dynamic caller in the repo (divoom_gui/permissions.py) is covered
    by tests/test_permissions.py, which asserts it never launches a player.
    """
    src = 's = f\'tell application "{app}" to activate\'\n'
    assert gate.scan_text(src, ".py") == []


# ---------------------------------------------------------------- exemption

def test_marker_exempts_a_tests_file():
    assert gate.is_exempt("tests/test_applescript_launch_gate.py", gate.FIXTURE_MARKER)


def test_marker_does_not_exempt_shipped_code():
    """The rug check: a module cannot wave itself through with a comment."""
    for rel in ("divoom_gui/gui_main.py", "tools/x.py", "scripts/x.sh",
                "divoomd/src/main.rs", "nottests/x.py"):
        assert not gate.is_exempt(rel, gate.FIXTURE_MARKER), rel


def test_a_tests_file_without_the_marker_is_still_policed():
    assert not gate.is_exempt("tests/test_other.py", "no marker here")


def test_this_file_is_the_only_marked_file():
    """If a second file ever claims the exemption, that is a decision to see."""
    marked = [
        p.relative_to(REPO).as_posix()
        for p in REPO.rglob("*.py")
        if ".venv" not in p.parts and "target" not in p.parts
        and gate.FIXTURE_MARKER in p.read_text(errors="replace")
        and p.name != "check_applescript_launch.py"
    ]
    assert marked == ["tests/test_applescript_launch_gate.py"], marked


# ------------------------------------------------------------------ live tree

def test_gate_refuses_to_pass_over_an_empty_scope(tmp_path):
    """Inspecting nothing is abstaining, not passing -- a rename would otherwise
    retire this gate in silence. `--staged` is exempt: a commit touching no
    .py/.rs/.sh really does have an empty scope."""
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    (tmp_path / "tools").mkdir()
    for name in ("check_applescript_launch.py", "_srcscan.py"):
        (tmp_path / "tools" / name).write_bytes((REPO / "tools" / name).read_bytes())
    gate_py = "tools/check_applescript_launch.py"

    full = subprocess.run([sys.executable, gate_py], cwd=tmp_path, capture_output=True, text=True)
    assert full.returncode == 1, full.stdout
    assert "0 files" in full.stdout

    staged = subprocess.run([sys.executable, gate_py, "--staged"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert staged.returncode == 0, staged.stdout


def test_gate_passes_on_current_tree():
    r = subprocess.run(
        [sys.executable, "tools/check_applescript_launch.py"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
