"""Launch options for the e2e browser: camoufox's, plus a hermetic network.

Split from tests/support/browser.py (the one launch seam) to keep that file
under the house line cap.
"""

from __future__ import annotations

import platform

#: Where a test browser's off-machine requests go: a closed local port, so they
#: fail in milliseconds. index.html links Google Fonts, and `page.goto` waits for
#: that stylesheet: probed 2026-10-19, 2.7-6.0 s per goto over the network vs
#: 0.12-0.73 s offline, and under load the fetch alone crossed goto's 30 s cap
#: (8 to 17 Page.goto timeouts per -n 8 run at load 100-160, different tests
#: each time). A suite that needs the internet is not testing this repo.
#: localhost stays reachable for the suites' own servers; page.route mocks run
#: before the proxy.
OFFLINE_PROXY = {"server": "http://127.0.0.1:9", "bypass": "localhost,127.0.0.1"}

#: What the browser's own chrome takes from the outer window: measured
#: 2026-11-01, the content starts 89 px down and 4 px in (mozInnerScreenY/X at
#: screenY 0), with margin.
BROWSER_CHROME = (16, 120)
#: The test browser's outer window, fixed. Larger than every suite's viewport
#: plus the chrome (tests/test_e2e_browser_window.py scans them), so the window
#: never has to move to hold a page.
HARNESS_WINDOW = (1600, 1100)
#: The camoufox fingerprint keys that fix the window, on a screen that holds it.
HARNESS_GEOMETRY = {
    "window.outerWidth": HARNESS_WINDOW[0], "window.outerHeight": HARNESS_WINDOW[1],
    "window.screenX": 0, "window.screenY": 0,
    "screen.width": 2560, "screen.height": 1440, "screen.availWidth": 2560, "screen.availHeight": 1415,
}


#: The fingerprint OS for each host this suite runs on (macOS on Apple silicon,
#: Linux): camoufox draws the OS at random, weighted toward Windows, once per
#: process, and a foreign OS lists fonts the host lacks (Calibri, Consolas, ...)
#: so every new page costs 2.5-2.6 s instead of 0.12-0.16 s. CI's browser step
#: took 58-91 min on a Windows draw and 13-23 min on a macOS one, the same 278
#: tests (2026-11-02; tests/test_e2e_browser_host_os.py).
_HOST_OS = {"Darwin": "macos", "Linux": "linux"}


def fingerprint_os() -> str:
    """The host's OS as camoufox names it; any other host is refused, never guessed."""
    host = platform.system()
    if host not in _HOST_OS:
        raise RuntimeError(f"the browser suites run on macOS and Linux, not {host}")
    return _HOST_OS[host]


def launch_options_for(*, network: bool) -> dict:
    from camoufox.utils import launch_options

    from tests.support import fpgen_compat

    fpgen_compat.install()  # fpgen 1.3.0 cannot draw a fingerprint on 3.15 (P1.22)
    # The fingerprint's window is otherwise random, and one shorter than the
    # page made Firefox move the content up mid-test, so a gesture landed
    # above its target (CI runs 41367764353, 41370988097). Both the window AND
    # the screen are fixed: camoufox clamps a window to the drawn screen, and
    # its screen constraint is not always honoured (1600x900 screens were still
    # drawn under min_height=1300, 4 in 1000). The OS is the host's (fingerprint_os).
    # The rest stays random.
    opts = launch_options(headless=True, main_world_eval=True, config=HARNESS_GEOMETRY,
                          os=fingerprint_os(), i_know_what_im_doing=True)
    if not network:
        opts["proxy"] = OFFLINE_PROXY
    return opts
