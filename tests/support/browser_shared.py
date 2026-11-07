"""One browser per test session, a fresh context per test (P1.21).

Every browser suite used to launch its own browser per test: about 2.2 s each
on the dev machine (camoufox starting, before any page), 57 of the 58 suites,
385 tests -- ``scripts/browser_e2e.sh`` measured 6 min 50 s serial. A browser
CONTEXT is what isolates a test (its own cookies, storage, cache, pages) and
costs about 0.01 s, so the session launches ONE browser and each test gets its
own context.

``tests/support/browser.py``'s ``launch`` is the one way an async suite gets a
browser, so it is the one place this lives: it returns a
:class:`SharedBrowser`, a handle that offers
what the suites use -- ``new_page``, ``new_context``, ``close`` -- over the
session's real browser. ``close()`` closes the contexts the HANDLE opened, not
the browser. A handle a test forgot to close (or a test that failed before its
``finally``) is closed by the next ``launch``, so a test never sees another
test's pages.

What makes a shared browser possible, and why it is not a fixture each suite
asks for: a Playwright browser belongs to the event loop that started it, and
pytest-asyncio gives every test its own loop. ``tests/conftest.py`` therefore
runs the browser suites' async tests on ONE session loop
(:func:`runs_on_session_loop`), and the shared browser is started on it. A
launch from any other loop is :class:`SharedBrowserWrongLoop`, never a quiet
second browser: a quiet second browser is the cost this module removed.

Not shared: a caller that is not a test (``scripts/gui_pov.py`` asks for the
network and its own run); and the SYNC API (``launch_sync``), which cannot be:
``sync_playwright()`` keeps its loop registered as running on the thread while a
test's own ``with sync_playwright()`` block is open, so a second instance (the
shared one) fails with "Sync API inside the asyncio loop". The three sync
suites hold one browser per module already (``test_gui_wall_canvas_drag``'s
fixture) or have one test (measured: 8 launches of the 385 tests).

Reaping: the browser belongs to the SESSION (``browser_reaper.session_owned``),
not to the test that happened to start it, or the test's own reaper frame would
kill it when that test ended.
"""

from __future__ import annotations

import asyncio
import contextlib

from tests.support import browser_reaper
from tests.support.browser_launch import launch_async
from tests.support.browser_options import launch_options_for

class SharedBrowserWrongLoop(RuntimeError):
    """A test asked for the shared browser from an event loop that is not the
    one that started it."""


def runs_on_session_loop(module) -> bool:
    """Does this test module drive a browser?

    Judged from its source -- it mentions ``playwright`` -- which is also how
    ``scripts/browser_e2e.sh`` picks the browser suites, so the two cannot
    disagree about which files are browser suites. (Judging by what the module
    imported missed the suites that reach ``launch`` through another suite's
    helper.) A module this misses fails loudly, never quietly: its launch is
    :class:`SharedBrowserWrongLoop`."""
    path = getattr(module, "__file__", None)
    if not path:
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return "playwright" in f.read()
    except OSError:
        return False


# ── async API ────────────────────────────────────────────────────────────────


class _AsyncHost:
    def __init__(self, playwright, browser, loop):
        self.playwright, self.browser, self.loop = playwright, browser, loop
        self.handles: list[SharedBrowser] = []

    async def sweep(self) -> None:
        for handle in self.handles:
            await handle.close()
        self.handles.clear()


class SharedBrowser:
    """A test's view of the session's browser: its own contexts, nothing else."""

    def __init__(self, host: _AsyncHost):
        self._host = host
        self._contexts: list = []

    async def new_context(self, **kwargs):
        context = await self._host.browser.new_context(**kwargs)
        self._contexts.append(context)
        return context

    async def new_page(self, **kwargs):
        return await (await self.new_context(**kwargs)).new_page()

    async def close(self) -> None:
        contexts, self._contexts = self._contexts, []
        for context in reversed(contexts):
            with contextlib.suppress(Exception):  # already closed by the test
                await context.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()


_async_host: _AsyncHost | None = None
#: The loop the shared browser may live on, bound by the session fixture in
#: tests/conftest.py before any test runs. Judged against THIS, not against
#: whichever loop happened to start the browser: a first launch from another
#: loop used to start the browser there, it died with that loop, and every later
#: test quietly started a new one.
_session_loop: asyncio.AbstractEventLoop | None = None


def bind_session_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """The session loop (tests/conftest.py); None at session end."""
    global _session_loop
    _session_loop = loop


async def shared_browser() -> SharedBrowser:
    """The session's browser, started on first use, as a fresh handle."""
    global _async_host
    loop = asyncio.get_running_loop()
    if loop is not _session_loop:
        raise SharedBrowserWrongLoop(
            "the shared browser lives on the session loop and this is another one; browser "
            "suites run on the session loop (tests/conftest.py, tests/support/browser_shared.py)")
    host = _async_host
    if host is not None and host.browser.is_connected():
        await host.sweep()
    else:
        if host is not None:  # it died: stop its driver too, or each crash leaks a node process
            await _stop(host)
        _async_host = host = await _start_async(loop)
    handle = SharedBrowser(host)
    host.handles.append(handle)
    return handle


async def _stop(host: _AsyncHost) -> None:
    await host.sweep()
    with contextlib.suppress(Exception):  # already gone when the browser crashed
        await host.browser.close()
    with contextlib.suppress(Exception):
        await host.playwright.stop()


async def _start_async(loop) -> _AsyncHost:
    from playwright.async_api import async_playwright

    with browser_reaper.session_owned():
        playwright = await async_playwright().start()
        try:
            browser = await launch_async(
                lambda: playwright.firefox.launch(**launch_options_for(network=False, launching=True)))
        except BaseException:
            await playwright.stop()
            raise
    return _AsyncHost(playwright, browser, loop)


async def shutdown_async() -> None:
    """End of session: close the contexts, the browser, the driver."""
    global _async_host
    host, _async_host = _async_host, None
    if host is None or host.loop is not asyncio.get_running_loop():
        return
    await _stop(host)
