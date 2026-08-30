"""
Live widget diagnostics: load the GUI in headless Chromium, navigate to
the Live Widgets tab, and capture any console errors / pageerrors so we
can diagnose "live widgets broken" regressions empirically.

This is a diagnostic tool, not a strict assertion. It always passes
(prints what it found). Run it interactively:

    /opt/homebrew/bin/python3.14 tests/test_live_widgets_diagnostic.py -v

R13: the test SKIPS (not errors) when playwright is missing, so CI on a
host without a Chromium can still run the rest of the suite. Previously
this file did `sys.exit(2)` at import time, which crashed the entire
pytest run before any test could collect.
"""
import sys
import time
import contextlib
import http.server
import socket
import socketserver
import threading
import pytest
from pathlib import Path
from tests.support.browser import add_init_js, launch_sync

playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
sync_playwright = playwright.sync_playwright

WEB_UI_DIR = Path(__file__).resolve().parents[1] / "divoom_gui" / "web_ui"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@contextlib.contextmanager
def _serve_directory(directory: Path):
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


def main():
    if not WEB_UI_DIR.exists():
        print(f"web_ui not found at {WEB_UI_DIR}", file=sys.stderr)
        return 2

    with _serve_directory(WEB_UI_DIR) as url, sync_playwright() as p, \
         launch_sync(p) as browser:
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        # Stub a richer pywebview so the page's widget init doesn't fail
        add_init_js(ctx, """
            window._calls = {};
            function rec(name) { window._calls[name] = (window._calls[name] || 0) + 1; }
            window.pywebview = {
                api: new Proxy({}, {
                    get: (_, name) => (...args) => {
                        rec(name);
                        // Return empty JSON for the things the page tries to call
                        if (name === "get_audio_levels") return Promise.resolve('{"levels":[10,20,30,40,30,20,10,5,5,5]}');
                        if (name === "get_current_track_info") return Promise.resolve('{"track":"Test Track","artist":"Test Artist","source":"Spotify","preview":""}');
                        if (name === "get_tickers") return Promise.resolve("[]");
                        if (name === "get_ticker_preview") return Promise.resolve('{"ok":false}');
                        if (name === "get_system_stats_preview") return Promise.resolve('{"ok":true,"stats":{"cpu":42,"mem":61,"battery":88},"preview":""}');
                        if (name === "get_transport_status") return Promise.resolve('{"ble":{"available":true},"lan":{"available":true},"cloud":{"available":false},"external":{"available":true}}');
                        if (name === "load_config") return Promise.resolve('{"devices":[]}');
                        return Promise.resolve(null);
                    }
                })
            };
        """)
        page = ctx.new_page()

        console_msgs = []
        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_msgs.append((msg.type, msg.text)))

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(".nav-btn[data-tab='data-sources']", timeout=5000)
        # Click the Live Widgets tab
        page.click(".nav-btn[data-tab='data-sources']")
        time.sleep(1.0)  # let any setTimeouts fire

        # Check the cards are present
        music_card = page.query_selector("#widget-card-music")
        stock_card = page.query_selector("#widget-card-stock")
        sysmon_card = page.query_selector("#widget-card-sysmon")
        cover_img = page.query_selector("#music-cover-img")

        # Try clicking each card
        if music_card:
            music_card.click()
            time.sleep(0.3)
        if stock_card:
            stock_card.click()
            time.sleep(0.3)
        if sysmon_card:
            sysmon_card.click()
            time.sleep(0.3)

        # Check active state
        active_cards = page.query_selector_all(".widget-active")
        active_ids = [c.get_attribute("id") for c in active_cards]

        print("=" * 60)
        print(f"Page errors: {len(page_errors)}")
        for e in page_errors:
            print(f"  ! {e}")
        print()
        print(f"Console errors: {sum(1 for t, _ in console_msgs if t == 'error')}")
        for t, txt in console_msgs:
            if t in ("error", "warning"):
                print(f"  [{t}] {txt}")
        print()
        print("Element presence:")
        print(f"  music card:    {music_card is not None}")
        print(f"  stock card:    {stock_card is not None}")
        print(f"  sysmon card:   {sysmon_card is not None}")
        print(f"  cover img:     {cover_img is not None}")
        print()
        print(f"Active cards after clicks: {active_ids}")
        print()
        print(f"pywebview.api call counts: {ctx.pages[0].evaluate('window._calls') if ctx.pages else {}}")
        print("=" * 60)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
