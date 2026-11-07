"""A browser that does not start is a named outcome (tests/support/browser_launch.py).

The stale-LaunchServices text below is the failure pre-push hit on 2026-11-02
(camoufox at a recycled pid, exit 1 after 130 ms), verbatim but for the paths.
"""

from __future__ import annotations

import asyncio
import warnings

import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import Error  # noqa: E402

from tests.support import browser, browser_launch as bl  # noqa: E402

_EXE = "/T/divoom-test-home-x/Library/Caches/camoufox/browsers/official/b/Camoufox.app"
STALE_LS = f"""BrowserType.launch: Failed to launch the browser process.
Browser logs:

<launching> {_EXE}/Contents/MacOS/camoufox -no-remote -headless -profile /T/p -juggler-pipe -silent
<launched> pid=41929
[pid=41929][err] *** You are running in headless mode.
[pid=41929][err] sandbox_extension_issue_file_to_process failed for {_EXE}: 1 (Operation not permitted)
[pid=41929] <process did exit: exitCode=1, signal=null>
[pid=41929] starting temporary directories cleanup
Call log:
  - <launched> pid=41929
  - [pid=41929][err] *** You are running in headless mode.
  - [pid=41929] <process did exit: exitCode=1, signal=null>
"""
#: The same exit, but the browser said why: that is not the LaunchServices case.
SPOKE = STALE_LS.replace(
    "[pid=41929][err] *** You are running in headless mode.\n",
    "[pid=41929][err] *** You are running in headless mode.\n[pid=41929][err] Error: profile is locked\n",
    1,
)
CRASHED = STALE_LS.replace("exitCode=1, signal=null", "exitCode=null, signal=SIGSEGV")
TIMEOUT = "BrowserType.launch: Timeout 180000ms exceeded."


def test_the_stale_launchservices_failure_is_classified():
    assert bl.classify(STALE_LS) == bl.STALE_LS_PID


@pytest.mark.parametrize("text", [SPOKE, CRASHED, TIMEOUT, ""], ids=["spoke", "crashed", "timeout", "empty"])
def test_every_other_failure_is_not(text):
    assert bl.classify(text) is None


class _Starts:
    """A launch that fails with the given texts, in order, then succeeds."""

    def __init__(self, *failures: str):
        self.failures = list(failures)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.failures:
            raise Error(self.failures.pop(0))
        return "browser"


def _async(start):
    async def go():
        return start()

    return go


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_one_relaunch_on_the_external_cause_and_it_is_recorded(mode):
    start = _Starts(STALE_LS)
    with pytest.warns(bl.BrowserRelaunched, match=bl.STALE_LS_PID):
        got = asyncio.run(bl.launch_async(_async(start))) if mode == "async" else bl.launch_blocking(start)
    assert (got, start.calls) == ("browser", 2)


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_the_same_failure_twice_is_not_relaunched_again(mode):
    start = _Starts(STALE_LS, STALE_LS)
    with pytest.warns(bl.BrowserRelaunched), pytest.raises(bl.BrowserLaunchFailed) as info:
        asyncio.run(bl.launch_async(_async(start))) if mode == "async" else bl.launch_blocking(start)
    assert start.calls == 2
    assert info.value.cause == bl.STALE_LS_PID
    assert "on relaunch 1 as well" in str(info.value)


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("text", [SPOKE, CRASHED, TIMEOUT], ids=["spoke", "crashed", "timeout"])
def test_any_other_failure_is_named_and_never_relaunched(mode, text):
    start = _Starts(text)
    with warnings.catch_warnings():
        warnings.simplefilter("error", bl.BrowserRelaunched)
        with pytest.raises(bl.BrowserLaunchFailed) as info:
            asyncio.run(bl.launch_async(_async(start))) if mode == "async" else bl.launch_blocking(start)
    assert start.calls == 1
    assert info.value.cause is None
    assert "cause not classified" in str(info.value) and text.splitlines()[0] in str(info.value)


def test_both_launch_seams_go_through_the_outcome():
    """The one seam every suite launches through must not call the engine bare."""
    import inspect

    assert "launch_async(" in inspect.getsource(browser.launch)
    assert "launch_blocking(" in inspect.getsource(browser.launch_sync)
