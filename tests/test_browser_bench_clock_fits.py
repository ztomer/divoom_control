"""P5.17: a bench node draws the whole clock on a 16x16 panel, and draws the
SAME pixels as the channel card beside it.

The nodes drew "12:0": five 3-wide glyphs with a column between each are 19
columns, and a 16x16 panel has 16, so the last digit fell off the canvas. The
channel card drew "12:00" from its own font and layout at 64 px. Two renderers
of one fact drift (house rule 9); this pins the count of lit cells against the
font itself (an independent oracle: a cropped glyph has fewer) and the node
against the card, cell for cell.
"""

import pytest
from pathlib import Path

from tests.support.browser import launch as launch_browser, eval_js, wait_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"

# Lit cells of "12:00", counted from the glyphs: 1 -> 6, 2 -> 11, : -> 2, 0 -> 12 (twice).
WHOLE_CLOCK_CELLS = 6 + 11 + 2 + 12 + 12


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [16, 32, 64])
async def test_a_bench_node_draws_the_whole_clock_the_card_draws(size):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1200, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window._clockFaceSVG")

        res = await eval_js(
            page,
            """(size) => {
            const disp = new window.DisplayPreview("bench-test", {width: size, height: size, size});
            disp.setActivity("clock", { style: 0, color: "#ffffff" });
            const canvas = document.createElement("canvas");
            canvas.width = size; canvas.height = size;
            disp.renderTo(canvas, 1);
            const data = canvas.getContext("2d").getImageData(0, 0, size, size).data;
            const unit = Math.max(1, Math.floor(size / 16));
            const node = new Set();
            for (let y = 0; y < size; y += unit) {
                for (let x = 0; x < size; x += unit) {
                    const i = (y * size + x) * 4;
                    if (data[i] > 128 && data[i + 1] > 128 && data[i + 2] > 128) node.add(`${x / unit},${y / unit}`);
                }
            }
            // The card: a 64 px SVG; its lit rects in 16-grid cells.
            const svg = decodeURIComponent(window._clockFaceSVG(0, "#ffffff").split(",")[1]);
            const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
            const card = new Set();
            doc.querySelectorAll("rect").forEach((r) => {
                if ((r.getAttribute("fill") || "").toLowerCase() !== "#ffffff") return;
                const w = Number(r.getAttribute("width"));
                if (w >= 64) return; // the background
                card.add(`${Number(r.getAttribute("x")) / w},${Number(r.getAttribute("y")) / w}`);
            });
            return { node: [...node].sort(), card: [...card].sort() };
        }""",
            size,
        )
        await browser.close()

    assert len(res["node"]) == WHOLE_CLOCK_CELLS, (
        f"{size}x{size}: the node lit {len(res['node'])} of the clock's {WHOLE_CLOCK_CELLS} cells -- a glyph is cropped"
    )
    assert res["node"] == res["card"], "the node and the card draw different clocks"
