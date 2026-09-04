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

import asyncio

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


def test_skips_when_the_browser_is_genuinely_not_installed(monkeypatch) -> None:
    """Drive camoufox's OWN not-installed path, not a stub of our probe.

    `get_active_path() is None` is exactly what camoufox reports when no browser
    has been fetched; `installed_verstr()` then raises CamoufoxNotInstalled.
    Patching that instead of our own `installed_verstr` reference means this
    exercises the real library code, so it stays honest if camoufox changes how
    absence is signalled — an earlier version of this test stubbed
    `installed_verstr` to return "", a condition the library never actually
    produces, which proved only that our branch worked and not that reality
    reaches it.
    """
    import camoufox.multiversion

    monkeypatch.setattr(camoufox.multiversion, "get_active_path", lambda: None)
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


def _browser_is_installed() -> bool:
    """True only if camoufox reports a real, active install.

    ``installed_verstr()`` RAISES ``CamoufoxNotInstalled`` when nothing is
    fetched -- it does not return a falsy string. The bail-out here used to be
    ``if not installed_verstr()``, written against a return-value contract the
    library does not have, so on a browserless machine this test blew up with
    ``CamoufoxNotInstalled`` instead of skipping (CI run 32654312489). That is
    the same mistake the sibling test's docstring warns about, made one function
    over: asserting on a shape the library never produces.

    Loudness about a missing browser belongs in the CI install step, which now
    verifies its own effect; the suite's job is to skip honestly.
    """
    try:
        from camoufox.pkgman import installed_verstr

        return bool(installed_verstr())
    except Exception:
        return False


def test_allows_the_test_when_a_browser_is_present() -> None:
    """The guard must not over-skip: with a real browser installed it passes.

    Without this, a guard that always skipped would look 'green' while silently
    disabling all 15 e2e suites -- the failure mode that hides regressions.
    """
    pytest.importorskip("camoufox.pkgman")
    if not _browser_is_installed():
        pytest.skip("no camoufox browser on this machine — nothing to assert")
    assert _run_guard() is None, "guard must allow the test when a browser IS installed"


def test_launch_helpers_guard_themselves(monkeypatch) -> None:
    """Getting a browser must require passing the guard, by construction.

    R66 relied on all 15 e2e modules remembering to call ``require_browser()``.
    The two sync-API suites did not, so a missing browser ERRORED them at
    fixture setup while the other 13 skipped. Both helpers now guard internally.

    Teeth (verified 2026-08-23): drop the ``require_browser()`` call from
    ``launch_sync`` and this goes red -- the call falls through to the
    playwright object instead of skipping.
    """
    from _pytest.outcomes import Skipped

    import camoufox.multiversion

    monkeypatch.setattr(camoufox.multiversion, "get_active_path", lambda: None)

    with pytest.raises(Skipped):
        browser_support.launch_sync(object())  # never reaches the playwright arg

    async def _call_async() -> None:
        await browser_support.launch(object())

    with pytest.raises(Skipped):
        asyncio.run(_call_async())


def test_every_e2e_module_gets_its_browser_through_the_seam() -> None:
    """No suite may launch a browser behind the helpers' backs.

    The guard is only structural while ``tests/support/browser.py`` is the one
    way to get a browser. A module calling ``p.firefox.launch``/``p.chromium
    .launch`` directly would reintroduce the R66 hole with the guard still
    looking healthy.
    """
    from pathlib import Path

    this_file = Path(__file__).resolve()
    tests_dir = this_file.parent
    offenders = []
    for path in sorted(tests_dir.glob("test_*.py")):
        if path.resolve() == this_file:
            continue  # this module NAMES the banned calls to ban them
        text = path.read_text(encoding="utf-8")
        for engine in ("p.firefox.launch", "p.chromium.launch", "p.webkit.launch"):
            if engine in text:
                offenders.append(f"{path.name}: {engine}")
    assert not offenders, (
        "e2e suites must launch via tests.support.browser, not directly: "
        + ", ".join(offenders)
    )
