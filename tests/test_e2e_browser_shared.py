"""The browser suites share ONE browser per session; a test gets a fresh context (P1.21).

Before this, 57 of the 58 browser suites launched a browser per test (about
2.2 s each before any page; the serial browser step took 6 min 50 s). The seam
(``tests/support/browser.py`` ``launch`` / ``launch_sync``) now hands out a
handle on the session's browser (``tests/support/browser_shared.py``). These
tests hold the three things that keep that true:

* a handle is isolated: what one test stored, opened or left open is not
  there for the next;
* the browser is launched once, however many handles are taken;
* no suite takes a browser by any other road -- the class ("a launch per
  test") cannot come back by a new suite calling the launcher itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support import browser as B
from tests.support import browser_shared as S
from tests.support.browser import launch

TESTS = Path(__file__).resolve().parent
PAGE = f"file://{TESTS.parent / 'divoom_gui' / 'web_ui' / 'index.html'}"
SELF = Path(__file__).name


async def test_a_handle_starts_with_nothing_the_last_one_left():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        first = await launch(p)
        page = await first.new_page()
        await page.goto(PAGE)
        await page.evaluate("localStorage.setItem('left', 'behind')")
        # The test "forgot" first.close(): the next launch must still hand over a clean browser.
        second = await launch(p)
        assert second._host is first._host, "a second launch started another browser"
        fresh = await second.new_page()
        await fresh.goto(PAGE)
        assert await fresh.evaluate("localStorage.getItem('left')") is None
        assert page.is_closed(), "the previous handle's page outlived its test"
        assert len(second._host.browser.contexts) == 1
        await second.close()
        assert second._host.browser.contexts == []


async def test_close_closes_the_handles_contexts_and_not_the_browser():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        handle = await launch(p)
        context = await handle.new_context()
        page = await context.new_page()
        await handle.close()
        assert page.is_closed()
        assert handle._host.browser.is_connected()


def test_the_browser_suites_run_on_the_session_loop(request):
    """The shared browser belongs to one event loop; every async test of a
    module that gets its browser from the seam must be on it."""
    import inspect

    items = request.session.items
    browser_async = [i for i in items if inspect.iscoroutinefunction(getattr(i, "obj", None))
                     and S.runs_on_session_loop(i.module)]
    if not browser_async:
        pytest.skip("no browser suite is part of this run")
    off = [i.nodeid for i in browser_async
           if (i.get_closest_marker("asyncio") is None
               or i.get_closest_marker("asyncio").kwargs.get("loop_scope") != "session")]
    assert not off, f"browser tests off the session loop: {off[:5]}"


def test_a_launch_from_another_loop_is_refused_not_quietly_a_second_browser():
    import asyncio

    from playwright.async_api import async_playwright

    class _Elsewhere:  # a started host whose loop is alive and is not ours
        loop = asyncio.new_event_loop()

    async def ask():
        async with async_playwright() as p:
            return await launch(p)

    saved = S._async_host
    S._async_host = _Elsewhere()
    try:
        with pytest.raises(S.SharedBrowserWrongLoop):
            asyncio.run(ask())
    finally:
        S._async_host = saved
        _Elsewhere.loop.close()


# ── the class gate: no suite takes a browser except through the seam ─────────

def _suites():
    return [p for p in sorted(TESTS.glob("test_*.py")) if p.name != SELF]


def test_no_suite_launches_a_browser_per_test():
    """The launchers under the seam are named by no suite. A direct engine launch
    is already banned by ``test_e2e_browser_guard``; this bans the helpers that
    would launch a browser without the shared one."""
    banned = ("launch_async", "shared_browser", "browser_shared")
    offenders = []
    for path in _suites():
        text = path.read_text(encoding="utf-8")
        for name in banned:
            if re.search(rf"\b{name}\b", text):
                if path.name in ("test_browser_launch_outcome.py", "test_e2e_browser_guard.py", "test_e2e_browser_reaped.py"):
                    continue  # they test the launch helpers themselves, with fakes
                offenders.append(f"{path.name}: {name}")
    assert not offenders, "launch through tests.support.browser.launch/launch_sync: " + ", ".join(offenders)


def test_every_playwright_suite_gets_its_browser_from_the_seam():
    """A module that drives the async API imports the seam, so the rule that
    puts it on the session loop (``runs_on_session_loop``) sees it. (The
    generator in ``test_ui_budget_gate`` writes playwright code as text.)"""
    seam = re.compile(r"tests\.support(?:\.browser\b| import (?:[^\n]*\b)?browser\b)")
    for path in _suites():
        text = path.read_text(encoding="utf-8")
        if path.name == "test_ui_budget_gate.py":
            continue
        if "async_playwright" in text and not seam.search(text):
            pytest.fail(f"{path.name} drives playwright without tests.support.browser")
