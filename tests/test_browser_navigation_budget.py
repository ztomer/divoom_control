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
from tests.support import navigation_budget as N


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
    longer cap costs nothing on a green run.

    The budget lives in `tests/support/navigation_budget.py` — the patch has to
    be importable without playwright's API — and the readiness cap in
    `tests/support/browser.py`. They are the SAME number on purpose."""
    assert N.NAVIGATION_TIMEOUT_MS == B.UI_TIMEOUT_MS


def test_the_budget_is_applied_to_a_page():
    class Fake:
        def __init__(self):
            self.ms = {}

        def set_default_navigation_timeout(self, ms):
            self.ms["navigation"] = ms

        def set_default_timeout(self, ms):
            self.ms["action"] = ms

    fake = Fake()
    N.give_navigation_budget(fake)
    # Actions too: a `click` that names no timeout (tools/check_ui_budgets.py
    # refuses one that does) would otherwise get playwright's 30s.
    assert fake.ms == {"navigation": N.NAVIGATION_TIMEOUT_MS, "action": N.NAVIGATION_TIMEOUT_MS}


def test_a_real_page_gets_the_budget_for_actions():
    """The seam, end to end: a page opened the ordinary way times an action out
    at the house budget, not playwright's 30s. Read back through playwright's own
    timeout settings, so a seam that stopped setting it goes red here."""
    B.require_browser()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = B.launch_sync(p)
        try:
            page = browser.new_page()
            assert page._impl_obj._timeout_settings.timeout() == N.NAVIGATION_TIMEOUT_MS
        finally:
            browser.close()


def test_an_object_that_is_neither_a_page_nor_a_context_is_left_alone():
    class NotAPage:
        pass

    N.give_navigation_budget(NotAPage())  # must not raise
