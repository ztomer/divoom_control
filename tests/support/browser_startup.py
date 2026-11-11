"""Waiting on the app's own startup scan (DV.E2ELOAD, 2026-11-11)."""

from __future__ import annotations

from tests.support.browser import wait_js

#: The app's startup scan has reported in the scan card (``#scan-result``,
#: ``settings_hardware.js`` ``sayScan``, which sets ``data-kind`` whatever the
#: outcome, auto scan or not).
STARTUP_SCAN_REPORTED_JS = "() => !!document.getElementById('scan-result')?.dataset.kind"


async def wait_startup_scan(page, *, timeout: int | None = None):
    """Wait until the app's own startup scan has run and reported.

    ``app_init.js`` starts that scan on a TIMER after the session restore, so
    "it has happened by now" is a wall-clock bet. Unloaded the timer beat the
    test; under load (2026-11-11, DV.E2ELOAD) a test's steps reached it first:
    a test holding ``scan_devices`` held the startup scan too, and a test
    asserting "no toast" after a fixed sleep could assert before the scan had
    run at all. The report is the event; wait on it.

    Requires a bridge whose ``scan_devices`` answers (resolve or reject) on
    its own; one that holds it would hold the startup scan here.
    """
    return await wait_js(page, STARTUP_SCAN_REPORTED_JS, timeout=timeout)
