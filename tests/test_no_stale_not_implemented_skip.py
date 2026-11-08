"""A skip that says "not implemented" must be TRUE: the method it names is missing.

Fifteen tests in ``examples/tests/test_divoom.py`` sat skipped as
"Method X not implemented in Divoom class" while every X existed on ``Divoom``;
the real defect was a fixture that patched the wrong class (D.SKIPS). A skip
reason is a claim, so this gate checks it: for every ``pytest.mark.skip`` /
``pytest.skip`` / ``skipif`` across the tree whose reason says "not implemented",
the reason must name ``Method <name> ... in <Class> class`` and ``<Class>`` must
NOT define ``<name>``. A stale skip goes red; an unparseable one goes red too,
because a claim nobody can check is how the fifteen survived.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("tests", "examples", "divoom_lib", "gui", "scripts")
NOT_IMPL = re.compile(r"not\s+(?:yet\s+)?implemented", re.IGNORECASE)
NAMED = re.compile(r"Method\s+(\w+)\s+not\s+(?:yet\s+)?implemented\s+in\s+(\w+)\s+class", re.IGNORECASE)


def _py_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if base.is_dir():
            yield from (p for p in base.rglob("*.py") if "node_modules" not in p.parts)


def _is_skip_call(node: ast.Call) -> bool:
    f = node.func
    return isinstance(f, ast.Attribute) and f.attr in ("skip", "skipif", "skipTest")


def _reasons(node: ast.Call):
    for arg in [*node.args, *(k.value for k in node.keywords)]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.value


def skip_claims(files):
    """(path, line, reason) for every skip reason claiming something is not implemented."""
    out = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_skip_call(node):
                out.extend((path, node.lineno, r) for r in _reasons(node) if NOT_IMPL.search(r))
    return out


def class_methods(files):
    """{class name: set of names defined in its body} over the scanned tree."""
    found: dict[str, set[str]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names = found.setdefault(node.name, set())
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.add(item.name)
    return found


def stale_skips(claims, methods):
    bad = []
    for path, line, reason in claims:
        m = NAMED.search(reason)
        where = f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}:{line}"
        if not m:
            bad.append(f"{where}: unverifiable 'not implemented' skip: {reason!r}")
        elif m.group(1) in methods.get(m.group(2), set()):
            bad.append(f"{where}: {m.group(2)}.{m.group(1)} exists; the skip is stale")
    return bad


def test_no_skip_claims_a_present_method_is_missing():
    files = list(_py_files())
    assert files, "scanned zero files: the gate would pass vacuously"
    assert not stale_skips(skip_claims(files), class_methods(files))


def test_the_gate_goes_red_on_a_stale_skip(tmp_path):
    """Calibration: a skip naming a method its class defines is caught."""
    src = tmp_path / "t.py"
    src.write_text(
        "import pytest\n"
        "class Divoom:\n"
        "    def present(self): ...\n"
        "@pytest.mark.skip(reason='Method present not implemented in Divoom class')\n"
        "def test_a(): ...\n"
        "@pytest.mark.skip(reason='Method absent not implemented in Divoom class')\n"
        "def test_b(): ...\n"
        "def test_c():\n"
        "    pytest.skip('feature not implemented')\n"
    )
    bad = stale_skips(skip_claims([src]), class_methods([src]))
    assert len(bad) == 2
    assert "Divoom.present exists" in bad[0]
    assert "unverifiable" in bad[1]
