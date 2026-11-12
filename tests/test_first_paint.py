"""DV.BGLAUNCH: a Control Center window that opens behind other windows (`open -g`, every
`goh ship` relaunch) paints its first frame instead of staying blank.

Unit layer (always runs): divoom_gui.first_paint turns WebKit's occlusion detection off
before the first show and back on after the page has drawn, and gui_main wires it.

Window layer (DIVOOM_WINDOW_TESTS=1, a logged-in macOS session with Screen Recording):
the finding itself. A real pywebview window opens under an opaque cover; the capture of
that window must hold the page. Without the fix the same capture is one flat colour.
"""

import os
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_gui import first_paint, gui_main  # noqa: E402
from tests.support.gui_main_fakes import _patch_main_common  # noqa: E402


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for fn in self.handlers:
            fn()


class _FakeWebView:
    def __init__(self, has_selector=True):
        self.has_selector = has_selector
        self.calls = []

    def respondsToSelector_(self, sel):
        return self.has_selector and sel == first_paint.OCCLUSION_SELECTOR

    def _setWindowOcclusionDetectionEnabled_(self, enabled):
        self.calls.append(enabled)


class _FakeWindow:
    def __init__(self, frames_after_polls=2):
        self.events = types.SimpleNamespace(before_show=_Event(), loaded=_Event())
        self.js = []
        self._polls_left = frames_after_polls

    def evaluate_js(self, script):
        self.js.append(script)
        if script == first_paint.FIRST_FRAMES_DONE_JS:
            if self._polls_left <= 0:
                return True
            self._polls_left -= 1
            return False
        return True


def _wire(window, webview_obj):
    main_queue = []
    first_paint.paint_first_frame_while_occluded(
        window,
        native_webview=lambda w: webview_obj,
        call_on_main=main_queue.append,
        sleep=lambda s: None,
    )
    return main_queue


def test_detection_is_off_before_first_show_and_back_on_after_frames():
    window, wv = _FakeWindow(frames_after_polls=2), _FakeWebView()
    main_queue = _wire(window, wv)

    window.events.before_show.fire()
    assert wv.calls == [False], "occlusion detection must be off before the window is first shown"

    window.events.loaded.fire()
    assert window.js[0] == first_paint.ARM_FIRST_FRAMES_JS
    assert window.js.count(first_paint.FIRST_FRAMES_DONE_JS) == 3, "polls until the page reports its frames"
    assert wv.calls == [False], "the restore runs on the main thread, not the loaded worker"
    for fn in main_queue:
        fn()
    assert wv.calls == [False, True]


def test_frame_wait_is_bounded():
    window, wv = _FakeWindow(frames_after_polls=10**9), _FakeWebView()
    main_queue = _wire(window, wv)
    window.events.before_show.fire()
    window.events.loaded.fire()
    polls = window.js.count(first_paint.FIRST_FRAMES_DONE_JS)
    assert polls == first_paint.MAX_POLLS == 100
    for fn in main_queue:
        fn()
    assert wv.calls == [False, True], "a page that never draws still gets occlusion detection back"


def test_frame_wait_failure_still_restores():
    window, wv = _FakeWindow(), _FakeWebView()

    def boom(script):
        raise RuntimeError("window gone")

    window.evaluate_js = boom
    main_queue = _wire(window, wv)
    with pytest.raises(RuntimeError):
        window.events.loaded.fire()
    for fn in main_queue:
        fn()
    assert wv.calls == [True]


def test_webkit_without_the_selector_degrades_with_a_reason(caplog):
    wv = _FakeWebView(has_selector=False)
    with caplog.at_level("WARNING"):
        assert first_paint.set_occlusion_detection(wv, False) is False
    assert wv.calls == []
    assert first_paint.OCCLUSION_SELECTOR in caplog.text


def test_no_webview_is_a_no_op():
    assert first_paint.set_occlusion_detection(None, False) is False


def test_gui_main_wires_first_paint_on_the_control_center_window(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    wired = []
    monkeypatch.setattr(first_paint, "paint_first_frame_while_occluded", lambda w, **kw: wired.append(w))

    with pytest.raises(SystemExit):
        gui_main.main()

    assert wired == [ctx.window], "the Control Center window must paint while it opens covered (DV.BGLAUNCH)"


# ───────────────────────────── the window itself ─────────────────────────────

_PROBE = textwrap.dedent(
    """
    import sys, webview
    sys.path.insert(0, {repo!r})
    from divoom_gui.first_paint import paint_first_frame_while_occluded
    html = ("<html><body style='background:#c03;margin:0'>"
            "<h1 style='color:#fff;font-size:120px'>PAINTED</h1></body></html>")
    w = webview.create_window({title!r}, html=html, width=800, height=600, background_color="#0a0b10")
    if sys.argv[1] == "fix":
        paint_first_frame_while_occluded(w)
    webview.start()
    """
)

_COVER = textwrap.dedent(
    """
    import sys, AppKit
    from PyObjCTools import AppHelper
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    wins = []
    for s in AppKit.NSScreen.screens():
        w = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(s.frame(), 0, 2, False)
        w.setLevel_(AppKit.NSFloatingWindowLevel)
        w.setBackgroundColor_(AppKit.NSColor.blackColor())
        w.setIgnoresMouseEvents_(True)
        w.orderFrontRegardless()
        wins.append(w)
    AppHelper.callLater(float(sys.argv[1]), AppHelper.stopEventLoop)
    AppHelper.runEventLoop()
    """
)


def _window_id(title, deadline_s=20.0):
    import Quartz

    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID):
            if w.get("kCGWindowName") == title and w.get("kCGWindowLayer") == 0:
                return int(w["kCGWindowNumber"])
        time.sleep(0.2)
    return None


def _page_fraction(png):
    """Share of the window's pixels that are the probe page's red (blank frames hold none)."""
    from PIL import Image

    im = Image.open(png).convert("RGB").resize((80, 60))
    px = [im.getpixel((x, y)) for x in range(80) for y in range(60)]
    return sum(1 for r, g, b in px if r > 150 and g < 90 and b < 110) / len(px)


def _capture_covered(tmp_path, mode):
    title = f"DV.BGLAUNCH probe {mode} {os.getpid()}"
    cover = subprocess.Popen([sys.executable, "-c", _COVER, "14"], stdin=subprocess.DEVNULL)
    probe = None
    try:
        time.sleep(1.5)
        probe = subprocess.Popen(
            [sys.executable, "-c", _PROBE.format(repo=str(_REPO), title=title), mode], stdin=subprocess.DEVNULL
        )
        wid = _window_id(title)
        assert wid is not None, "the probe window never appeared"
        time.sleep(4)
        assert cover.poll() is None, "the cover ended before the capture: the window was not covered"
        png = tmp_path / f"{mode}.png"
        subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), str(png)], check=True, stdin=subprocess.DEVNULL)
        return _page_fraction(png)
    finally:
        for p in (probe, cover):
            if p is not None:
                p.terminate()
                p.wait(timeout=10)


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("DIVOOM_WINDOW_TESTS") != "1",
    reason="opens real windows and captures them: set DIVOOM_WINDOW_TESTS=1 in a logged-in macOS session",
)
def test_a_window_opened_under_a_cover_paints_its_page(tmp_path):
    blank = _capture_covered(tmp_path, "plain")
    painted = _capture_covered(tmp_path, "fix")
    # The instrument can read blank: without the fix the covered window is one flat frame.
    assert blank < 0.05, f"calibration: the unfixed covered window should be blank, read {blank:.0%} page"
    assert painted > 0.5, f"the covered window with the fix should hold its page, read {painted:.0%} page"
