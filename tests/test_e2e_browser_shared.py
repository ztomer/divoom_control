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


def _reaches_the_seam() -> set[str]:
    """Test modules that can reach the browser seam, by IMPORTS -- not by the
    text ``runs_on_session_loop`` judges, so the two can check each other. A
    module reaches it by importing ``tests.support.browser`` or anything that
    does (a support helper, another suite's helpers), transitively."""
    imports = re.compile(
        r"^\s*(?:from\s+tests\.(?:support\.)?(\w+)\s+import"
        r"|from\s+tests\.support\s+import\s+([\w, ]+)"
        r"|import\s+tests\.(?:support\.)?(\w+))", re.MULTILINE)
    deps: dict[str, set[str]] = {}
    for path in [*TESTS.glob("test_*.py"), *(TESTS / "support").glob("*.py")]:
        names: set[str] = set()
        for m in imports.finditer(path.read_text(encoding="utf-8")):
            if m.group(2):
                names |= {n.strip().split(" as ")[0] for n in m.group(2).split(",")}
            else:
                names.add(m.group(1) or m.group(3))
        deps[path.stem] = names
    reach = {"browser", "browser_shared"}
    grew = True
    while grew:
        grew = False
        for name, names in deps.items():
            if name not in reach and names & reach:
                reach.add(name)
                grew = True
    return {name for name in reach if name.startswith("test_")}


def test_every_module_that_reaches_the_seam_is_a_browser_suite():
    """The class gate under the session loop: every module that can get a
    browser through the seam -- directly or through a helper -- is one
    ``runs_on_session_loop`` (and scripts/browser_e2e.sh) picks."""
    import types

    reach = _reaches_the_seam()
    assert SELF.removesuffix(".py") in reach and len(reach) > 40, sorted(reach)
    missed = sorted(name for name in reach
                    if not S.runs_on_session_loop(types.SimpleNamespace(__file__=str(TESTS / f"{name}.py"))))
    assert not missed, f"reach the browser seam but are not judged browser suites: {missed}"


def test_the_browser_suites_run_on_the_session_loop(request):
    """The shared browser belongs to one event loop; every async test of a
    module that reaches the seam is marked onto it. The modules are picked by
    imports (``_reaches_the_seam``), never by the predicate under test."""
    import inspect

    reach = _reaches_the_seam()
    browser_async = [i for i in request.session.items if inspect.iscoroutinefunction(getattr(i, "obj", None))
                     and Path(i.module.__file__).stem in reach]
    mine = [i for i in browser_async if Path(i.module.__file__).name == SELF]
    assert mine or request.config.option.keyword or request.config.option.markexpr, (
        "this module's own async tests were collected, so the check cannot be empty")
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


def test_a_first_launch_off_the_session_loop_is_refused():
    """With no browser started yet, a launch from a loop that is not the session's
    must not start one there: that browser dies with its loop, and every later
    test would then start a new one, quietly (Argon on 24ab74e)."""
    import asyncio

    from playwright.async_api import async_playwright

    async def ask():
        async with async_playwright() as p:
            await launch(p)
            await S.shutdown_async()  # reached only when the launch was wrongly allowed

    saved = S._async_host
    S._async_host = None
    try:
        with pytest.raises(S.SharedBrowserWrongLoop):
            asyncio.run(ask())
    finally:
        S._async_host = saved


async def test_a_replaced_browser_has_its_driver_stopped():
    """A browser that died is replaced on the next launch; the replaced host's
    playwright driver (a node process) must stop with it, or every crash leaks one."""
    import asyncio

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        first = await launch(p)
        old = first._host
        driver = old.playwright._impl_obj._connection._transport._proc
        await old.browser.close()  # what a crash looks like to the host: disconnected
        second = await launch(p)
        assert second._host is not old
        for _ in range(50):
            if driver.returncode is not None:
                break
            await asyncio.sleep(0.1)
        assert driver.returncode is not None, f"the replaced host's driver (pid {driver.pid}) is still running"
        await second.close()


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
