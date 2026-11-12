"""A window that opens behind other windows still paints its first frame (DV.BGLAUNCH).

`goh ship` relaunches the app with `open -g` (scripts/ship_install.sh), so the Control
Center opens without activating and usually lands behind the window the owner is using.
WKWebView watches its window's occlusion state and does not paint while the window is
fully covered; a window that is covered from its very first show therefore has NO
content at all: a window capture (screencapture -l, a computer-use screenshot, the
app's own previews) reads a uniform blank frame, and the page draws only once the window
is uncovered or the app is activated. Measured 2026-11-12: `open -g` of Divoom 0.45.2
under an opaque cover captured 2 colours, the same window uncovered 613.

The fix is WebKit's own switch for that behaviour, `-[WKWebView
_setWindowOcclusionDetectionEnabled:]` (WKWebViewPrivate.h, macOS): occlusion detection is
turned OFF before the window is first shown, and turned back ON once the page has drawn
two animation frames, so a covered window keeps its first frame and the bench's
render loop is still throttled while the window is covered afterwards. A WebKit
without the selector degrades to today's behaviour, with a log line saying so.

Seams (tests/test_first_paint.py): `native_webview` returns the WKWebView (or None),
`call_on_main` runs a callable on the AppKit main thread, `sleep` is the poll's clock.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

OCCLUSION_SELECTOR = "_setWindowOcclusionDetectionEnabled:"

# Arms a flag that turns true after the page has produced two animation frames: the
# first frame is committed by then, so restoring occlusion detection cannot blank it.
ARM_FIRST_FRAMES_JS = (
    "window.__divoomFirstFrames = false;"
    "requestAnimationFrame(() => requestAnimationFrame(() => { window.__divoomFirstFrames = true; }));"
    "true"
)
FIRST_FRAMES_DONE_JS = "window.__divoomFirstFrames === true"

POLL_INTERVAL_S = 0.05
POLL_LIMIT_S = 5.0
MAX_POLLS = round(POLL_LIMIT_S / POLL_INTERVAL_S)


def set_occlusion_detection(webview_obj: Any, enabled: bool) -> bool:
    """Turn WebKit's window-occlusion detection on or off for one WKWebView.

    Returns True when the switch was applied, False when there is no web view or this
    WebKit lacks the selector (the window then behaves as before: blank while covered).
    """
    if webview_obj is None:
        logger.info("first paint: no WKWebView yet; occlusion detection left as is")
        return False
    if not webview_obj.respondsToSelector_(OCCLUSION_SELECTOR):
        logger.warning(
            "first paint: this WebKit has no %s; a window opened behind others stays blank until uncovered",
            OCCLUSION_SELECTOR,
        )
        return False
    webview_obj._setWindowOcclusionDetectionEnabled_(enabled)
    return True


def _cocoa_webview(window: Any) -> Any:
    from webview.platforms.cocoa import BrowserView

    browser = BrowserView.instances.get(window.uid)
    return None if browser is None else browser.webview


def _call_on_main(fn: Callable[[], Any]) -> None:
    from PyObjCTools import AppHelper

    AppHelper.callAfter(fn)


def paint_first_frame_while_occluded(
    window: Any,
    *,
    native_webview: Callable[[Any], Any] = _cocoa_webview,
    call_on_main: Callable[[Callable[[], Any]], None] = _call_on_main,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wire `window` (a pywebview Window) so it paints its first frame even when it
    opens fully covered. Call before `webview.start()`."""

    def _before_show() -> None:
        # pywebview runs before_show synchronously on the main thread, before the window
        # is ordered in: the switch is set before WebKit first sees the occlusion state.
        set_occlusion_detection(native_webview(window), False)

    def _loaded() -> None:
        # pywebview runs `loaded` on a worker thread, so the bounded poll blocks nothing.
        try:
            window.evaluate_js(ARM_FIRST_FRAMES_JS)
            for _ in range(MAX_POLLS):
                if window.evaluate_js(FIRST_FRAMES_DONE_JS):
                    break
                sleep(POLL_INTERVAL_S)
            else:
                logger.warning("first paint: no animation frame in %.1fs; restoring occlusion detection", POLL_LIMIT_S)
        finally:
            # A wait that raises (the window closed mid-load) still hands detection back;
            # pywebview logs the exception itself.
            call_on_main(lambda: set_occlusion_detection(native_webview(window), True))

    window.events.before_show += _before_show
    window.events.loaded += _loaded
