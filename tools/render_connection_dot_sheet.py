#!/usr/bin/env python3
"""Render the connection dot's six states offscreen, the way the app draws them.

WHY OFFSCREEN, AND WHY A COMMITTED TOOL
----------------------------------------
P7.2 ended with the owner's eye: the dot's shape vocabulary is only worth
something if the owner can SEE the six states side by side and judge them.
This is that sheet, and it is a TOOL rather than a screenshot somebody took
once, because a picture that cannot be regenerated is a picture that goes
stale: the day the vocabulary changes, the sheet in docs/ is a lie until
somebody remembers to redraw it.

THE PIXELS ARE THE PRODUCT'S
----------------------------
The marks in this sheet are the app's own marks: the sheet drives the REAL
funnel (`window.setConnectionState`) in the REAL page, reads back the class
string the funnel wrote, and renders marks with that exact class string. The
CSS is the app's CSS (style.css -> transport_mark.css), the browser is the
house browser, and nothing is reimplemented here -- no canvas drawing, no
second copy of the shapes. A preview that is a parallel implementation always
drifts, and `tools/render_tray_icon.py` was rewritten for exactly that
reason (it compiles the product's own Rust renderer instead of reproducing
it).

The greyscale row is the doctrine's question -- "render it greyscale, in one
size, static: can you still tell the options apart?" -- asked by eye. The
answer is measured, not eyeballed, by tests/test_e2e_transport_mark_greyscale.py.

Usage:
    python3 tools/render_connection_dot_sheet.py --out docs/connection-dot-states.png
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

INDEX_HTML = REPO / "divoom_gui" / "web_ui" / "index.html"

#: The six live states, as the FUNNEL is told about them. The labels are the
#: sheet's own; the MARKS are whatever the funnel writes.
STATES = (
    ("disconnected", {"mode": "inactive"}),
    ("connecting", {"mode": "connecting", "mac": "AA:BB:CC:DD:EE:FF"}),
    ("linked · Bluetooth", {"mode": "active", "mac": "AA:BB:CC:DD:EE:FF"}),
    ("linked · Wi-Fi", {"mode": "active", "mac": "LAN:10.0.0.5"}),
    ("linked · Virtual Wall", {"mode": "active", "mac": "MatrixWall"}),
    ("degraded", {"mode": "degraded", "mac": "AA:BB:CC:DD:EE:FF"}),
)

# The mock backend: the sheet only needs the page to load and the funnel to
# run, and the page asks the backend for a lot of things it does not need.
MOCK_API = """
window.__api = {};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""

# The sheet itself, built in the page so the LABELS are real text rendered by
# the real font, and the marks are the real marks. Two rows: the states as the
# app draws them, and the same six in greyscale.
SHEET_JS = """
window.__buildSheet = function (states) {
    const old = document.getElementById('p72-sheet');
    if (old) old.remove();
    const dot = document.getElementById('global-status-dot');
    if (dot) dot.style.visibility = 'hidden';

    const host = document.createElement('div');
    host.id = 'p72-sheet';
    host.style.cssText = [
        'position:fixed', 'right:20px', 'bottom:20px', 'z-index:99999',
        // The dot lives on the app's PAGE surface, so the sheet's marks sit on
        // that surface too — the dimmed "no link" mark is judged against the
        // background it will really live on.
        'background:var(--bg-base,#121316)',
        'border:1px solid var(--border-color,rgba(255,255,255,0.10))',
        'border-radius:10px', 'padding:14px 16px',
        'display:flex', 'flex-direction:column', 'gap:9px',
        'font-family:var(--font-sans,sans-serif)', 'font-size:11px',
        'color:var(--text-muted,#9aa0aa)',
        'box-shadow:0 12px 34px rgba(0,0,0,0.5)'
    ].join(';');

    const title = document.createElement('div');
    title.style.cssText = 'font-weight:700;letter-spacing:0.06em;font-size:10px;'
        + 'text-transform:uppercase;opacity:0.75';
    title.textContent = "The connection dot — every state, and the same six in greyscale";
    host.appendChild(title);

    const row = (greyscale) => {
        const r = document.createElement('div');
        r.style.cssText = 'display:flex;gap:22px;align-items:center'
            + (greyscale ? ';filter:grayscale(1)' : '');
        for (const s of states) {
            const cell = document.createElement('div');
            cell.style.cssText = 'display:flex;align-items:center;gap:7px;'
                + 'min-width:132px';
            const mark = document.createElement('span');
            // The class string the funnel wrote, verbatim.
            mark.className = s.cls;
            const label = document.createElement('span');
            label.textContent = s.name;
            cell.appendChild(mark);
            cell.appendChild(label);
            r.appendChild(cell);
        }
        return r;
    };

    host.appendChild(row(false));
    host.appendChild(row(true));
    document.body.appendChild(host);
    return true;
};
"""


async def _render(out: Path) -> list[dict]:
    from playwright.async_api import async_playwright
    from tests.support.browser import add_init_js, eval_js, launch, wait_js

    async with async_playwright() as p:
        browser = await launch(p, opted_in=True)
        try:
            context = await browser.new_context(device_scale_factor=2)
            page = await context.new_page()
            await add_init_js(page, MOCK_API)
            await add_init_js(page, SHEET_JS)
            await page.goto(f"file://{INDEX_HTML}")
            await page.wait_for_load_state("domcontentloaded")
            await wait_js(page, "() => !!window.setConnectionState && !!window.__buildSheet")

            # The motion off: a pulsing dot is not reproducible, and the sheet
            # is a still frame by definition.
            await eval_js(page, """() => {
                const s = document.createElement('style');
                s.textContent = '*, *::before, *::after {'
                    + ' animation: none !important; transition: none !important; }';
                document.head.appendChild(s);
                window.DivoomState.discoveredDevices = [];
                return true;
            }""")

            states = []
            for name, args in STATES:
                await eval_js(page, "() => window.setConnectionState(%s)" % json.dumps(args))
                cls = await eval_js(
                    page, "() => document.getElementById('global-status-dot').className"
                )
                label = await eval_js(
                    page,
                    "() => document.getElementById('global-status-dot')"
                    ".getAttribute('aria-label')",
                )
                states.append({"name": name, "cls": cls, "label": label})

            await eval_js(page, "() => window.__buildSheet(%s)" % json.dumps(states))
            raw = await page.locator("#p72-sheet").screenshot()
            out.write_bytes(raw)
            return states
        finally:
            await browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        default=str(REPO / "docs" / "connection-dot-states.png"),
        help="where the sheet lands (default: docs/connection-dot-states.png)",
    )
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    states = asyncio.run(_render(out))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    for s in states:
        print(f"  {s['name']:22s} {s['cls']:42s} {s['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
