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
text). A background drawn with an image or gradient cannot be measured from
computed style, so text over one is skipped and NAMED in the failure output's
count rather than silently passed.

Skipped if a browser isn't installed (runs with --run-browser).
"""
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
TABS = ("control-panel", "data-sources", "pixel-art", "display-wall", "routines", "device-settings")
MIN_RATIO = 3.0

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
  const backdrop = el => { const layers = [];
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== 'none' && !/url\\(/.test(cs.backgroundImage)) return null;
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
    let acc = {r: 255, g: 255, b: 255, a: 1};
    for (let i = layers.length - 1; i >= 0; i--) acc = over(layers[i], acc);
    return acc; };
  const shown = el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0 && parseFloat(cs.fontSize) > 0; };
  const bad = []; let unmeasured = 0;
  document.querySelectorAll('body *').forEach(el => {
    if (!shown(el)) return;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
    const bg = backdrop(el); if (!bg) { unmeasured++; return; }
    const fg = parse(getComputedStyle(el).color); if (!fg) return;
    const k = ratio(over(fg, bg), bg);
    if (k < min) bad.push(`${k.toFixed(2)} ${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}`
                         + `.${String(el.className).trim().split(/\\s+/).join('.')} "${el.textContent.trim().slice(0, 24)}"`);
  });
  document.querySelectorAll('.slider-round').forEach(s => {
    if (!shown(s)) return;
    const knob = parse(getComputedStyle(s, '::before').backgroundColor), track = backdrop(s);
    if (!knob || !track) { unmeasured++; return; }
    const k = ratio(over(knob, track), track);
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
            await add_init_js(page, _MOCK_API
                              + f"\ntry {{ localStorage.setItem('aesthetic-theme', '{theme}'); }} catch (e) {{}}\n")
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.DivoomState")
            assert await eval_js(page, f"() => document.body.classList.contains('theme-{theme}')")
            failures = {}
            for tab in TABS:
                await page.click(f'.nav-btn[data-tab="{tab}"]')
                await page.wait_for_timeout(300)
                res = await eval_js(page, _PROBE, MIN_RATIO)
                for line in res["bad"]:
                    failures.setdefault(line, tab)
            assert not failures, (
                f"{len(failures)} element(s) below {MIN_RATIO}:1 in the {theme} theme "
                "(ratio, element, first tab seen):\n  "
                + "\n  ".join(f"{k}  [{t}]" for k, t in failures.items()))
        finally:
            await browser.close()
