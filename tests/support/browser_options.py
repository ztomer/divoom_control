"""Launch options for the e2e browser: camoufox's, plus a hermetic network.

Split from tests/support/browser.py (the one launch seam) to keep that file
under the house line cap.
"""

from __future__ import annotations

#: Where a test browser's off-machine requests go: a closed local port, so they
#: fail in milliseconds. index.html links Google Fonts, and `page.goto` waits for
#: that stylesheet: probed 2026-10-19, 2.7-6.0 s per goto over the network vs
#: 0.12-0.73 s offline, and under load the fetch alone crossed goto's 30 s cap
#: (8 to 17 Page.goto timeouts per -n 8 run at load 100-160, different tests
#: each time). A suite that needs the internet is not testing this repo.
#: localhost stays reachable for the suites' own servers; page.route mocks run
#: before the proxy.
OFFLINE_PROXY = {"server": "http://127.0.0.1:9", "bypass": "localhost,127.0.0.1"}


def launch_options_for(*, network: bool) -> dict:
    from camoufox.utils import launch_options

    opts = launch_options(headless=True, main_world_eval=True)
    if not network:
        opts["proxy"] = OFFLINE_PROXY
    return opts
