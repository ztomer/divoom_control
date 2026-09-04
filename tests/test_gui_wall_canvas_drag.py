"""
Instrumented tests for the wall canvas drag handler.

User requirement (2026-06-05): "adding screens to the wall should be possible,
and they should be moveable within the canvas (so we'll be able to arrange
them), and this requirement should be non mutually exclusive with moving
the app window."

This test file verifies:
  1. Wall screens can be added to the canvas.
  2. Wall screens can be moved within the canvas (drag works, position
     updates, clamped to canvas bounds).
  3. The wall-screen drag and the appbar-window-drag are non-mutually-
     exclusive: clicking on a wall screen does NOT trigger a window
     drag, and clicking on the appbar does NOT affect wall screens.

Requires: pip install playwright camoufox && python3 -m camoufox fetch
Runs in the normal pytest suite. Skips if Playwright is unavailable.
"""
import contextlib
import http.server
import socket
import socketserver
import threading
import time
from pathlib import Path

import pytest
from tests.support.browser import add_init_js, eval_js, launch_sync, UI_TIMEOUT_MS

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


WEB_UI_DIR = Path(__file__).resolve().parents[1] / "divoom_gui" / "web_ui"


def _free_port() -> int:
    """Bind to port 0, read assigned port, release."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


@contextlib.contextmanager
def _serve_directory(directory: Path):
    """Serve `directory` over HTTP on a free port. Yields the base URL."""
    port = _free_port()
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(directory), **kw)
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/index.html"
    finally:
        httpd.shutdown()
        httpd.server_close()


pytestmark = pytest.mark.skipif(
    sync_playwright is None,
    reason="playwright not installed (pip install playwright camoufox)",
)


@pytest.fixture(scope="module")
def browser():
    """Single browser instance for the whole test module."""
    if sync_playwright is None:
        yield None
        return
    with sync_playwright() as p:
        with launch_sync(p) as b:
            yield b


# ── JS helpers (executed in the page context) ────────────────────────────────

SEED_WALL_NODE_JS = """
    // Seed one node into the arranger's state and re-render.
    window.DivoomState.assignedSlots['AA:BB:CC:DD:EE:01'] = {
        x: 40, y: 30, width: 80, height: 80, size: 16,
        name: 'Timoo-test', image: 'assets/timoo.png'
    };
    window.renderArrangerCanvas();
"""

SEED_TWO_WALL_NODES_JS = """
    window.DivoomState.assignedSlots['AA:BB:CC:DD:EE:01'] = {
        x: 40, y: 30, width: 80, height: 80, size: 16,
        name: 'Timoo-A', image: 'assets/timoo.png'
    };
    window.DivoomState.assignedSlots['AA:BB:CC:DD:EE:02'] = {
        x: 200, y: 100, width: 80, height: 80, size: 16,
        name: 'Timoo-B', image: 'assets/timoo.png'
    };
    window.renderArrangerCanvas();
"""


PYWEBVIEW_STUB = """
    window._dragCalls = [];
    window._syncCalls = [];
    window.pywebview = {
        api: {
            minimize_window: () => {},
            maximize_window: () => {},
            close_window: () => {},
            drag_window: (dx, dy) => window._dragCalls.push([dx, dy]),
            update_wall_slots: (slotsJson) => window._syncCalls.push(JSON.parse(slotsJson)),
        }
    };
"""


ACTIVATE_WALL_TAB_JS = """
    // The wall canvas lives inside #display-wall which is hidden by default
    // (display: none). Add the .active class so it's visible for testing.
    //
    // Throws rather than silently doing nothing when the tab is absent. A
    // no-op here left the wait_for_selector on #arranger-canvas to time out
    // opaquely -- naming the canvas, not the missing tab that caused it.
    const wallTab = document.getElementById('display-wall');
    if (!wallTab) throw new Error('#display-wall not in the DOM - cannot activate the wall tab');
    wallTab.classList.add('active');
"""


def _open_wall_tab(page) -> None:
    """Navigate to the display-wall tab so the arranger canvas is visible.

    The wall canvas is inside #display-wall which is `display: none` by
    default (see gui/web_ui/sidebar.css .tab-content { display: none; }).
    Tests must activate the tab before interacting with the canvas.
    """
    page.wait_for_selector("#arranger-canvas", state="attached", timeout=UI_TIMEOUT_MS)
    eval_js(page, ACTIVATE_WALL_TAB_JS)
    page.wait_for_selector("#arranger-canvas", state="visible", timeout=UI_TIMEOUT_MS)


# ── Tests ────────────────────────────────────────────────────────────────────


def _get_canvas_origin(page) -> tuple:
    """Get the canvas's viewport-space (x, y) top-left.

    The wall canvas is inside the display-wall tab, which has its own
    offset in the viewport. The slot.x/y values are canvas-relative,
    but bounding_box() returns viewport-absolute. We subtract the
    canvas origin to get canvas-relative coordinates.
    """
    return tuple(eval_js(page, """
        (() => {
            const c = document.getElementById('arranger-canvas');
            const r = c.getBoundingClientRect();
            return [r.left, r.top];
        })()
    """))


def _node_canvas_position(page, node) -> tuple:
    """Return (canvas-relative x, y) of a wall node's top-left corner."""
    bb = node.bounding_box()
    assert bb is not None
    ox, oy = _get_canvas_origin(page)
    return (bb["x"] - ox, bb["y"] - oy)


def test_wall_canvas_renders_added_node(browser):
    """Adding a node to DivoomState.assignedSlots makes the canvas render it.

    User requirement: "adding screens to the wall should be possible".
    We seed the state directly (the Add button's popup flow is too
    dialog-heavy to test in headless; the popup calls renderArrangerCanvas
    on confirm — we test the post-confirm state here).
    """
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_wall_tab(page)

        # No nodes yet.
        nodes = page.query_selector_all(".arranger-node")
        assert len(nodes) == 0, f"expected empty canvas, got {len(nodes)} nodes"

        # Seed a node and re-render.
        eval_js(page, SEED_WALL_NODE_JS)
        page.wait_for_timeout(50)

        nodes = page.query_selector_all(".arranger-node")
        assert len(nodes) == 1, f"expected 1 node after seed, got {len(nodes)}"

        # The node should be at canvas-relative (40, 30) per our seed.
        node = nodes[0]
        nx, ny = _node_canvas_position(page, node)
        assert 35 <= nx <= 45, f"expected node x~40, got {nx}"
        assert 25 <= ny <= 35, f"expected node y~30, got {ny}"
        context.close()


def test_wall_canvas_drag_node_updates_position(browser):
    """Dragging a wall node within the canvas updates its position.

    User requirement: "they should be moveable within the canvas".
    We seed a node at (40, 30), drag it (+50, +40), and verify the new
    canvas-relative position matches the expected (90, 70).
    """
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_wall_tab(page)
        eval_js(page, SEED_WALL_NODE_JS)
        page.wait_for_timeout(50)

        node = page.query_selector(".arranger-node")
        assert node is not None
        bb = node.bounding_box()
        assert bb is not None
        cx = bb["x"] + bb["width"] / 2
        cy = bb["y"] + bb["height"] / 2

        # Drag the node (+50, +40).
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 50, cy + 40, steps=5)
        page.mouse.up()
        page.wait_for_timeout(50)

        # Verify the new canvas-relative position is roughly (40+50, 30+40) = (90, 70).
        nx, ny = _node_canvas_position(page, node)
        assert 85 <= nx <= 95, f"expected new x~90, got {nx}"
        assert 65 <= ny <= 75, f"expected new y~70, got {ny}"

        # The state should be updated too.
        slots = eval_js(page, "window.DivoomState.assignedSlots")
        slot = slots["AA:BB:CC:DD:EE:01"]
        assert 85 <= slot["x"] <= 95, f"expected slot.x~90, got {slot['x']}"
        assert 65 <= slot["y"] <= 75, f"expected slot.y~70, got {slot['y']}"
        context.close()


def test_wall_canvas_drag_node_clamped_to_canvas(browser):
    """Dragging a wall node beyond the canvas boundaries clamps it.

    The drag handler at gui/web_ui/app.js:175-178 clamps to [0, maxLeft]
    and [0, maxTop] so nodes don't get lost off-screen.
    """
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_wall_tab(page)
        eval_js(page, SEED_WALL_NODE_JS)
        page.wait_for_timeout(50)

        node = page.query_selector(".arranger-node")
        assert node is not None
        bb = node.bounding_box()
        assert bb is not None
        cx = bb["x"] + bb["width"] / 2
        cy = bb["y"] + bb["height"] / 2

        # Drag WAY off to the bottom-right (+2000, +2000). Should clamp to canvas.
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 2000, cy + 2000, steps=10)
        page.mouse.up()
        page.wait_for_timeout(50)

        nx, ny = _node_canvas_position(page, node)
        # The JS clamp uses canvas.clientWidth - node.clientWidth.
        # .arranger-node has a 2px border, so clientWidth is 4 less than the
        # declared 80px width. Read both values from the live DOM to assert
        # the actual clamp, not a hardcoded number.
        dims = eval_js(page, """
            (() => {
                const c = document.getElementById('arranger-canvas');
                const n = document.querySelector('.arranger-node');
                return {
                    cw: c.clientWidth, ch: c.clientHeight,
                    nw: n.clientWidth, nh: n.clientHeight,
                };
            })()
        """)
        # Node should be clamped to (canvas - node) on each axis.
        # Allow 2px tolerance for subpixel rounding between
        # getBoundingClientRect (float) and style.left (int).
        max_x = dims["cw"] - dims["nw"]
        max_y = dims["ch"] - dims["nh"]
        assert nx <= max_x + 2, (
            f"node x={nx} exceeds clamp {max_x} (canvas cw={dims['cw']}, node nw={dims['nw']})"
        )
        assert ny <= max_y + 2, (
            f"node y={ny} exceeds clamp {max_y} (canvas ch={dims['ch']}, node nh={dims['nh']})"
        )
        # Node should NOT be at negative coordinates.
        assert nx >= 0, f"node went off-screen left: x={nx}"
        assert ny >= 0, f"node went off-screen top: y={ny}"
        context.close()


def test_wall_drag_does_not_trigger_appbar_drag(browser):
    """User requirement: "non mutually exclusive with moving the app window".

    Dragging a wall screen must NOT trigger the appbar's drag handler.
    The wall drag mutates DOM and updates DivoomState. The appbar drag
    is handled natively by pywebview (pywebview-drag-region class +
    pywebviewMoveWindow from webview/js/customize.js). They are
    independent code paths; the wall drag does not invoke the appbar's
    native drag handler because the mousedown event on the wall node
    is not on a .pywebview-drag-region element.
    """
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_wall_tab(page)
        eval_js(page, SEED_WALL_NODE_JS)
        page.wait_for_timeout(50)

        # Drag the wall node. The appbar drag handler must NOT fire.
        node = page.query_selector(".arranger-node")
        assert node is not None
        bb = node.bounding_box()
        assert bb is not None
        cx = bb["x"] + bb["width"] / 2
        cy = bb["y"] + bb["height"] / 2
        nx_before, ny_before = _node_canvas_position(page, node)
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 30, cy + 20, steps=5)
        page.mouse.up()
        page.wait_for_timeout(50)

        # CRITICAL: drag_window should NOT have been called.
        drag_calls = eval_js(page, "window._dragCalls")
        assert drag_calls == [], (
            f"wall drag must NOT call drag_window, but got {drag_calls}. "
            f"This is the non-conflict requirement."
        )

        # The wall node DID move, however.
        nx_after, ny_after = _node_canvas_position(page, node)
        assert abs(nx_after - nx_before) > 1 or abs(ny_after - ny_before) > 1, (
            f"wall node should have moved: ({nx_before}, {ny_before}) → ({nx_after}, {ny_after})"
        )
        context.close()


def test_appbar_drag_does_not_affect_wall_node(browser):
    """User requirement: "non mutually exclusive with moving the app window".

    Dragging the appbar must NOT move wall nodes. The appbar drag is
    handled natively by pywebview (pywebview-drag-region class on
    <header class="integrated-appbar pywebview-drag-region">,
    dispatched via pywebviewMoveWindow from webview/js/customize.js);
    the wall nodes' positions should be unchanged.
    """
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(".integrated-appbar", state="visible", timeout=UI_TIMEOUT_MS)
        _open_wall_tab(page)
        eval_js(page, SEED_WALL_NODE_JS)
        page.wait_for_timeout(50)

        # Record wall node position before appbar drag.
        node = page.query_selector(".arranger-node")
        assert node is not None
        nx_before, ny_before = _node_canvas_position(page, node)

        # Drag the appbar.
        spacer = page.query_selector(".appbar-drag-spacer")
        target = spacer if spacer else page.query_selector(".integrated-appbar")
        assert target is not None
        ab = target.bounding_box()
        assert ab is not None
        ax = ab["x"] + ab["width"] / 2
        ay = ab["y"] + ab["height"] / 2
        page.mouse.move(ax, ay)
        page.mouse.down()
        page.mouse.move(ax + 60, ay + 30, steps=5)
        page.mouse.up()
        page.wait_for_timeout(50)

        # The wall node's position should be UNCHANGED. The appbar drag
        # is handled by pywebview's native backend (not via a JS API
        # call to drag_window), so we cannot assert that pywebview.api
        # was called; we assert the user-visible invariant: wall
        # nodes stay put while the appbar is dragged.
        nx_after, ny_after = _node_canvas_position(page, node)
        assert abs(nx_after - nx_before) < 1, (
            f"wall node x changed during appbar drag: {nx_before} → {nx_after}"
        )
        assert abs(ny_after - ny_before) < 1, (
            f"wall node y changed during appbar drag: {ny_before} → {ny_after}"
        )
        context.close()


def test_wall_remove_button_does_not_start_drag(browser):
    """Clicking the × button on a wall node removes it without starting a drag.

    Regression guard for the e.stopPropagation() at app.js:160.
    """
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_wall_tab(page)
        eval_js(page, SEED_TWO_WALL_NODES_JS)
        page.wait_for_timeout(50)

        # Should be 2 nodes.
        nodes = page.query_selector_all(".arranger-node")
        assert len(nodes) == 2

        # Click the × button on the first node.
        remove_btns = page.query_selector_all(".arranger-node-remove")
        assert len(remove_btns) == 2
        page.mouse.move(
            remove_btns[0].bounding_box()["x"] + 5,
            remove_btns[0].bounding_box()["y"] + 5,
        )
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(50)

        # Should be 1 node left.
        nodes = page.query_selector_all(".arranger-node")
        assert len(nodes) == 1, f"expected 1 node after remove, got {len(nodes)}"

        # No drag_window call.
        drag_calls = eval_js(page, "window._dragCalls")
        assert drag_calls == [], (
            f"× click should not start a drag, but drag_window was called: {drag_calls}"
        )
        context.close()
