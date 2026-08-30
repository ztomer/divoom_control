"""The one place the GUI e2e suites get a browser.

Before R66 each of the 15 e2e modules called
``p.chromium.launch(headless=True)`` itself and guarded with
``pytest.importorskip("playwright.async_api")``. Two problems, both fixed here:

1. **The guard did not guard.** ``importorskip`` only checks that the Python
   MODULE imports. It says nothing about the browser BINARY, so a machine with
   the playwright package but no downloaded browser did not skip -- it raised
   ``BrowserType.launch: Executable doesn't exist`` and produced **69 failures**
   that read exactly like real regressions (measured 2026-08-17 on a clean
   checkout). ``require_browser()`` probes the binary, so a missing browser
   skips like it always claimed to.

2. **The engine was copy-pasted 17 times.** Swapping it meant touching every
   file, which is why it never happened. It is now one function.

Version: CI pins the **browser build** to ``official/stable/152.0.4-beta.29``
(the current latest on that channel) via ``camoufox set``, with the pip package
at 0.5.5. Pinning the package is NOT sufficient on its own -- camoufox accepts
any build in ``[alpha.1, 1)``, so a bare ``camoufox fetch`` takes the newest one
regardless, and the build is the half that decides whether the suite passes.

**The isolated world.** From build 152.0.4-beta.29 (2026-08-20) page scripting
runs in an ISOLATED WORLD, so main-world globals the app defines --
``window.DivoomState`` and every render function -- read as ``undefined``. The
page itself is fine: probed on 2026-08-30, all 29 scripts fetch 200, the DOM
builds, and there is not a single console or page error. Only the *view*
changed, which is why that upgrade turned CI red on 2026-08-25 with 60 failures
and no code change.

Three separate holes had to be closed, and only the first was known:

1. ``page.evaluate`` reaches the main world again through an ``mw:`` script
   prefix, enabled by ``main_world_eval=True`` at launch. BOTH are required:
   the flag alone does not restore the old default, and the prefix without the
   flag raises "Main world evaluation is disabled". See :func:`eval_js`.

2. **``wait_for_function`` has no main-world form at all.** Probed 2026-08-30
   across camoufox 0.5.4 and 0.5.5 on beta.29: with ``mw:`` and the launch flag
   both on, ``page.wait_for_function("mw:window.MARKER === 42")`` still times
   out, while the identical expression through ``page.evaluate`` returns 42.
   camoufox documents the prefix for ``evaluate`` only. So the migration this
   module's earlier note described -- "prefix every evaluate /
   wait_for_function" -- was only half possible. :func:`wait_js` polls
   ``evaluate`` instead.

3. **``add_init_script`` has no main-world form either**, which matters more
   than it sounds: the suites mock the backend by defining ``window.__api``
   before the app's own scripts read it. All four spellings (page/context,
   plain, ``mw:``-prefixed, keyword) leave the page unable to see what they
   installed. :func:`add_init_js` bridges it the way userscripts always have --
   see :func:`main_world_bootstrap`.

Everything goes through these helpers rather than each suite prefixing its own
strings. This module already exists because the launch call was copy-pasted 17
times and swapping it meant touching every file; 191 open-coded ``mw:`` prefixes
would rebuild that exact problem one layer up. When the browser next moves the
goalposts, it is one function again.

Engine: **camoufox** (anti-detect Firefox) rather than Chromium. It is the house
browser-automation transport (see the ``gemini-camoufox`` skill), so this
consolidates on one engine instead of also carrying a ~130 MB Chromium download
that every fresh dev environment silently failed without. camoufox exposes
``launch_options()`` -- executable_path/args/env/firefox_user_prefs -- which makes
``p.firefox.launch(**opts)`` a drop-in for the old chromium call, so the suites
keep their existing ``async_playwright()`` structure.
"""

from __future__ import annotations

import json
import os
import time

import pytest

# How long a UI wait may take before a test gives up.
#
# This is a BUDGET, not an assertion. No e2e test here measures how FAST the UI
# is; every wait asserts that a condition EVENTUALLY holds. So a tight budget
# cannot catch a defect a generous one misses — it can only turn a momentarily
# slow machine into a red test that reads like a regression. The suites had
# ~47 ad-hoc budgets (16x 2000ms, 14x 4000ms, 7x 5000ms), each invented at its
# call site, and on 2026-08-23 two of them went red during a release while the
# machine was busy with a py2app build: the same suite that normally finishes
# in 372s took 618s.
#
# Deliberately NOT applied to absence assertions ("this must not appear"),
# where a short timeout IS the assertion. Those keep their own explicit values.
#
# Override for a slow CI box with DIVOOM_E2E_TIMEOUT_MS.
UI_TIMEOUT_MS = int(os.environ.get("DIVOOM_E2E_TIMEOUT_MS", "20000"))


def require_browser() -> None:
    """Skip the test unless a launchable browser is actually present.

    Checks the binary, not just the import — that distinction is the whole
    point of this helper.
    """
    pytest.importorskip("playwright.async_api")
    pytest.importorskip("camoufox.utils")
    try:
        from camoufox.pkgman import installed_verstr

        version = installed_verstr()
    except Exception as exc:  # not downloaded, or pkgman API moved
        pytest.skip(f"camoufox browser unavailable ({exc}) — run: python3 -m camoufox fetch")
    if not version:
        pytest.skip("camoufox browser not downloaded — run: python3 -m camoufox fetch")


async def launch(p):
    """Launch the e2e browser from an ``async_playwright()`` instance.

    Drop-in for the old ``p.chromium.launch(headless=True)``.

    Calls :func:`require_browser` itself -- see the note on :func:`launch_sync`.
    """
    require_browser()
    from camoufox.utils import launch_options

    return await p.firefox.launch(**launch_options(headless=True, main_world_eval=True))


def launch_sync(p):
    """Sync-API counterpart of :func:`launch`.

    Drop-in for ``p.chromium.launch(headless=True)`` under ``sync_playwright()``.
    Two suites (wall-canvas drag, the live-widgets diagnostic) use the sync API.

    The guard lives HERE, not only at each call site. R66 asked all 15 e2e
    modules to call ``require_browser()``; 13 did. The two that did not were
    exactly the two sync-API ones, so on a machine with no browser they ERRORED
    (``CamoufoxNotInstalled`` at fixture setup) while the other 13 skipped --
    CI run 32654312489, 6 errors. A guard you have to remember to call is not a
    guard, so getting a browser now requires passing it by construction.
    """
    require_browser()
    from camoufox.utils import launch_options

    return p.firefox.launch(**launch_options(headless=True, main_world_eval=True))


# ── Reaching the page's main world ────────────────────────────────────────────

#: camoufox's opt-in prefix for running a script in the page's main world.
MAIN_WORLD_PREFIX = "mw:"

#: How often :func:`wait_js` re-evaluates its condition.
#:
#: ``wait_for_function`` used the browser's own scheduler; polling is the price
#: of it having no main-world path. 50ms is well under any UI transition these
#: suites assert on, and the cost is bounded by the timeout, not the interval.
POLL_INTERVAL_MS = 50


def main_world(script: str) -> str:
    """Prefix ``script`` so camoufox evaluates it in the page's main world.

    Idempotent, so a caller that has already prefixed does not end up with
    ``mw:mw:``. Leading whitespace is stripped because the suites pass
    triple-quoted scripts that begin with a newline, and the prefix has to be
    the first thing camoufox sees.
    """
    stripped = script.lstrip()
    if stripped.startswith(MAIN_WORLD_PREFIX):
        return stripped
    return MAIN_WORLD_PREFIX + stripped


def eval_js(page, script: str, *args):
    """``page.evaluate`` against the page's MAIN world.

    Returns whatever ``page.evaluate`` returns, so this is a drop-in under both
    playwright APIs: awaitable under the async one, a plain value under the sync
    one. That is deliberate -- a suite does ``return page.evaluate(...)`` from an
    async helper without awaiting, and a version that awaited internally would
    silently change its meaning.

    Without the main world the app's globals are invisible and every assertion
    reads ``None``, which looks exactly like a broken feature rather than a
    browser that changed under the suite.
    """
    return page.evaluate(main_world(script), *args)


class MainWorldTimeout(AssertionError):
    """A :func:`wait_js` condition never became truthy.

    An ``AssertionError`` rather than a playwright ``TimeoutError`` because that
    is what it is: the suite asserted a condition would eventually hold, and it
    did not. The message carries the script, so a failure names the condition
    instead of only a line number.
    """


async def wait_js(page, script: str, *, timeout: int | None = None):
    """Main-world replacement for ``page.wait_for_function`` (async API).

    ``timeout`` is in milliseconds, matching playwright's own signature, and
    defaults to :data:`UI_TIMEOUT_MS`.

    Polls :func:`eval_js` because camoufox's ``mw:`` prefix is implemented for
    ``evaluate`` only -- ``wait_for_function`` stays in the isolated world no
    matter what is prefixed or which launch flags are set (probed 2026-08-30).

    Evaluation errors are swallowed while waiting, on purpose: a condition that
    reads ``window.Foo.bar`` legitimately throws until ``Foo`` exists, and that
    is the normal case this function is for. A condition that throws forever
    still fails, via the timeout, with the last error in its message.

    Async only. All 62 waits in the suite are in async tests; the two sync
    suites wait on selectors, which the isolated world sees perfectly well. A
    sync counterpart is the same loop with ``page.wait_for_timeout``, and is not
    written until something needs it -- an untested helper kept "just in case"
    is where the next surprise hides.
    """
    import asyncio

    budget_ms = UI_TIMEOUT_MS if timeout is None else timeout
    deadline = time.monotonic() + budget_ms / 1000
    last_error: Exception | None = None
    while True:
        try:
            value = await eval_js(page, script)
            if value:
                return value
            last_error = None
        except Exception as exc:  # not ready yet -- see docstring
            last_error = exc
        if time.monotonic() >= deadline:
            raise MainWorldTimeout(_timeout_message(script, budget_ms, last_error))
        await asyncio.sleep(POLL_INTERVAL_MS / 1000)


def _timeout_message(script: str, budget_ms: int, last_error: Exception | None) -> str:
    condition = " ".join(script.split())
    if len(condition) > 200:
        condition = condition[:197] + "..."
    tail = ""
    if last_error is not None:
        tail = f"; last evaluation raised {type(last_error).__name__}: {last_error}"
    return f"condition never became true within {budget_ms}ms: {condition}{tail}"


def main_world_bootstrap(source: str) -> str:
    """Wrap ``source`` so an init script installs it in the page's MAIN world.

    The way through is the one userscripts have always used for
    ``@run-at document-start``: the isolated world shares the DOM, and a
    ``<script>`` element appended to the document executes in the MAIN world.
    So the init script (isolated) builds a ``<script>`` carrying ``source`` and
    inserts it; the browser runs it in the page's own world.

    ``document.documentElement`` does not necessarily exist yet at
    document_start, hence the MutationObserver fallback -- without it this
    silently does nothing on whichever page happens to parse slightly
    differently, and a mock that silently fails to install is indistinguishable
    from a feature that is broken.

    Ordering is what makes it correct, and it holds: probed 2026-08-30 on a page
    whose own ``<head>`` script appends to a marker array, the result is
    ``['mock', 'app']`` -- the injected source ran first.
    """
    literal = json.dumps(source)
    return (
        "(() => {"
        "  const s = document.createElement('script');"
        f" s.textContent = {literal};"
        "  const install = (root) => { root.insertBefore(s, root.firstChild); s.remove(); };"
        "  const root = document.documentElement;"
        "  if (root) { install(root); return; }"
        "  new MutationObserver((_, obs) => {"
        "    const r = document.documentElement;"
        "    if (r) { obs.disconnect(); install(r); }"
        "  }).observe(document, {childList: true, subtree: true});"
        "})();"
    )


def add_init_js(page, source: str):
    """``page.add_init_script`` that the PAGE can actually see.

    Drop-in for ``page.add_init_script(source)``: returns whatever playwright
    returns, so it awaits under the async API and does not under the sync one.
    """
    return page.add_init_script(main_world_bootstrap(source))
