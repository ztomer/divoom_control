"""The browser suites' navigation budget (tests/support/browser.py).

Playwright's own default for a navigation is 30s, and it was the one budget
in these suites nobody had measured -- every other wait was sized from a
measurement, and this one was the library's. On a loaded machine it is too
tight: the suites open eight browsers at once, and on 2026-10-20 two
pre-push runs of this repo were REFUSED by ``Page.goto: Timeout 30000ms
exceeded`` on unrelated suites, at load 90+ (another repo's Rust build),
while the same suites were green locally at load 25. The page was fine; the
load was not.

So every page and context the suites open now gets the house's navigation
budget, applied at the one seam (`Browser.new_page` / `Browser.new_context`)
so no suite has to remember it -- 47 files would otherwise each have to,
and 46 of them would have remembered it wrong.

These tests are the gate for that patch: a seam that stopped being patched
would leave the suites with the library's 30s again, and the flake would
come back as an intermittent pre-push refusal nobody could point at.
"""
from __future__ import annotations

from tests.support import browser as B


def _seams():
    """Every place a suite can open a page or a context."""
    import playwright.async_api as async_api
    import playwright.sync_api as sync_api

    for api in (async_api, sync_api):
        for class_name in ("Browser", "BrowserContext"):
            cls = getattr(api, class_name, None)
            if cls is None:  # pragma: no cover - the API moved
                continue
            for method_name in ("new_page", "new_context"):
                method = getattr(cls, method_name, None)
                if method is None:  # pragma: no cover - the API moved
                    continue
                yield f"{class_name}.{method_name}", method


def test_every_seam_gets_the_navigation_budget():
    for name, method in _seams():
        assert getattr(method, "__divoom_navigation_budget__", False), (
            f"{name} is not patched, so a suite that opens a page through it "
            f"gets playwright's 30s and the load flake comes back"
        )


def test_the_budget_is_the_house_ui_budget():
    """One number, one argument: a loaded machine stretches a wait, and a
    longer cap costs nothing on a green run."""
    assert B.NAVIGATION_TIMEOUT_MS == B.UI_TIMEOUT_MS


def test_the_budget_is_applied_to_a_page():
    class Fake:
        def __init__(self):
            self.ms = None

        def set_default_navigation_timeout(self, ms):
            self.ms = ms

    fake = Fake()
    B._give_navigation_budget(fake)
    assert fake.ms == B.NAVIGATION_TIMEOUT_MS


def test_an_object_that_is_neither_a_page_nor_a_context_is_left_alone():
    class NotAPage:
        pass

    B._give_navigation_budget(NotAPage())  # must not raise
