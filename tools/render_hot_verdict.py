#!/usr/bin/env python3
"""Render the hot-channel verdict line's states, the way the app draws them (U.5).

The owner picked P5.13 option A (2026-10-31): one lasting verdict line per
panel under the Update Hot Channel button, and the same line, shorter, in each
Auto-Sync row. This sheet shows every state of that line in the REAL page --
the app's CSS, the app's renderer (`hot_verdict.js`), the house browser --
driven through the same entry the daemon's `hot_status` event takes
(`window.Divoom.onHotStatus`). Nothing is redrawn here, so the sheet cannot
drift from the product.

One sheet per theme: a colour tuned for one background is unreadable on the
other, and the line's colour only reinforces its glyph and words.

Usage:
    python3 tools/render_hot_verdict.py --theme dark --out docs/assets/hot-verdict-dark.png
    python3 tools/render_hot_verdict.py --theme light --out docs/assets/hot-verdict-light.png
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

INDEX_HTML = REPO / "divoom_gui" / "web_ui" / "index.html"
PANELS = {
    "f90d2cc9-420e-65f9-9e06-f9554470fced": "Timoo-light-4",
    "a9fccb71-3d3d-4de3-c381-0de382cdc4aa": "Pixoo-1",
    "2b471aee-a9bd-24ab-7d5f-4afd88c16eeb": "Tivoo-Max-light-3",
    "e9a41e1e-9a96-974f-ce44-54f16d616f28": "Ditoo-light-2",
}
SHOWN = "f90d2cc9-420e-65f9-9e06-f9554470fced"


def states(now: int) -> list[tuple[str, dict | None]]:
    """Every line the Hot tab can show, as the daemon records it."""
    h2 = now - 2 * 3600
    return [
        ("never checked", None),
        # Oldest first: the page keeps the NEWER record, as the product must.
        ("stale (20 days)", {"at": now - 20 * 86400, "by": "button", "outcome": "ok",
                             "offered": 23, "fetched": 23, "delivered": 0}),
        ("button: up to date", {"at": h2, "by": "button", "outcome": "ok",
                                "offered": 23, "fetched": 23, "delivered": 0}),
        ("button: new files", {"at": h2, "by": "button", "outcome": "ok",
                               "offered": 23, "fetched": 23, "delivered": 3}),
        ("button: files missing", {"at": h2, "by": "button", "outcome": "ok",
                                   "offered": 23, "fetched": 19, "delivered": 0}),
        ("Sync Now: failed", {"at": h2, "by": "sync_now", "outcome": "failed",
                              "error": "device 'f90d2cc9' not connected"}),
        ("schedule: stored", {"at": h2, "by": "schedule", "outcome": "ok",
                              "offered": 5, "fetched": 5, "delivered": 5}),
        ("schedule: failed", {"at": h2, "by": "schedule", "outcome": "failed",
                              "error": f"Connection to {SHOWN} failed: connect already in progress"}),
    ]


MOCK_API = """
window.__verdicts = {};
window.__api = {
    hot_verdict: (mac) => JSON.stringify(window.__verdicts[mac] || {}),
    hot_verdicts: () => JSON.stringify(window.__verdicts),
    get_sync_candidates: () => JSON.stringify(window.__candidates || []),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _render(theme: str, out: Path) -> list[str]:
    from PIL import Image, ImageDraw
    from playwright.async_api import async_playwright
    from tests.support.browser import add_init_js, eval_js, launch, wait_js

    now = int(time.time())
    async with async_playwright() as p:
        browser = await launch(p, opted_in=True)
        try:
            context = await browser.new_context(device_scale_factor=2,
                                                viewport={"width": 1200, "height": 860})
            page = await context.new_page()
            await add_init_js(page, MOCK_API)
            await add_init_js(page, "try { localStorage.setItem('aesthetic-theme', %s); } catch (_) {}"
                              % json.dumps(theme))
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.HotVerdict && !!window.SpatialStage"
                                " && !!window.Divoom?.onOwnedDevices")
            await eval_js(page, """(panels) => window.Divoom.onOwnedDevices({type: 'owned_devices',
                devices: Object.entries(panels).map(([a, n]) =>
                    ({address: a, name: n, kind: 'clock', state: 'active'}))})""", PANELS)
            await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", SHOWN)
            await page.click('.nav-btn[data-tab="pixel-art"]')
            await page.click('[data-pixel-tab="pixel-hot-channel"]')
            await page.wait_for_selector("#pixel-hot-channel.active")

            shots, lines = [], []
            area = page.locator("#pixel-hot-channel .gallery-actions")
            for label, verdict in states(now):
                await eval_js(page, """([m, v]) => { window.__verdicts = v ? {[m]: v} : {};
                    window.HotVerdict.refresh(m); }""", [SHOWN, verdict])
                if verdict:
                    await eval_js(page, """([m, v]) => window.Divoom.onHotStatus(
                        {type: 'hot_status', mac: m, verdict: v})""", [SHOWN, verdict])
                await page.wait_for_timeout(120)
                text = await eval_js(page, "() => document.getElementById('hot-verdict').textContent")
                lines.append(f"{label:24s} {text}")
                shots.append((label, await area.screenshot()))
            # A run under way on the shown panel.
            await eval_js(page, """(m) => window.Divoom.onHotProgress(
                {type: 'hot_progress', mac: m, phase: 'uploading', current: 4, total: 23})""", SHOWN)
            await page.wait_for_timeout(120)
            lines.append(f"{'checking now':24s} "
                         + await eval_js(page, "() => document.getElementById('hot-verdict').textContent"))
            shots.append(("checking now", await area.screenshot()))

            # The Auto-Sync rows: the same record, shorter.
            await eval_js(page, """([panels, vs]) => {
                window.__verdicts = vs;
                window.__candidates = Object.entries(panels).map(([a, n]) => ({address: a, name: n, selected: true}));
            }""", [PANELS, dict(zip(PANELS, [states(now)[7][1], states(now)[3][1],
                                                 states(now)[6][1], states(now)[4][1]]))])
            await page.click('.nav-btn[data-tab="routines"]')
            await page.wait_for_selector("#routines-schedule.active")
            await eval_js(page, "() => window.renderSyncTargets(window.__candidates)")
            await page.wait_for_timeout(300)
            rows = await page.locator("#routines-schedule .card").first.screenshot()
        finally:
            await browser.close()

    import io
    tiles = [(label, Image.open(io.BytesIO(raw)).convert("RGB")) for label, raw in shots]
    rows_img = Image.open(io.BytesIO(rows)).convert("RGB")
    bg = (18, 19, 22) if theme == "dark" else (244, 244, 246)
    fg = (154, 160, 170) if theme == "dark" else (60, 62, 68)
    label_w, pad = 360, 16
    tile_w = max(t.width for _, t in tiles)
    height = sum(t.height + pad for _, t in tiles) + pad
    sheet_w = label_w + tile_w + pad * 3 + rows_img.width
    sheet = Image.new("RGB", (sheet_w, max(height, rows_img.height + 2 * pad)), bg)
    draw = ImageDraw.Draw(sheet)
    y = pad
    for label, t in tiles:
        draw.text((pad, y + t.height // 2 - 8), label, fill=fg, font_size=26)
        sheet.paste(t, (label_w, y))
        y += t.height + pad
    sheet.paste(rows_img, (label_w + tile_w + pad * 2, pad))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--out", default=None,
                        help="where the sheet lands (default: docs/assets/hot-verdict-<theme>.png)")
    args = parser.parse_args(argv)
    out = Path(args.out or REPO / "docs" / "assets" / f"hot-verdict-{args.theme}.png")
    for line in asyncio.run(_render(args.theme, out)):
        print(f"  {line}")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
