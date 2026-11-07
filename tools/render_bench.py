#!/usr/bin/env python3
"""Render the Spatial Bench the way the app draws it, in the light or dark theme.

The REAL page (the app's HTML, CSS and JS, in the house browser) fed the
running daemon's own answers -- its fleet (`device_status`) and its saved
arrangement (`get_topology`) -- read-only over the socket, so the sheet shows
the owner's panels at their real sizes in the owner's places. Nothing is
written back: the page's `set_topology` is answered and dropped.

Usage:
    python3 tools/render_bench.py --theme light --out docs/assets/bench-light.png
    python3 tools/render_bench.py --theme dark --out docs/assets/bench-dark.png
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
INDEX_HTML = REPO / "divoom_gui" / "web_ui" / "index.html"
PANEL_FIELDS = (
    "mac",
    "connected",
    "selected",
    "model",
    "width",
    "height",
    "model_source",
    "chassis",
    "features",
    "screens",
    "wall_refusal",
)


def _ask(sock: str, command: str) -> dict:
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(10)
        s.connect(sock)
        s.sendall((json.dumps({"command": command, "args": {}, "id": 1}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.split(b"\n")[0])


MOCK = """
window.__panels = %PANELS%;
window.__topology = %TOPOLOGY%;
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: window.__panels}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  get_topology: () => ({success: true, topology: window.__topology}),
  set_topology: () => ({success: true}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (typeof window.__api[name] === 'function') return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _render(theme: str, out: Path, sock: str) -> None:
    from playwright.async_api import async_playwright

    from tests.support.browser import add_init_js, eval_js, launch, wait_js

    fleet = _ask(sock, "device_status").get("devices") or []
    topology = _ask(sock, "get_topology").get("topology") or {}
    panels = [{k: d.get(k) for k in PANEL_FIELDS} for d in fleet]
    known = {p["mac"] for p in panels}
    names = {m: (topology.get("names") or {}).get(m) for m in topology.get("devices", {})}
    # Every panel the arrangement places is on the bench, linked or not, as in the app.
    owned = [
        {
            "address": m,
            "name": names.get(m) or m[:8],
            "kind": "clock",
            "state": "active" if m in known else "disconnected",
        }
        for m in topology.get("devices", {})
    ]
    for d in fleet:
        for o in owned:
            if o["address"] == d.get("mac") and d.get("name"):
                o["name"] = d["name"]
    async with async_playwright() as p:
        browser = await launch(p, opted_in=True)
        try:
            ctx = await browser.new_context(device_scale_factor=2, viewport={"width": 900, "height": 640})
            page = await ctx.new_page()
            await add_init_js(
                page, MOCK.replace("%PANELS%", json.dumps(panels)).replace("%TOPOLOGY%", json.dumps(topology))
            )
            await add_init_js(page, f"try {{ localStorage.setItem('aesthetic-theme', '{theme}'); }} catch (_) {{}}")
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialRooms?.isLoaded()")
            await eval_js(page, "(d) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: d})", owned)
            await eval_js(page, "() => window.refreshPanelFacts()")
            await page.wait_for_timeout(600)
            out.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out))
        finally:
            await browser.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", choices=("light", "dark"), default="dark")
    ap.add_argument("--out", default=None)
    ap.add_argument("--socket", default="/tmp/divoom.sock")
    args = ap.parse_args(argv)
    out = Path(args.out or REPO / "docs" / "assets" / f"bench-{args.theme}.png")
    asyncio.run(_render(args.theme, out, args.socket))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
