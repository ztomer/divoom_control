"""Every visible label and switch is readable in BOTH themes (3:1).

Found 2026-10-18 looking at the P5.4 weather card in the light theme: its
"Live" switch was a white oval with no knob -- `.slider-round:before` was
`white` in every theme, over a track that is white in the light one. The same
pass found 60 more: the bench header and the panel deck painted hardcoded dark
surfaces behind theme-coloured text (the deck's panel name at 1.04:1), and
accent colours tuned for a dark background used as TEXT on a light one.

The class is "a colour chosen for one theme", so the gate is the whole page in
both themes, every tab, not a list of the elements that were wrong: every
element with its own visible text, and every switch knob against its track,
must reach 3:1 (WCAG 1.4.11's bar for UI components, and 1.4.3's for large
text). A gradient is measured at every one of its colour stops (a transparent
stop shows what is under it) and the WORST stop is the verdict: until
2026-11-01 text over a gradient was skipped, which is how the bench nodes'
names (theme ink on a chassis gradient fixed dark) read 1.1:1 in the light
theme, and the bench's dot grid (a radial gradient) showed through its loading
and empty-state text, with every run green. Only a `url()` image is left
unmeasured, and counted.

The mock fleet puts real panels on the bench, and the bench is also drawn in
its loading and empty states, because a page with no panel never draws a node.

Skipped if a browser isn't installed (runs with --run-browser).
"""

from pathlib import Path

import pytest

from divoom_lib.utils.plural import counted
from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
TABS = ("control-panel", "data-sources", "pixel-art", "display-wall", "routines", "device-settings")
MIN_RATIO = 3.0
# The verdict is on the SETTLED colours: a mid-transition sample (a tab's tint
# fading in, a switch track sliding) read 2.1-2.6:1 for colours that settle
# above 4:1, so transitions are switched off for the measurement.
_SETTLED = "*, *::before, *::after { transition: none !important; animation: none !important; }"

_MOCK_API = """
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) =>
    Promise.resolve(String(name).startsWith('get_') ? '{}' : true) })};
"""

# Composite each element's background chain up to the first opaque layer, and
# measure the WCAG contrast of its text colour (alpha-blended) against that.
_PROBE = """(min) => {
  const parse = c => { const m = /rgba?\\(([^)]+)\\)/.exec(c || ''); if (!m) return null;
    const v = m[1].split(',').map(parseFloat); return {r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1}; };
  const lin = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
  const lum = c => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const over = (t, u) => ({r: t.r * t.a + u.r * (1 - t.a), g: t.g * t.a + u.g * (1 - t.a),
                           b: t.b * t.a + u.b * (1 - t.a), a: 1});
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  // Every colour the element's text can sit on: the background chain
  // composited to the first opaque colour, each gradient expanded to its stops.
  const stops = img => (img.match(/rgba?\\([^)]+\\)/g) || []).map(parse);
  const backdrops = el => { const layers = [];
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const img = cs.backgroundImage && cs.backgroundImage !== 'none' ? cs.backgroundImage : '';
      if (/url\\(/.test(img)) return null;
      const c = parse(cs.backgroundColor), g = img ? stops(img) : [];
      if ((c && c.a > 0) || g.length) layers.push({c, g});
      if (c && c.a >= 1) break; }
    let accs = [{r: 255, g: 255, b: 255, a: 1}];
    for (let i = layers.length - 1; i >= 0; i--) {
      const {c, g} = layers[i];
      if (c && c.a > 0) accs = accs.map(a => over(c, a));
      if (g.length) accs = accs.flatMap(a => g.map(s => over(s, a)));
    }
    return accs; };
  const worst = (fg, bgs) => Math.min(...bgs.map(b => ratio(over(fg, b), b)));
  const shown = el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0 && parseFloat(cs.fontSize) > 0; };
  const bad = []; let unmeasured = 0;
  document.querySelectorAll('body *').forEach(el => {
    if (!shown(el)) return;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
    const bgs = backdrops(el); if (!bgs) { unmeasured++; return; }
    const fg = parse(getComputedStyle(el).color); if (!fg) return;
    const k = worst(fg, bgs);
    if (k < min) bad.push(`${k.toFixed(2)} ${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}`
                         + `.${String(el.className).trim().split(/\\s+/).join('.')} "${el.textContent.trim().slice(0, 24)}"`);
  });
  document.querySelectorAll('.slider-round').forEach(s => {
    if (!shown(s)) return;
    const knob = parse(getComputedStyle(s, '::before').backgroundColor), tracks = backdrops(s);
    if (!knob || !tracks) { unmeasured++; return; }
    const k = worst(knob, tracks);
    const id = s.parentElement.querySelector('input') ? s.parentElement.querySelector('input').id : '?';
    if (k < min) bad.push(`${k.toFixed(2)} switch knob #${id}`);
  });
  return {bad, unmeasured};
}"""


@pytest.mark.asyncio
@pytest.mark.parametrize("theme", ["light", "dark"])
async def test_every_label_and_switch_reads_at_3_to_1(theme):
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await add_init_js(
                page, _MOCK_API + f"\ntry {{ localStorage.setItem('divoom-theme', '{theme}'); }} catch (e) {{}}\n"
            )
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.DivoomState")
            await page.add_style_tag(content=_SETTLED)
            assert await eval_js(page, f"() => document.body.classList.contains('theme-{theme}')")
            failures = {}
            for tab in TABS:
                await page.click(f'.nav-btn[data-tab="{tab}"]')
                # The tab switch is the event (transitions are off, _SETTLED):
                # the panel carries `active` once the app has shown it.
                await wait_js(page, f"() => document.getElementById('{tab}')?.classList.contains('active')")
                res = await eval_js(page, _PROBE, MIN_RATIO)
                for line in res["bad"]:
                    failures.setdefault(line, tab)
            assert not failures, (
                f"{counted(len(failures), 'element')} below {MIN_RATIO}:1 in the {theme} theme "
                "(ratio, element, first tab seen):\n  " + "\n  ".join(f"{k}  [{t}]" for k, t in failures.items())
            )
        finally:
            await browser.close()


_FLEET_API = """
window.__panels = %PANELS%;
window.__api = {
  get_panels: () => JSON.stringify({ok: true, panels: window.__panels}),
  get_panel_levels: (mac) => JSON.stringify({ok: true, mac, brightness: 50, volume: null}),
  get_topology: () => ({success: true, topology: %TOPOLOGY%}),
  set_topology: () => ({success: true}),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (typeof window.__api[name] === 'function') return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("state", ["panels", "empty", "loading"])
async def test_the_bench_reads_at_3_to_1_in_every_state(theme, state):
    """The bench with real panels on it, with none, and waiting for the daemon."""
    require_browser()
    import json

    from playwright.async_api import async_playwright

    from tests.test_e2e_bench_snap import _panel

    macs = ["aa000000-0000-4000-8000-000000000001", "bb000000-0000-4000-8000-000000000002"]
    names = {macs[0]: "Pixoo-1", macs[1]: "Timoo-light-4"}
    # Loading is drawn only once a panel is known (no panel says so first).
    panels = [] if state == "empty" else [_panel(m) for m in macs]
    topology = "null" if state == "loading" else json.dumps({"rooms": ["Desk"], "wall_linked": True, "devices": {}})
    init = (
        _FLEET_API.replace("%PANELS%", json.dumps(panels)).replace("%TOPOLOGY%", topology)
        + f"\ntry {{ localStorage.setItem('divoom-theme', '{theme}'); }} catch (e) {{}}\n"
    )
    if state == "loading":
        init = init.replace(
            "get_topology: () => ({success: true, topology: null})", "get_topology: () => new Promise(() => {})"
        )
    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await add_init_js(page, init)
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(
                page, "() => !!window.SpatialStage && !!window.SpatialRooms && !!window.Divoom?.onOwnedDevices"
            )
            await page.add_style_tag(content=_SETTLED)
            if state != "empty":
                owned = [{"address": m, "name": names[m], "kind": "clock", "state": "active"} for m in macs]
                await eval_js(page, "(d) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: d})", owned)
                await eval_js(page, "() => window.refreshPanelFacts()")
            marker = {
                "panels": f"spatial-node-{macs[-1]}",
                "empty": "spatial-bench-empty",
                "loading": "spatial-bench-loading",
            }[state]
            await wait_js(page, f"() => !!document.getElementById('{marker}')")
            res = await eval_js(page, _PROBE, MIN_RATIO)
            assert not res["bad"], (
                f"{counted(len(res['bad']), 'element')} below {MIN_RATIO}:1 in the {theme} "
                f"theme, bench {state}:\n  " + "\n  ".join(res["bad"])
            )
        finally:
            await browser.close()
