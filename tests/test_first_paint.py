"""DV.BGLAUNCH: a Control Center window that opens behind other windows (`open -g`, every
`goh ship` relaunch) paints its first frame instead of staying blank.

Unit layer (always runs): divoom_gui.first_paint turns WebKit's occlusion detection off
before the first show and never back on (0.45.3 restored it after two frames, and a covered
window went blank ~20 minutes later); occlusion changes reach the page, whose render loop
stops while covered; gui_main wires it.

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
        self.native_js = []

    def respondsToSelector_(self, sel):
        return self.has_selector and sel == first_paint.OCCLUSION_SELECTOR

    def _setWindowOcclusionDetectionEnabled_(self, enabled):
        self.calls.append(enabled)

    def evaluateJavaScript_completionHandler_(self, script, handler):
        self.native_js.append(script)


class _FakeWindow:
    def __init__(self):
        self.events = types.SimpleNamespace(before_show=_Event(), loaded=_Event())
        self.js = []

    def evaluate_js(self, script):
        self.js.append(script)
        return True


def _wire(window, webview_obj, covered_now=False):
    """Returns the occlusion callbacks subscribed (call one with True/False to simulate a change)."""
    observers = []
    first_paint.keep_painting_while_occluded(
        window,
        native_webview=lambda w: webview_obj,
        native_window=lambda w: "the NSWindow",
        observe_occlusion=lambda nswindow, cb: observers.append((nswindow, cb)) or "token",
        is_covered=lambda nswindow: covered_now,
    )
    return observers


def test_detection_is_off_before_first_show_and_never_turned_back_on():
    """The 0.45.3 restore after two frames is the defect: a covered window is a hidden page,
    and WebKit drops a hidden page's layers (blank ~20 min into being covered)."""
    window, wv = _FakeWindow(), _FakeWebView()
    _wire(window, wv)

    window.events.before_show.fire()
    assert wv.calls == [False], "occlusion detection must be off before the window is first shown"
    window.events.loaded.fire()
    assert wv.calls == [False], "detection must stay off: turning it back on blanks a covered window"


def test_a_cover_and_an_uncover_reach_the_page():
    window, wv = _FakeWindow(), _FakeWebView()
    observers = _wire(window, wv)
    window.events.before_show.fire()
    assert [w for w, _ in observers] == ["the NSWindow"], "the window's occlusion changes must be observed"
    observers[0][1](True)
    observers[0][1](False)
    assert wv.native_js == [first_paint.covered_js(True), first_paint.covered_js(False)]
    assert "window.__divoomCovered = true" in first_paint.covered_js(True)
    assert first_paint.COVERED_EVENT in first_paint.covered_js(False)


@pytest.mark.parametrize("covered", [True, False])
def test_a_loaded_page_is_told_the_windows_state_at_load(covered):
    """Measured: a window covered from its first show got no occlusion notification at all,
    so the page must be told the state when it loads, read from the window, not remembered."""
    window, wv = _FakeWindow(), _FakeWebView()
    _wire(window, wv, covered_now=covered)
    window.events.before_show.fire()
    window.events.loaded.fire()
    assert window.js == [first_paint.covered_js(covered)]


def test_the_default_seams_name_pywebviews_nswindow_not_the_web_views():
    """Measured in the real app: at before_show `webview.window()` is None (the web view is not
    in its window yet), so an observer built from it watched nothing. The NSWindow is
    pywebview's BrowserView.window."""
    import inspect

    src = inspect.getsource(first_paint._cocoa_window)
    assert "browser.window" in src and ".window()" not in src.split('"""')[-1].split("#")[0]
    sig = inspect.signature(first_paint.keep_painting_while_occluded)
    assert sig.parameters["native_window"].default is first_paint._cocoa_window


def test_without_the_switch_nothing_is_observed():
    window, wv = _FakeWindow(), _FakeWebView(has_selector=False)
    observers = _wire(window, wv)
    window.events.before_show.fire()
    assert observers == [] and wv.calls == []


def test_the_render_loop_stops_while_covered_and_resumes():
    """The page side reads the names first_paint.py writes (one place each), and the bench's
    render loop asks it first on every frame."""
    web = _REPO / "divoom_gui" / "web_ui"
    covered = (web / "window_covered.js").read_text()
    assert "window.__divoomCovered" in covered and f'"{first_paint.COVERED_EVENT}"' in covered
    loop = (web / "spatial_stage.js").read_text()
    loop = loop[loop.index("function renderLoop()") :][:200]
    assert "if (window.DivoomCovered?.hold(renderLoop)) return;" in loop
    html = (web / "index.html").read_text()
    assert html.index('src="window_covered.js"') < html.index('src="spatial_stage.js"')


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
    monkeypatch.setattr(first_paint, "keep_painting_while_occluded", lambda w, **kw: wired.append(w))

    with pytest.raises(SystemExit):
        gui_main.main()

    assert wired == [ctx.window], "the Control Center window must paint while it opens covered (DV.BGLAUNCH)"


# ───────────────────────────── the window itself ─────────────────────────────

_PROBE = textwrap.dedent(
    """
    import sys, webview
    sys.path.insert(0, {repo!r})
    from divoom_gui.first_paint import keep_painting_while_occluded
    html = ("<html><body style='background:#c03;margin:0'>"
            "<h1 style='color:#fff;font-size:120px'>PAINTED</h1></body></html>")
    w = webview.create_window({title!r}, html=html, width=800, height=600, background_color="#0a0b10")
    if sys.argv[1] == "fix":
        keep_painting_while_occluded(w)
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
