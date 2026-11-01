"""Both directions of tools/check_ui_budgets.py: a literal UI budget in a browser
suite is refused, and the two shapes where a short timeout IS the assertion pass.

The gate exists because 44 literal budgets survived a hand sweep, and one of them
(`timeout=2000` on a tab click) refused a pre-push at host load on 2026-10-31.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

gate = pytest.importorskip("check_ui_budgets")

HEADER = "from playwright.async_api import async_playwright\n"


def test_a_literal_budget_on_a_click_is_refused():
    src = HEADER + "async def t(page):\n    await page.click('#tab', timeout=2000)\n"
    assert gate.literal_budgets(src) == [3]


def test_a_literal_budget_on_the_house_wait_is_refused():
    src = HEADER + "async def t(page):\n    await wait_js(page,\n        '() => 1', timeout=4000)\n"
    assert gate.literal_budgets(src) == [3]


def test_a_named_budget_and_no_budget_pass():
    src = HEADER + (
        "async def t(page):\n"
        "    await page.click('#tab')\n"
        "    await wait_js(page, '() => 1', timeout=UI_TIMEOUT_MS)\n"
    )
    assert gate.literal_budgets(src) == []


def test_a_wait_for_absence_keeps_its_short_timeout():
    src = HEADER + "async def t(page):\n    await page.wait_for_selector('#x', state='hidden', timeout=300)\n"
    assert gate.literal_budgets(src) == []


def test_a_wait_that_must_time_out_keeps_its_short_timeout():
    src = HEADER + (
        "async def t(page):\n"
        "    with pytest.raises(MainWorldTimeout):\n"
        "        await wait_js(page, '() => window.NEVER', timeout=300)\n"
        "    await wait_js(page, '() => 1', timeout=300)\n"
    )
    assert gate.literal_budgets(src) == [5], "only the wait OUTSIDE pytest.raises is a budget"


def test_asyncio_wait_for_is_no_ui_wait():
    src = HEADER + "async def t(q):\n    await asyncio.wait_for(q.get(), timeout=2)\n"
    assert gate.literal_budgets(src) == []


def test_a_module_that_drives_no_page_is_out_of_scope(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sub.py").write_text("def t(sub):\n    sub.wait_for(lambda e: e, timeout=3)\n")
    (tmp_path / "tests" / "test_page.py").write_text(HEADER + "def t(page):\n    page.click('#a', timeout=5)\n")
    scanned, found = gate.census(tmp_path / "tests")
    assert scanned == 1
    assert found == {"tests/test_page.py": [3]}


def test_the_repo_holds_no_literal_ui_budget():
    r = subprocess.run([sys.executable, "tools/check_ui_budgets.py"], cwd=REPO, check=False,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
