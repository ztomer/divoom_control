"""The web UI's JavaScript syntax gate must be able to FAIL.

P1.14. A stray backtick inside a template literal in
`divoom_gui/web_ui/templates_settings.js` broke the whole Settings tab, and
nothing in this repo's gates noticed: the browser suites load the page, but a
file the page loads and nothing calls is not exercised by any of them.

So `tools/check_js_syntax.py` is a GATE, and an unverified gate is the defect
it was written to close. These tests prove it bites, in the shape the failure
actually had -- and they prove it in BOTH readers, because the pure-Python
reader is the one that runs on a machine with no node, and a fallback nobody
has ever seen fail is a fallback nobody can trust.

The accept direction is proved too: a checker that always failed would be
just as useless as one that always passed.

WHAT IS ASSERTED, and why each one is here:

  * the historical defect -- a stray backtick inside a template literal --
    fails the node reader AND the lexical reader;
  * a plain grammar error (`const x = ;`) fails the node reader and NOT the
    lexical one. That asymmetry is the documented scope of the fallback, and
    a test that hid it would be a test that let the next reader believe the
    fallback is a parser;
  * the real tree is green;
  * an empty scope is red, so a renamed directory cannot make the gate
    vacuously pass.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "tools" / "check_js_syntax.py"
WEB_UI = REPO_ROOT / "divoom_gui" / "web_ui"

sys.path.insert(0, str(REPO_ROOT / "tools"))

from _js_lex import scan  # noqa: E402


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the REAL checker against a directory, unmodified."""
    return subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )


def _planted_tree(tmp_path: Path, defect: str) -> Path:
    """A copy of the real web UI with one defect in one file."""
    root = tmp_path / "web_ui"
    shutil.copytree(WEB_UI, root)
    target = root / "templates_settings.js"
    source = target.read_text(encoding="utf-8")
    if defect == "stray-backtick":
        old = '<label class="form-label label-xs">Timeout (s)</label>'
        assert old in source, "the fixture moved; re-derive the planting"
        source = source.replace(
            old, '<label class="form-label label-xs">Timeout (s)`</label>', 1
        )
    elif defect == "grammar":
        source = source + "\nconst broken = ;\n"
    else:  # pragma: no cover - a typo in a test is not a product defect
        raise AssertionError(f"unknown defect {defect}")
    target.write_text(source, encoding="utf-8")
    return root


def test_the_real_tree_is_green() -> None:
    result = _run_checker(WEB_UI)
    assert result.returncode == 0, (
        f"the real web UI must be green; the gate said:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_a_stray_backtick_in_a_template_literal_is_red(tmp_path: Path) -> None:
    """THE historical defect: a stray backtick inside a template literal.

    It ends the literal early, and everything after it is read as JavaScript
    -- which is how one character broke a whole tab.
    """
    root = _planted_tree(tmp_path, "stray-backtick")
    result = _run_checker(root)
    assert result.returncode != 0, (
        "a stray backtick inside a template literal must fail the gate; "
        f"it said:\n{result.stdout}\n{result.stderr}"
    )
    assert "templates_settings.js" in result.stdout + result.stderr


def test_the_stray_backtick_fails_the_lexical_reader_too(tmp_path: Path) -> None:
    """The fallback must catch the class the browser broke on.

    The pure-Python reader is what runs on a machine with no node, so it is
    the reader that has to catch the historical defect. A fallback that only
    the node reader can trip is a fallback with no coverage at all.
    """
    root = _planted_tree(tmp_path, "stray-backtick")
    problems = scan((root / "templates_settings.js").read_text(encoding="utf-8"))
    assert problems, "the lexical reader must find the stray backtick"


def test_a_grammar_error_is_red(tmp_path: Path) -> None:
    """A plain grammar error fails the gate -- the node reader's job."""
    root = _planted_tree(tmp_path, "grammar")
    result = _run_checker(root)
    assert result.returncode != 0, (
        "a JavaScript grammar error must fail the gate; it said:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_the_lexical_reader_is_a_lexer_and_not_a_parser(tmp_path: Path) -> None:
    """The fallback's scope, stated as a test so it cannot drift silently.

    `const x = ;` is a grammar error, and the pure-Python reader cannot see
    it -- only an engine builds the grammar. The node reader catches it (the
    test above). If this test ever fails, the fallback has become a parser,
    and its docstring is now understating what it does; that is worth
    knowing, but it must be a deliberate change, not a drift.
    """
    root = _planted_tree(tmp_path, "grammar")
    problems = scan((root / "templates_settings.js").read_text(encoding="utf-8"))
    assert not problems, (
        "the lexical reader is documented as a lexer, not a parser; if it now "
        "catches a grammar error, say so in the docstring and in the report"
    )


def test_an_empty_scope_is_red(tmp_path: Path) -> None:
    """A gate that inspected nothing has not passed, it has abstained.

    A renamed directory would otherwise make this gate report green over
    zero files, which is indistinguishable from green over all of them.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _run_checker(empty)
    assert result.returncode != 0, "an empty scope must be red"
