"""The e2e browser guard must SKIP on a missing browser, never fail.

This pins the defect R66 found. The suites previously guarded with
``pytest.importorskip("playwright.async_api")``, which only proves the Python
MODULE imports -- it says nothing about the browser BINARY. On a clean checkout
with the playwright package installed but no browser downloaded, the 15 e2e
modules did not skip: they raised ``BrowserType.launch: Executable doesn't
exist`` and produced **69 failures** that read exactly like real regressions.
CI's own comment claimed "they skip via pytest.importorskip". They did not.

Teeth: make ``require_browser()`` stop probing the binary (drop the
``installed_verstr`` check) and ``skips_when_the_browser_is_not_downloaded``
goes red.

We simulate the missing browser rather than deleting the real one -- a ~150 MB
re-download per run is not a reasonable test cost, and the thing under test is
the guard's decision, not camoufox's installer.
"""

from __future__ import annotations

import pytest

from tests.support import browser as browser_support


def _run_guard() -> str | None:
    """Run require_browser(); return the skip reason, or None if it allowed the test.

    Catches ``Skipped`` explicitly. It derives from BaseException, not Exception,
    so a bare ``except Exception`` lets it propagate and SKIPS this test instead
    of asserting -- which would leave the guard unverified while looking green.
    """
    from _pytest.outcomes import Skipped

    try:
        browser_support.require_browser()
    except Skipped as exc:
        return str(exc)
    return None


def test_skips_when_the_browser_is_not_downloaded(monkeypatch) -> None:
    """installed_verstr() returning empty means 'no binary' -> skip, not fail."""
    import camoufox.pkgman

    monkeypatch.setattr(camoufox.pkgman, "installed_verstr", lambda: "")
    reason = _run_guard()
    assert reason is not None, "a missing browser binary must skip, not proceed to launch"
    assert "camoufox fetch" in reason, f"skip reason must say how to fix it, got: {reason}"


def test_skips_when_the_pkgman_probe_raises(monkeypatch) -> None:
    """A broken/moved camoufox install must also skip rather than error out."""
    import camoufox.pkgman

    def _boom() -> str:
        raise RuntimeError("browser dir missing")

    monkeypatch.setattr(camoufox.pkgman, "installed_verstr", _boom)
    reason = _run_guard()
    assert reason is not None, "a raising probe must skip, not propagate"
    assert "camoufox fetch" in reason


def test_allows_the_test_when_a_browser_is_present() -> None:
    """The guard must not over-skip: with a real browser installed it passes.

    Without this, a guard that always skipped would look 'green' while silently
    disabling all 15 e2e suites -- the failure mode that hides regressions.
    """
    pytest.importorskip("camoufox.pkgman")
    from camoufox.pkgman import installed_verstr

    if not installed_verstr():
        pytest.skip("no camoufox browser on this machine — nothing to assert")
    assert _run_guard() is None, "guard must allow the test when a browser IS installed"
