"""
Regression guard for the frameless window drag mechanism.

The window drag is handled by pywebview's built-in drag-region
mechanism (`gui/web_ui/index.html` <header class="integrated-appbar
pywebview-drag-region">) + the cocoa `BrowserView.move` patched
in `gui/gui_main.py` per upstream issue #1820 (May 2026).

This file contains static-analysis guards. The actual drag behavior
can only be verified by manual test on a real macOS window, because:

1. pywebview's bundled `customize.js` is only injected by pywebview's
   `start()` (not by loading the HTML in a plain browser), so a
   Playwright test that serves the HTML over HTTP will not exercise
   the drag handler.
2. The Cocoa `setFrameTopLeftPoint_` call is in Python and only
   takes effect on a real NSWindow, so it cannot be observed from
   a headless browser.
3. The upstream #1820 patch is a no-op on single-monitor setups
   (the most common test environment), so a CI test on single-
   monitor would not detect a regression in the multi-monitor
   coordinate handling.

The structural guards below catch the regressions that have actually
broken the drag in prior rounds (custom JS handler re-added, custom
Python `drag_window` re-added, `pywebview-drag-region` class dropped,
#1820 patch removed or wrong).
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "divoom_gui" / "web_ui" / "index.html"
def _cat(paths: list[Path]) -> str:
    parts = []
    for p in paths:
        if p.exists():
            parts.append(p.read_text())
    return "\n".join(parts)

APP_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "app_globals.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "app_init.js",
])
GUI_MAIN = REPO_ROOT / "divoom_gui" / "gui_main.py"


def _read_cocoa_browser_view_move_source():
    """Return the source text of pywebview's cocoa BrowserView.move,
    or None if the cocoa backend is not importable in this test
    environment (e.g. CI on Linux)."""
    try:
        import inspect
        from webview.platforms.cocoa import BrowserView
        return inspect.getsource(BrowserView.move)
    except (ImportError, OSError, TypeError):
        return None


def test_appbar_has_pywebview_drag_region_class():
    """The appbar <header> must carry `pywebview-drag-region` so
    pywebview's customize.js (webview/js/customize.js:69-89) treats
    it as a native drag region and dispatches `pywebviewMoveWindow`
    on mousedown. Combined with the #1820 patch in gui_main.py,
    this is the only working drag path on macOS."""
    html = INDEX_HTML.read_text()
    m = re.search(r'<header[^>]*class="([^"]*)"[^>]*>', html)
    assert m is not None, "could not find <header> in gui/web_ui/index.html"
    classes = m.group(1).split()
    assert "integrated-appbar" in classes, (
        "header is missing 'integrated-appbar' class"
    )
    assert "pywebview-drag-region" in classes, (
        "header is missing 'pywebview-drag-region' class — pywebview will "
        "not start a native window drag from the appbar. Add it to use "
        "the bundled drag-region mechanism (with the #1820 patch)."
    )


def test_gui_main_patches_cocoa_drag():
    """gui_main.py must apply the upstream #1820 monkey-patch to
    BrowserView.move on macOS, but only when the bug is still present
    in the installed pywebview. The patch is gated by
    _pywebview_1820_bug_present() so it self-deactivates when
    pywebview ships the upstream fix.

    The patched move implementation must drop the
    `self.screen.origin.x` term that causes the coordinate double-
    count on multi-monitor setups."""
    src = GUI_MAIN.read_text()
    assert "_pywebview_1820_bug_present" in src, (
        "gui_main.py must define the _pywebview_1820_bug_present() "
        "detection helper that gates the monkey-patch on whether the "
        "upstream bug is still in the installed pywebview."
    )
    assert "BrowserView.move = _patched_move" in src, (
        "gui_main.py must apply the pywebview #1820 multi-monitor drag patch "
        "(`BrowserView.move = _patched_move`). Without it, the window jumps "
        "off-screen on multi-monitor macOS setups."
    )
    # The patched move body must NOT contain the bug term
    # `self.screen.origin.x + x` — that's the very thing the patch
    # is supposed to drop. The bug token IS allowed elsewhere in
    # the file (in the detection helper's comment + token, since
    # the token is the detection signal).
    patched_block = src.split("def _patched_move")[1].split("BrowserView.move = _patched_move")[0]
    assert "self.screen.origin.x + x" not in patched_block, (
        "the #1820 patch body must drop the `self.screen.origin.x + x` term — "
        "keeping it causes the coordinate double-count."
    )


def test_app_js_has_no_custom_drag_handler():
    """app.js must NOT have a custom drag handler. The drag is
    delegated to pywebview's bundled drag-region mechanism; the
    only Python path that should exist is the #1820 patch in
    gui_main.py.

    A custom JS drag handler (mousedown/mousemove/mouseup on
    .integrated-appbar with pywebview.api.drag_window calls) was
    the source of multiple regressions. Replaced by the native
    pywebview drag-region (with the cocoa #1820 patch).
    """
    src = APP_JS
    assert "pywebview.api.drag_window" not in src, (
        "divoom_gui/web_ui/app.js still calls pywebview.api.drag_window — this is "
        "an OLD custom drag path. Delete the drag handler block; the "
        "window drag is handled natively by pywebview's drag region."
    )
    assert 'e.target.closest(".integrated-appbar")' not in src, (
        "divoom_gui/web_ui/app.js still walks the DOM for .integrated-appbar to "
        "attach a drag handler — this is the OLD custom drag path. "
        "pywebview handles drag detection natively for elements with "
        "the .pywebview-drag-region class."
    )


def test_gui_api_has_no_drag_window():
    """gui_api.py must NOT define a custom drag_window method. The
    drag is handled by pywebview's bundled mechanism + the #1820
    patch in gui_main.py. A custom Python drag_window would be
    dead code (and is the source of multiple regressions)."""
    from divoom_gui import gui_api as _api_mod
    assert not hasattr(_api_mod.DivoomGuiAPI, "drag_window"), (
        "DivoomGuiAPI.drag_window still exists — this is the OLD custom "
        "Python drag path. Delete it; pywebview handles drag natively."
    )


def test_pywebview_1820_detection_matches_source():
    """The _pywebview_1820_bug_present() helper in gui_main.py must
    agree with the actual source of pywebview's cocoa BrowserView.move.

    This is the canary for upstream self-deactivation: when pywebview
    ships the fix for #1820, the literal token
    `self.screen.origin.x + x` will no longer be in BrowserView.move's
    source, our detection will return False, and the monkey-patch
    will be skipped.

    If this test fails after a pywebview upgrade, it means the
    detection token in gui_main.py no longer matches the bug
    signature in the new pywebview source. Update the detection
    token to match the new bug pattern (or, ideally, confirm the
    bug is fixed and remove the monkey-patch entirely)."""
    cocoa_src = _read_cocoa_browser_view_move_source()
    if cocoa_src is None:
        import pytest
        pytest.skip("pywebview cocoa backend not importable in this env")

    # The exact bug token from issue #1820 (May 2026).
    BUG_TOKEN = "self.screen.origin.x + x"

    # What the source actually says.
    actual_bug_present = BUG_TOKEN in cocoa_src

    # What our detection helper says.
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "divoom_gui"))
    # Import the helper without triggering main()/webview.start().
    import importlib
    if "gui_main" in sys.modules:
        importlib.reload(sys.modules["gui_main"])
    from gui_main import _pywebview_1820_bug_present
    detected_bug_present = _pywebview_1820_bug_present()

    assert detected_bug_present == actual_bug_present, (
        f"Detection mismatch: helper says bug_present={detected_bug_present} "
        f"but the actual pywebview cocoa source has the bug token "
        f"{BUG_TOKEN!r} present={actual_bug_present}. "
        f"--- BrowserView.move source ---\n{cocoa_src}\n--- end source ---\n"
        f"This usually means pywebview upstream changed the bug "
        f"signature. If the fix has shipped, the monkey-patch will "
        f"auto-deactivate and you can delete the workaround from "
        f"gui_main.py entirely. If pywebview restructured the code "
        f"but kept the same bug, update the BUG_TOKEN in the "
        f"detection helper to match the new signature."
    )


def test_pywebview_1820_detection_simulates_upstream_fix():
    """Simulate pywebview shipping the #1820 fix and confirm the
    detection returns False (i.e. the monkey-patch would be
    skipped on a fixed pywebview). This is the self-deactivation
    contract.

    We monkey-patch webview.platforms.cocoa.BrowserView.move with
    the upstream-recommended fix shape, then call the detection
    helper. If the helper still returns True after the simulation,
    the detection token is too lenient and a real upstream fix
    would not auto-deactivate the patch."""
    try:
        from webview.platforms import cocoa as _cocoa
    except ImportError:
        import pytest
        pytest.skip("pywebview cocoa backend not importable in this env")

    # Upstream-recommended fix shape (per the bug description's
    # "Suggested fix" section): drop the `self.screen.origin.x` term.
    def _fixed_move(self, x, y):
        flipped_y = self.screen.size.height - y
        self.window.setFrameTopLeftPoint_(
            _cocoa.AppKit.NSPoint(x, self.screen.origin.y + flipped_y)
        )

    original = _cocoa.BrowserView.move
    _cocoa.BrowserView.move = _fixed_move
    try:
        # Re-import the helper so it picks up the new source.
        sys.path.insert(0, str(REPO_ROOT))
        sys.path.insert(0, str(REPO_ROOT / "divoom_gui"))
        import importlib
        if "gui_main" in sys.modules:
            importlib.reload(sys.modules["gui_main"])
        from gui_main import _pywebview_1820_bug_present

        detected = _pywebview_1820_bug_present()
        assert detected is False, (
            "Detection still says the bug is present after simulating "
            "the upstream fix. The detection token is too lenient and "
            "the monkey-patch will not auto-deactivate when pywebview "
            "ships the real fix. Tighten the token in gui_main.py."
        )
    finally:
        _cocoa.BrowserView.move = original
