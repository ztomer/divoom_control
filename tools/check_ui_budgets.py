#!/usr/bin/env python3
"""check_ui_budgets.py — a browser test's wait carries the house's budget, not its own.

A wait in these suites asserts that a condition EVENTUALLY holds; none of them
measures how fast the UI is. So a literal budget at a call site cannot catch a
defect the house budget (`tests/support/browser.UI_TIMEOUT_MS`, 60s, measured
under load) misses: it can only turn a busy machine into a red test that reads
like a regression. The suites were swept onto the house budget on 2026-09-12,
and the seam (`tests/support/navigation_budget.py`) gives every page that budget
as its default, so a call that names no timeout is already right.

The sweep was by hand, so it left survivors: on 2026-10-31 a pre-push run of
this repo was refused by `Page.click: Timeout 2000ms exceeded` on a Gallery tab
that was visible, enabled and stable, at host load. 44 literal budgets were
left across 15 browser suites (2000 to 15000 ms), and nothing stopped a 45th.
This gate does.

Flagged: in a module that drives a page, a Playwright action or wait (or the
house's own `wait_js` / `wait_toast`) whose `timeout=` is a numeric literal.
Exempt by SHAPE, never by list, the two places where a short timeout IS the
assertion: a wait for absence (`state="hidden"` / `state="detached"`), and a
wait inside `pytest.raises(...)`, which asserts that the wait times out.
"""

from __future__ import annotations

import ast
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402
from _empty_scope import scope_is_empty  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"

#: Calls whose `timeout=` is a UI budget: Playwright's page/locator actions and
#: waits, plus the house helpers in tests/support/browser.py.
WAITS = frozenset(
    {
        "check",
        "click",
        "dblclick",
        "fill",
        "focus",
        "goto",
        "hover",
        "press",
        "select_option",
        "set_checked",
        "tap",
        "type",
        "uncheck",
        "wait_for",
        "wait_for_function",
        "wait_for_load_state",
        "wait_for_selector",
        "wait_for_url",
        "wait_js",
        "wait_toast",
    }
)
ABSENCE = frozenset({"hidden", "detached"})


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_asyncio(func: ast.expr) -> bool:
    """`asyncio.wait_for(..., timeout=2)` bounds a coroutine in seconds; it is no UI wait."""
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "asyncio"


def is_browser_suite(source: str) -> bool:
    """A module that drives a page: it imports playwright or the house's browser seam.

    The scope is the browser suites, because the names a UI wait goes by (`wait_for`,
    `click`) are also the names of a daemon subscription's wait or a socket helper's."""
    return "playwright" in source or "tests.support.browser" in source or "tests.support import browser" in source


def _expected_timeouts(tree: ast.AST) -> list[tuple[int, int]]:
    """Line spans of every `with pytest.raises(...)` block: a wait there must time out."""
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(
            isinstance(item.context_expr, ast.Call) and _name(item.context_expr.func) == "raises" for item in node.items
        ):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def literal_budgets(source: str) -> list[int]:
    """Line numbers of every wait in `source` that names its own numeric budget."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # a test's own regex escapes are not ours
        tree = ast.parse(source)
    expected = _expected_timeouts(tree)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _name(node.func) not in WAITS or _is_asyncio(node.func):
            continue
        timeout = _keyword(node, "timeout")
        if not (isinstance(timeout, ast.Constant) and isinstance(timeout.value, (int, float))):
            continue
        state = _keyword(node, "state")
        if isinstance(state, ast.Constant) and state.value in ABSENCE:
            continue
        if any(start <= node.lineno <= end for start, end in expected):
            continue
        lines.append(node.lineno)
    return sorted(lines)


def census(tests: Path = TESTS) -> tuple[int, dict[str, list[int]]]:
    """(browser suites scanned, {repo-relative path: [lines]})."""
    scanned, found = 0, {}
    for path in sorted(p for p in tests.rglob("*.py") if "__pycache__" not in p.parts):
        source = path.read_text(encoding="utf-8")
        if not is_browser_suite(source):
            continue
        scanned += 1
        lines = literal_budgets(source)
        if lines:
            found[path.relative_to(tests.parent).as_posix()] = lines
    return scanned, found


def main() -> int:
    scanned, found = census()
    if scope_is_empty("ui-budgets", scanned, unit="browser suites"):
        return 1
    for path, lines in found.items():
        err(
            f"[ui-budgets] {path}: a literal UI budget at line(s) {', '.join(map(str, lines))} -- "
            f"drop the `timeout=` (the page default and wait_js's are the house budget)"
        )
    if found:
        return 1
    info(f"[ui-budgets] {scanned} browser suite(s) scanned")
    ok("[ui-budgets] every browser wait carries the house budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
