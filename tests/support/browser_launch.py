"""A browser that does not start is its own outcome, named by its cause.

On 2026-11-02 one pre-push run (8 workers, 288 tests) failed
``test_each_wall_write_names_the_panel_that_did_not_take_it`` with
``BrowserType.launch: Failed to launch the browser process``: camoufox printed
its headless banner and exited 1 after 130 ms. The last line of its stderr,
``sandbox_extension_issue_file_to_process failed ... Operation not permitted``,
was a red herring -- libsystem_sandbox logs it on EVERY launch (203 of them in
that run, all but one healthy).

The cause is in macOS LaunchServices, found in the unified log and then
reproduced on demand:

* At 2026-11-01 19:59 the owner's installed ``Divoom.app`` ran as pid 41929
  under ASN 0x0-0xdf6cf5f. It quit at 20:23, but its ``divoom-menubar``
  child kept running in the app's coalition, so launchservicesd KEPT the app's
  record, keyed by pid ("ExitedApps ... exited = 1", coalitionPIDs still live).
* Seven and a half hours later the pid was recycled to a camoufox. Its AppKit
  check-in was bound to that stale record: the dead app's ASN, ``launchedByLS=1
  bringForward=1`` (every one of the other 2,602 camoufox launches in the
  retained three days logged ``launchedByLS=0``). It exited 1 within 130 ms.
* The record is spent by that check-in (loginwindow logs
  ``kLSNotifyApplicationExitedIncludingSubordinateProcesses`` for it), so the
  same pid launches cleanly afterwards; and the next launch gets another pid.

Reproduced deterministically 2026-11-02: an applet that leaves a child in its
own process group and quits, then camoufox started at the applet's recycled
pid -> exit 1 in 0.11 s, stderr only the banner -- the CI signature exactly.

So the cause is external to this repo and single-use, and the harness answers
it ONE way: a launch failure is :class:`BrowserLaunchFailed`, never a generic
test error; the stale-LaunchServices signature (:func:`classify`) earns ONE
relaunch, recorded as a :class:`BrowserRelaunched` warning that lands in the
pytest summary; anything else, or the same failure twice, fails at once with
the cause named. ``tests/test_browser_launch_outcome.py`` holds it.
"""

from __future__ import annotations

import re
import warnings

#: The signature's name, as the failure and the warning print it.
STALE_LS_PID = "stale-launchservices-pid"
#: The lines a launch that LaunchServices killed prints, and nothing else.
_BENIGN_BROWSER_LINES = (
    re.compile(r"^\*\*\* You are running in headless mode\.$"),
    # libsystem_sandbox, on every launch (see the module docstring).
    re.compile(r"^sandbox_extension_issue_file_to_process failed for "),
)
_BROWSER_LINE = re.compile(r"\[pid=\d+\]\[(?:err|out)\] ?(.*)$")
_EXITED_1 = "<process did exit: exitCode=1, signal=null>"
_FAILED_TO_LAUNCH = "Failed to launch the browser process"


class BrowserLaunchFailed(RuntimeError):
    """The browser never started; ``cause`` names why, when it is known."""

    def __init__(self, message: str, cause: str | None):
        super().__init__(message)
        self.cause = cause


class BrowserRelaunched(UserWarning):
    """A launch failed on a proven external cause and was relaunched once."""


def classify(message: str) -> str | None:
    """The known cause of a failed launch, from Playwright's error text.

    :data:`STALE_LS_PID` when the browser exited 1 having printed only what
    every launch prints; None for anything else (a crash, a missing binary, a
    timeout, a browser that said why it stopped)."""
    if _FAILED_TO_LAUNCH not in message or _EXITED_1 not in message:
        return None
    said = [m.group(1).strip() for m in map(_BROWSER_LINE.search, message.splitlines()) if m]
    if not all(any(p.match(line) for p in _BENIGN_BROWSER_LINES) for line in said if line):
        return None
    return STALE_LS_PID


def _failed(exc: Exception, attempt: int) -> BrowserLaunchFailed:
    cause = classify(str(exc))
    if cause is None:
        head = "the browser did not start (cause not classified)"
    else:
        head = (
            f"the browser did not start: {cause} (macOS bound its pid to a dead "
            "app's LaunchServices record; tests/support/browser_launch.py)"
        )
    if attempt > 1:
        head += f", on relaunch {attempt - 1} as well"
    return BrowserLaunchFailed(f"{head}\n{exc}", cause)


def _launch_error():
    from playwright.async_api import Error

    return Error


def _relaunch_note(exc: Exception) -> None:
    warnings.warn(
        BrowserRelaunched(f"browser relaunched once after {STALE_LS_PID}: {str(exc).splitlines()[0]}"), stacklevel=3
    )


async def launch_async(start):
    """``await start()``, with the one relaunch :func:`classify` allows."""
    error = _launch_error()
    try:
        return await start()
    except error as exc:
        if classify(str(exc)) is None:
            raise _failed(exc, 1) from exc
        _relaunch_note(exc)
    try:
        return await start()
    except error as exc:
        raise _failed(exc, 2) from exc


def launch_blocking(start):
    """Sync-API counterpart of :func:`launch_async`."""
    error = _launch_error()
    try:
        return start()
    except error as exc:
        if classify(str(exc)) is None:
            raise _failed(exc, 1) from exc
        _relaunch_note(exc)
    try:
        return start()
    except error as exc:
        raise _failed(exc, 2) from exc
