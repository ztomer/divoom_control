"""Three-bucket reachability classification (R71 P1.0).

**Why the gate needed a third bucket.** It asked "does `web_ui/` mention this
name" and reported one number: 20 allowlisted. That conflates two states
needing OPPOSITE fixes -- a method reached only from Python does not belong on
the pywebview bridge surface and should MOVE, while a method reached from
nowhere should GO. One number is why all 20 sat undecided for a round.

**Why AST and not a text scan.** Two gates in this repo were reddened by their
own prose (`check_no_allow`, `check_positional_args`); source text cannot tell
an attribute from a comment quoting one. It cuts the other way too: a text scan
of `batch_sync_artwork` "finds" a caller in `gallery_sync.py` that is a
DOCSTRING, and the allowlist entry asserting "called from Python (gallery_sync)"
was written from exactly that false hit. The method has no production caller.

**The delegation trap, which the first version of this scanner fell into.**
`DivoomGuiAPI.probe_lan` is `return self.connection.probe_lan()`. That inner
attribute access is the method forwarding to its implementation, not a caller
of it -- but it is an `ast.Attribute` named `probe_lan` like any other. Counting
those reported 13 methods as Python-reached when the true figure was 4. The
instrument was confident, repeatable, and measuring the wrong thing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

gate = pytest.importorskip("check_gui_api_reachable")


def _mod(tmp_path: Path, name: str, body: str) -> tuple[Path, ...]:
    pkg = tmp_path / "pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / f"{name}.py").write_text(body)
    return (pkg,)


def test_delegation_is_not_a_caller(tmp_path):
    """The trap: a method forwarding to its own implementation."""
    roots = _mod(tmp_path, "api", (
        "class Api:\n"
        "    def probe_lan(self):\n"
        "        return self.connection.probe_lan()\n"
    ))
    assert gate.python_callers({"probe_lan"}, roots)["probe_lan"] == []


def test_a_real_cross_module_call_is_found(tmp_path):
    roots = _mod(tmp_path, "caller", (
        "def go(api):\n"
        "    return api.probe_lan()\n"
    ))
    hits = gate.python_callers({"probe_lan"}, roots)["probe_lan"]
    assert len(hits) == 1 and hits[0].endswith(":2")


def test_docstring_mention_is_not_a_caller(tmp_path):
    """The false hit that produced a wrong ALLOWLIST reason.

    `batch_sync_artwork`'s entry says "called from Python (gallery_sync)". The
    only thing in gallery_sync.py is a docstring saying the name.
    """
    roots = _mod(tmp_path, "gallery", (
        "def helper():\n"
        '    """Core of batch_sync_artwork that keeps the failure REASON."""\n'
        "    return None\n"
    ))
    assert gate.python_callers({"batch_sync_artwork"}, roots)["batch_sync_artwork"] == []


def test_comment_mention_is_not_a_caller(tmp_path):
    roots = _mod(tmp_path, "c", "# calls api.probe_lan() eventually\nx = 1\n")
    assert gate.python_callers({"probe_lan"}, roots)["probe_lan"] == []


def test_recursive_only_method_counts_as_dead(tmp_path):
    """Excluded deliberately: calling yourself is not being reached."""
    roots = _mod(tmp_path, "r", (
        "class A:\n"
        "    def loop(self):\n"
        "        return self.loop()\n"
    ))
    assert gate.python_callers({"loop"}, roots)["loop"] == []


def test_unparseable_file_does_not_abort_the_scan(tmp_path):
    """One bad file must not silently truncate the whole classification."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "broken.py").write_text("def (((\n")
    (pkg / "good.py").write_text("def go(api):\n    return api.probe_lan()\n")
    assert len(gate.python_callers({"probe_lan"}, (pkg,))["probe_lan"]) == 1


def test_divoom_lib_is_outside_the_scanned_surface():
    """A reference-only module must not vouch for a live API method."""
    names = {p.name for p in gate.PY_SURFACE}
    assert "divoom_lib" not in names, (
        "divoom_lib is the protocol REFERENCE; counting a call from it would "
        "let obsolete code keep a bridge method alive"
    )
    assert names == {"divoom_gui", "divoom_client"}, names
