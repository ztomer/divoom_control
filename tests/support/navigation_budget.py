"""The browser suites' navigation budget.

Playwright's own default for a navigation is 30s, and it was the one budget
in these suites nobody had measured -- every other wait is sized from a
measurement (``tests.support.browser.UI_TIMEOUT_MS``, 60s, because a
readiness wait that takes 3s unloaded takes 16s under load, and a larger cap
costs nothing on a green run and only lengthens a red one).

On a loaded machine 30s is too tight. The suites open eight browsers at
once, and on 2026-10-20 two pre-push runs of this repo were REFUSED by
``Page.goto: Timeout 30000ms exceeded`` on unrelated suites, at load 90+
(another repo's Rust build), while the same suites were green locally at
load 25. The page was fine; the load was not.

So every page and context the suites open gets the house's budget, applied
at the one seam -- ``Browser.new_page`` and ``Browser.new_context`` -- so no
suite has to remember it. 47 files would otherwise each have to, and 46 of
them would have remembered it wrong.

The patch is applied when this module is imported, which
``tests/conftest.py`` does at configuration time -- before any suite opens a
browser.
"""
from __future__ import annotations

import importlib
import inspect
import os

#: The navigation cap. Override with DIVOOM_E2E_TIMEOUT_MS, the same knob
#: the suites' other waits use, so one number governs the whole harness.
NAVIGATION_TIMEOUT_MS = int(os.environ.get("DIVOOM_E2E_TIMEOUT_MS", "60000"))


def give_navigation_budget(obj) -> None:
    """Give a page or a context the house's navigation budget."""
    setter = getattr(obj, "set_default_navigation_timeout", None)
    if setter is None:  # not a page and not a context
        return
    try:
        setter(NAVIGATION_TIMEOUT_MS)
    except Exception:  # pragma: no cover - a stub without the setter
        pass


def _wrap(original):
    if inspect.iscoroutinefunction(original):
        async def wrapper(self, *args, **kwargs):
            made = await original(self, *args, **kwargs)
            give_navigation_budget(made)
            return made
    else:
        def wrapper(self, *args, **kwargs):
            made = original(self, *args, **kwargs)
            give_navigation_budget(made)
            return made
    wrapper.__divoom_navigation_budget__ = True
    return wrapper


def patch_navigation_budget() -> None:
    """Give every page and context the suites open the house's budget."""
    for module_name in ("playwright.async_api", "playwright.sync_api"):
        try:
            api = importlib.import_module(module_name)
        except Exception:  # pragma: no cover - playwright not installed
            continue
        for class_name in ("Browser", "BrowserContext"):
            cls = getattr(api, class_name, None)
            if cls is None:  # pragma: no cover - the API moved
                continue
            for method_name in ("new_page", "new_context"):
                original = getattr(cls, method_name, None)
                if original is None:
                    continue
                if getattr(original, "__divoom_navigation_budget__", False):
                    continue
                setattr(cls, method_name, _wrap(original))


patch_navigation_budget()
