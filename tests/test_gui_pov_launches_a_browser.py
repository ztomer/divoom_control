"""`scripts/gui_pov.py` reaches the browser launch instead of "skipping".

`6d9cda6` moved the browser opt-in to the one launch seam
(`tests.support.browser.require_browser`), set from pytest's `--run-browser`.
Right for tests; wrong for the one caller that is not a test. `gui_pov.py` is
the user-POV harness AGENTS.md sends you to ("does the app actually work?"),
and from that commit on every run of it died on its first line of real work
with `Skipped: launches a real browser; run with --run-browser` -- a pytest
outcome raised in a plain script, naming a flag the script does not have.
Found 2026-10-18 by running it for the P5.4 weather card.

Running the script IS the opt-in. This drives `gui_pov.run()` with the daemon
stack and the browser replaced by fakes, and requires that it get as far as
asking Playwright for a browser. It runs WITHOUT `--run-browser`, which is the
state a script is always in.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")

REPO = Path(__file__).resolve().parent.parent


class _Reached(Exception):
    """The launch was asked for: everything before it let the script through."""


def _load_gui_pov():
    spec = importlib.util.spec_from_file_location("gui_pov_under_test", REPO / "scripts" / "gui_pov.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeStack:
    def __init__(self, _out):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeFirefox:
    async def launch(self, **_kw):
        raise _Reached


class _FakePlaywright:
    firefox = _FakeFirefox()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def test_gui_pov_gets_to_the_browser_without_the_pytest_flag(monkeypatch, tmp_path):
    from tests.support import browser as browser_support

    # The state of every script run: nobody passed --run-browser.
    monkeypatch.setattr(browser_support, "RUN_BROWSER", False)
    gui_pov = _load_gui_pov()
    monkeypatch.setattr(gui_pov, "Stack", _FakeStack)
    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: _FakePlaywright())

    args = argparse.Namespace(out=str(tmp_path), widget="sysmon", kill_daemon=False)
    try:
        asyncio.run(gui_pov.run(args))
    except _Reached:
        return
    except pytest.skip.Exception as exc:
        if "--run-browser" in str(exc):
            pytest.fail(f"gui_pov.py stopped at the pytest opt-in instead of launching: {exc}")
        raise  # a genuinely missing browser is a skip, as for any browser test
    pytest.fail("gui_pov.run() returned without ever asking for a browser")


def test_the_opt_in_does_not_leak_into_the_test_session(monkeypatch, tmp_path):
    """Opting the SCRIPT in must not flip pytest's switch for the tests that
    run after it in the same process."""
    from tests.support import browser as browser_support

    monkeypatch.setattr(browser_support, "RUN_BROWSER", False)
    gui_pov = _load_gui_pov()
    monkeypatch.setattr(gui_pov, "Stack", _FakeStack)
    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: _FakePlaywright())
    args = argparse.Namespace(out=str(tmp_path), widget="sysmon", kill_daemon=False)
    try:
        asyncio.run(gui_pov.run(args))
    except (_Reached, pytest.skip.Exception):
        pass
    assert browser_support.RUN_BROWSER is False

