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

Engine: **camoufox** (anti-detect Firefox) rather than Chromium. It is the house
browser-automation transport (see the ``gemini-camoufox`` skill), so this
consolidates on one engine instead of also carrying a ~130 MB Chromium download
that every fresh dev environment silently failed without. camoufox exposes
``launch_options()`` -- executable_path/args/env/firefox_user_prefs -- which makes
``p.firefox.launch(**opts)`` a drop-in for the old chromium call, so the suites
keep their existing ``async_playwright()`` structure.
"""

from __future__ import annotations

import os

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

    return await p.firefox.launch(**launch_options(headless=True))


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

    return p.firefox.launch(**launch_options(headless=True))
