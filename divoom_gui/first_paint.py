"""A window that opens or stays behind other windows still holds its page (DV.BGLAUNCH).

`goh ship` relaunches the app with `open -g` (scripts/ship_install.sh), so the Control
Center opens without activating and usually lands behind the window the owner is using.
WKWebView watches its window's occlusion state; while the window is covered it treats the
page as hidden: it stops painting, and in time lets go of what it painted.

Two findings, one cause. (1) A window covered from its very first show had NO content: a
window capture (screencapture -l, a computer-use screenshot) read a uniform blank frame
(Divoom 0.45.2 under an opaque cover: 2 colours; uncovered 613). 0.45.3 turned detection off
before the first show and back ON after two frames. (2) That was not enough: the 0.45.3 ship's
own `open -g` window was blank 37 minutes later (7 colours), and a fresh one that drew 2381
colours at 15 s was blank again ~20 minutes into being covered (7 colours, measured
2026-11-11 21:41 and again 12 minutes after an activation redrew it). With detection back on,
a covered window is a hidden page, and WebKit drops a hidden page's layers.

So detection stays OFF for the window's life (`-[WKWebView
_setWindowOcclusionDetectionEnabled:]`, WKWebViewPrivate.h): WebKit always treats the page as
shown and keeps its frame. What detection was there for, throttling the bench's render loop
while covered, is done by the app itself instead: an NSWindow occlusion observer tells the
page (`window.__divoomCovered`, event `divoom:window-covered`), and spatial_stage.js's render
loop stops while covered and resumes when the window is seen again. A WebKit without the
selector degrades to the old behaviour, with a log line saying so.

Seams (tests/test_first_paint.py): `native_webview` returns the WKWebView (or None),
`observe_occlusion` subscribes a callback to the NSWindow's occlusion changes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

OCCLUSION_SELECTOR = "_setWindowOcclusionDetectionEnabled:"

# NSWindowOcclusionStateVisible: set while any part of the window can be seen.
OCCLUSION_STATE_VISIBLE = 1 << 1

COVERED_EVENT = "divoom:window-covered"


def covered_js(covered: bool) -> str:
    """The script that tells the page whether its window is covered."""
    flag = "true" if covered else "false"
    return f"window.__divoomCovered = {flag}; window.dispatchEvent(new Event('{COVERED_EVENT}')); true"


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


def _observe_occlusion(webview_obj: Any, on_change: Callable[[bool], None]) -> Any:
    """Call `on_change(covered)` on the main thread whenever the web view's window is
    covered or uncovered. Returns the observer token (kept alive by the caller)."""
    import AppKit

    nswindow = webview_obj.window()
    if nswindow is None:
        logger.warning("first paint: the web view has no window yet; the page is never told it is covered")
        return None

    def _changed(_note: Any) -> None:
        on_change(not (nswindow.occlusionState() & OCCLUSION_STATE_VISIBLE))

    return AppKit.NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
        AppKit.NSWindowDidChangeOcclusionStateNotification, nswindow, AppKit.NSOperationQueue.mainQueue(), _changed
    )


def keep_painting_while_occluded(
    window: Any,
    *,
    native_webview: Callable[[Any], Any] = _cocoa_webview,
    observe_occlusion: Callable[[Any, Callable[[bool], None]], Any] = _observe_occlusion,
) -> None:
    """Wire `window` (a pywebview Window) so it holds its page however long it is covered,
    and its page knows when it is covered. Call before `webview.start()`."""
    keep: list[Any] = []
    state = {"covered": False}

    def _covered(covered: bool) -> None:
        state["covered"] = covered
        wv = native_webview(window)
        if wv is not None:
            # Native and asynchronous: evaluate_js would wait on the main thread it runs on.
            wv.evaluateJavaScript_completionHandler_(covered_js(covered), None)

    def _before_show() -> None:
        # pywebview runs before_show synchronously on the main thread, before the window
        # is ordered in: the switch is set before WebKit first sees the occlusion state,
        # and it is never turned back on.
        wv = native_webview(window)
        if set_occlusion_detection(wv, False):
            keep.append(observe_occlusion(wv, _covered))

    def _loaded() -> None:
        # A change seen before the page's script ran was told to no page: tell this one.
        # pywebview runs `loaded` on a worker thread, where evaluate_js may wait.
        window.evaluate_js(covered_js(state["covered"]))

    window.events.before_show += _before_show
    window.events.loaded += _loaded
