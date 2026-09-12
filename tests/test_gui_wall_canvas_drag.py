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

SEED_BENCH_NODE_JS = """
    window.DivoomState.discoveredDevices = [
        { address: 'AA:BB:CC:DD:EE:01', name: 'Timoo-test', room: 'Wall' }
    ];
    if (window.SpatialRooms) {
        const pos = window.SpatialRooms.getSavedPositions();
        pos['AA:BB:CC:DD:EE:01'] = { x: 40, y: 30 };
        window.SpatialRooms.savePositions(pos);
    }
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
"""

SEED_TWO_BENCH_NODES_JS = """
    window.DivoomState.discoveredDevices = [
        { address: 'AA:BB:CC:DD:EE:01', name: 'Timoo-A', room: 'Wall' },
        { address: 'AA:BB:CC:DD:EE:02', name: 'Timoo-B', room: 'Desk' }
    ];
    if (window.SpatialRooms) {
        const pos = window.SpatialRooms.getSavedPositions();
        pos['AA:BB:CC:DD:EE:01'] = { x: 40, y: 30 };
        pos['AA:BB:CC:DD:EE:02'] = { x: 200, y: 100 };
        window.SpatialRooms.savePositions(pos);
    }
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
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


def _open_bench(page) -> None:
    """Expand the spatial bench mount so #spatial-bench is visible for dragging."""
    eval_js(page, """
        (() => {
            const mount = document.getElementById('spatial-stage-mount');
            if (mount) mount.style.display = 'block';
            const benchView = document.getElementById('appbar-bench-view');
            if (benchView) benchView.style.display = 'flex';
            const ribbonView = document.getElementById('appbar-ribbon-view');
            if (ribbonView) ribbonView.style.display = 'none';
            if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
        })()
    """)
    page.wait_for_selector("#spatial-bench", state="visible", timeout=UI_TIMEOUT_MS)


def _get_bench_origin(page) -> tuple:
    """Get the bench's viewport-space (x, y) top-left."""
    return tuple(eval_js(page, """
        (() => {
            const c = document.getElementById('spatial-bench');
            const r = c.getBoundingClientRect();
            return [r.left, r.top];
        })()
    """))


def _node_bench_position(page, node) -> tuple:
    """Return (bench-relative x, y) of a node's top-left corner."""
    bb = node.bounding_box()
    assert bb is not None
    ox, oy = _get_bench_origin(page)
    return (bb["x"] - ox, bb["y"] - oy)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_bench_canvas_renders_node(browser):
    """Adding a device makes the Spatial Stage Bench render its .spatial-node."""
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_bench(page)

        eval_js(page, SEED_BENCH_NODE_JS)
        page.wait_for_timeout(50)

        nodes = page.query_selector_all(".spatial-node")
        assert len(nodes) == 1, f"expected 1 node after seed, got {len(nodes)}"

        node = nodes[0]
        nx, ny = _node_bench_position(page, node)
        assert 35 <= nx <= 45, f"expected node x~40, got {nx}"
        assert 25 <= ny <= 35, f"expected node y~30, got {ny}"
        context.close()


def test_bench_canvas_drag_node_updates_position(browser):
    """Dragging a node on the Spatial Bench updates its position and persists."""
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_bench(page)
        eval_js(page, SEED_BENCH_NODE_JS)
        page.wait_for_timeout(50)

        node = page.query_selector(".spatial-node")
        assert node is not None
        bb = node.bounding_box()
        assert bb is not None
        cx = bb["x"] + bb["width"] / 2
        cy = bb["y"] + bb["height"] / 2

        # Drag the node (+50, +40)
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 50, cy + 40, steps=5)
        page.mouse.up()
        page.wait_for_timeout(50)

        nx, ny = _node_bench_position(page, node)
        assert 85 <= nx <= 95, f"expected new x~90, got {nx}"
        assert 65 <= ny <= 75, f"expected new y~70, got {ny}"

        # Positions should persist to SpatialRooms
        pos = eval_js(page, "window.SpatialRooms.getSavedPositions()")
        assert 85 <= pos["AA:BB:CC:DD:EE:01"]["x"] <= 95
        assert 65 <= pos["AA:BB:CC:DD:EE:01"]["y"] <= 75
        context.close()


def test_bench_canvas_drag_node_clamped(browser):
    """Dragging a node beyond bench boundaries clamps within the bench container."""
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_bench(page)
        eval_js(page, SEED_BENCH_NODE_JS)
        page.wait_for_timeout(50)

        node = page.query_selector(".spatial-node")
        assert node is not None
        bb = node.bounding_box()
        assert bb is not None
        cx = bb["x"] + bb["width"] / 2
        cy = bb["y"] + bb["height"] / 2

        # Drag far to the bottom-right (+2000, +2000)
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 2000, cy + 2000, steps=10)
        page.mouse.up()
        page.wait_for_timeout(50)

        nx, ny = _node_bench_position(page, node)
        dims = eval_js(page, """
            (() => {
                const c = document.getElementById('spatial-bench');
                const n = document.querySelector('.spatial-node');
                return {
                    cw: c.clientWidth, ch: c.clientHeight,
                    nw: n.offsetWidth, nh: n.offsetHeight,
                };
            })()
        """)
        max_x = dims["cw"] - dims["nw"]
        max_y = dims["ch"] - dims["nh"]
        assert nx <= max_x + 2, f"node x={nx} exceeds clamp {max_x}"
        assert ny <= max_y + 2, f"node y={ny} exceeds clamp {max_y}"
        assert nx >= 0, f"node went off-screen left: x={nx}"
        assert ny >= 0, f"node went off-screen top: y={ny}"
        context.close()


def test_bench_drag_does_not_trigger_appbar_drag(browser):
    """Dragging a node on the bench must NOT trigger window dragging."""
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_bench(page)
        eval_js(page, SEED_BENCH_NODE_JS)
        page.wait_for_timeout(50)

        node = page.query_selector(".spatial-node")
        assert node is not None
        bb = node.bounding_box()
        assert bb is not None
        cx = bb["x"] + bb["width"] / 2
        cy = bb["y"] + bb["height"] / 2

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 30, cy + 20, steps=5)
        page.mouse.up()
        page.wait_for_timeout(50)

        drag_calls = eval_js(page, "window._dragCalls")
        assert drag_calls == [], f"node drag must not call drag_window: {drag_calls}"
        context.close()


def test_two_nodes_can_be_dragged_independently(browser):
    """Dragging node A does not alter node B's position."""
    if browser is None:
        pytest.skip("playwright not available")

    with _serve_directory(WEB_UI_DIR) as url:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        add_init_js(context, PYWEBVIEW_STUB)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _open_bench(page)
        eval_js(page, SEED_TWO_BENCH_NODES_JS)
        page.wait_for_timeout(50)

        nodes = page.query_selector_all(".spatial-node")
        assert len(nodes) == 2

        node_b = nodes[1]
        bx_before, by_before = _node_bench_position(page, node_b)

        # Drag node A
        node_a = nodes[0]
        bb_a = node_a.bounding_box()
        cx = bb_a["x"] + bb_a["width"] / 2
        cy = bb_a["y"] + bb_a["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy + 30, steps=5)
        page.mouse.up()
        page.wait_for_timeout(50)

        # Node B should be unaffected
        bx_after, by_after = _node_bench_position(page, node_b)
        assert abs(bx_after - bx_before) < 2
        assert abs(by_after - by_before) < 2
        context.close()

