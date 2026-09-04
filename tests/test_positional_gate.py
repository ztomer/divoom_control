"""Regression tests for tools/check_positional_args.py (R67/C7 gate).

The gate once passed on APFS and failed on ext4 for the SAME commit, because
two defects cancelled out on one filesystem. Both are pinned here.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

check_positional_args = pytest.importorskip("check_positional_args")
from _srcscan import strip_rust_comments  # noqa: E402


def test_annotated_signature_wins_over_bare_duplicate():
    """`show_light` is defined twice; the ANNOTATED definition is authority.

    display/__init__.py annotates `color: str`; display/light.py does not.
    Selection used to be first-wins over an unsorted rglob, so the winner —
    and the gate's verdict — depended on filesystem order.
    """
    params = check_positional_args.python_signatures()["show_light"]
    assert params[0] == ("color", "str")


def test_signature_selection_is_deterministic():
    """Repeated runs agree. A gate that flips verdicts cannot be trusted."""
    runs = [check_positional_args.python_signatures() for _ in range(3)]
    assert all(r == runs[0] for r in runs)


def test_comment_quoting_code_is_not_scanned_as_code():
    """A comment that quotes `args.get(1)` must not read as a live call."""
    src = '// brightness used to read `args.get(1)` — the COMPACTED list\nlet x = 1;\n'
    out = strip_rust_comments(src)
    assert "args.get(1)" not in out
    assert "let x = 1;" in out


def test_stripping_preserves_offsets_and_lines():
    """Callers index back into the text, so length and newlines must survive."""
    src = "a /* {{{ */ b\n// tail {\nc\n"
    out = strip_rust_comments(src)
    assert len(out) == len(src)
    assert out.count("\n") == src.count("\n")
    assert "{" not in out  # braces in comments cannot corrupt depth counting


def test_string_literals_survive_stripping():
    """Arm names the gate keys on are string literals, not comments."""
    assert '"display.show_light"' in strip_rust_comments('"display.show_light" => {}')


def test_gate_passes_on_current_tree():
    r = subprocess.run([sys.executable, "tools/check_positional_args.py"],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
