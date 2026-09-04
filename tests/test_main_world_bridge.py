"""Tests for the main-world bridge in tests/support/browser.py.

From camoufox build 152.0.4-beta.29 the browser runs page scripting in an
ISOLATED WORLD. The e2e suites read the app's own globals and install their
mocks before the app boots, so all of that had to be routed explicitly into the
page's main world. That routing is the thing most likely to rot silently: when
it breaks, every assertion reads `None` and 60 tests fail looking like feature
regressions rather than a browser change.

So the browser-backed test below asserts BOTH directions -- the bridge sees the
global AND the unbridged call does not. A test that only checked the bridge
would keep passing on a browser where the bridge had become unnecessary, and
tell us nothing on the day it becomes insufficient again.
"""
from __future__ import annotations

import json

import pytest

from tests.support import browser as B

MAIN_WORLD_PAGE = (
    "data:text/html,<script>"
    "window.APP_GLOBAL = 'from-the-page';"
    "window.BOOT_ORDER = (window.BOOT_ORDER || []).concat('app');"
    "</script><div id='visible'>in the dom</div>"
)


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_main_world_prefixes():
    assert B.main_world("window.X") == "mw:window.X"


def test_main_world_is_idempotent():
    """Double-prefixing would send camoufox a script starting `mw:mw:`."""
    assert B.main_world(B.main_world("window.X")) == "mw:window.X"


def test_main_world_strips_leading_whitespace():
    """The suites pass triple-quoted scripts that open with a newline.

    Only LEADING whitespace matters -- the prefix has to be the first thing
    camoufox sees. Trailing whitespace is left alone; it is valid JS.
    """
    assert B.main_world("\n    () => 1\n") == "mw:() => 1\n"


def test_bootstrap_carries_the_source_as_a_js_literal():
    src = "window.__api = {push: () => 'ok'};"
    out = B.main_world_bootstrap(src)
    assert json.dumps(src) in out


def test_bootstrap_survives_quotes_and_script_tags():
    """A mock containing `</script>` must not break out of the injected node."""
    src = "window.q = \"a'b\\\"c</script>\";"
    out = B.main_world_bootstrap(src)
    # textContent, never innerHTML -- the payload is never parsed as HTML.
    assert "textContent" in out
    assert "innerHTML" not in out
    assert json.dumps(src) in out


def test_bootstrap_has_a_fallback_for_a_missing_documentelement():
    """document.documentElement may not exist yet at document_start."""
    out = B.main_world_bootstrap("window.x = 1;")
    assert "MutationObserver" in out


def test_timeout_message_names_the_condition():
    msg = B._timeout_message("() => window.ready\n   === true", 2000, None)
    assert "2000ms" in msg
    assert "() => window.ready === true" in msg, "whitespace should be collapsed"


def test_timeout_message_reports_the_last_error():
    msg = B._timeout_message("window.a.b", 500, ValueError("boom"))
    assert "ValueError" in msg and "boom" in msg


def test_timeout_message_truncates_a_huge_script():
    msg = B._timeout_message("x" * 500, 100, None)
    assert "..." in msg and len(msg) < 300


def test_main_world_timeout_is_an_assertion_error():
    """Suites and reporters treat a failed wait as a failed assertion."""
    assert issubclass(B.MainWorldTimeout, AssertionError)


# ── the real thing, against the real browser ──────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_reaches_the_main_world_and_plain_evaluate_does_not():
    """The load-bearing claim, asserted in both directions."""
    B.require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await B.launch(p)
        try:
            page = await b.new_page()
            await page.goto(MAIN_WORLD_PAGE)

            assert await B.eval_js(page, "() => window.APP_GLOBAL") == "from-the-page"

            # The isolated world shares the DOM but not the globals. If this
            # ever starts returning the value, the bridge has become
            # unnecessary -- which is worth knowing deliberately.
            assert await page.evaluate("() => window.APP_GLOBAL") is None
            assert await page.evaluate(
                "() => document.getElementById('visible').textContent"
            ) == "in the dom"
        finally:
            await b.close()


@pytest.mark.asyncio
async def test_init_script_runs_before_the_pages_own_scripts():
    """Mocks must be installed before the app reads them, not merely present."""
    B.require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await B.launch(p)
        try:
            page = await b.new_page()
            await B.add_init_js(
                page,
                "window.__api = {ok: true};"
                "window.BOOT_ORDER = (window.BOOT_ORDER || []).concat('mock');",
            )
            await page.goto(MAIN_WORLD_PAGE)

            assert await B.eval_js(page, "() => window.BOOT_ORDER") == ["mock", "app"]
            assert await B.eval_js(page, "() => window.__api.ok") is True
        finally:
            await b.close()


@pytest.mark.asyncio
async def test_wait_js_returns_once_the_condition_holds():
    B.require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await B.launch(p)
        try:
            page = await b.new_page()
            await page.goto(MAIN_WORLD_PAGE)
            await B.eval_js(page, "() => { setTimeout(() => { window.LATE = 7; }, 120); }")
            assert await B.wait_js(page, "() => window.LATE === 7") is True
        finally:
            await b.close()


@pytest.mark.asyncio
async def test_wait_js_times_out_with_the_condition_in_the_message():
    """A wait that cannot succeed must fail fast and say what it wanted."""
    B.require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await B.launch(p)
        try:
            page = await b.new_page()
            await page.goto(MAIN_WORLD_PAGE)
            with pytest.raises(B.MainWorldTimeout) as exc:
                await B.wait_js(page, "() => window.NEVER_SET", timeout=300)
            assert "window.NEVER_SET" in str(exc.value)
        finally:
            await b.close()
