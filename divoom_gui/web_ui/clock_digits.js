/* clock_digits.js — the ONE digital-clock layout every preview draws (P5.17).
 *
 * The bench's 16x16 nodes drew "12:0": their renderer laid "12:00" out as five
 * 3-wide glyphs with a column between each, 19 columns on a 16-column panel, so
 * the last digit fell off the canvas. The channel card beside them drew "12:00"
 * because it had its OWN copy of the font and its own layout at 64 px -- two
 * renderers of one fact, drifting (house rule 9).
 *
 * So the layout lives here, on the panel's own 16-cell grid, and both draw it:
 * the bench node at its canvas resolution, the channel card at 4 px a cell.
 * Glyphs are 5 rows tall and as wide as they are drawn: 3 columns, the "1" two
 * and the colon one, with one blank column between any two. That is how
 * "12:00" fits with every glyph apart: 2+1+3+1+1+1+3+1+3 = 16. (A colon touching
 * its digits fits in 15 and reads "1200" -- tried and rejected on the render.)
 */
(function () {
    "use strict";

    const GRID = 16;

    const FONT_3X5 = {
        "0": [0b111, 0b101, 0b101, 0b101, 0b111],
        "1": [0b01, 0b11, 0b01, 0b01, 0b01], // two columns wide (WIDTH)
        "2": [0b111, 0b001, 0b111, 0b100, 0b111],
        "3": [0b111, 0b001, 0b111, 0b001, 0b111],
        "4": [0b101, 0b101, 0b111, 0b001, 0b001],
        "5": [0b111, 0b100, 0b111, 0b001, 0b111],
        "6": [0b111, 0b100, 0b111, 0b101, 0b111],
        "7": [0b111, 0b001, 0b010, 0b010, 0b010],
        "8": [0b111, 0b101, 0b111, 0b101, 0b111],
        "9": [0b111, 0b101, 0b111, 0b001, 0b111],
        " ": [0b000, 0b000, 0b000, 0b000, 0b000],
    };
    const COLON = [0b0, 0b1, 0b0, 0b1, 0b0]; // one column wide
    const WIDTH = { "1": 2 };

    /** The lit cells of `text` on the 16-cell grid, centred: [{x, y, i}] with i the char index. */
    function layout(text) {
        const glyphs = Array.from(text).map((ch) => (ch === ":"
            ? { rows: COLON, w: 1 }
            : { rows: FONT_3X5[ch] || FONT_3X5[" "], w: WIDTH[ch] || 3 }));
        let width = 0;
        glyphs.forEach((g, i) => {
            if (i > 0) width += 1; // a blank column between any two glyphs
            g.x = width;
            width += g.w;
        });
        const x0 = Math.floor((GRID - width) / 2);
        const y0 = Math.floor((GRID - 5) / 2);
        const cells = [];
        glyphs.forEach((g, i) => {
            for (let r = 0; r < 5; r++) {
                for (let c = 0; c < g.w; c++) {
                    if (g.rows[r] & (1 << (g.w - 1 - c))) cells.push({ x: x0 + g.x + c, y: y0 + r, i });
                }
            }
        });
        return { cells, width, x0, y0 };
    }

    /** The box face's frame (style 2): a rule above and below the digits, full width. */
    function boxCells() {
        const out = [];
        for (let x = 0; x < GRID; x++) out.push({ x, y: 3 }, { x, y: 11 });
        return out;
    }

    /** Draw on a canvas of any size: the 16-grid scaled by a whole number, centred. */
    function drawCanvas(ctx, text, w, h, colorOf, withBox) {
        const unit = Math.max(1, Math.floor(Math.min(w, h) / GRID));
        const ox = Math.floor((w - GRID * unit) / 2);
        const oy = Math.floor((h - GRID * unit) / 2);
        layout(text).cells.forEach((p) => {
            ctx.fillStyle = colorOf(p.i);
            ctx.fillRect(ox + p.x * unit, oy + p.y * unit, unit, unit);
        });
        if (withBox) {
            ctx.fillStyle = colorOf(-1);
            boxCells().forEach((p) => ctx.fillRect(ox + p.x * unit, oy + p.y * unit, unit, unit));
        }
    }

    /** The same cells as SVG rects, `unit` px a cell (the 64 px card is 4). */
    function svg(text, unit, colorOf, withBox) {
        const rect = (p, fill) => `<rect x="${p.x * unit}" y="${p.y * unit}" width="${unit}" height="${unit}" fill="${fill}"/>`;
        let out = layout(text).cells.map((p) => rect(p, colorOf(p.i))).join("");
        if (withBox) out += boxCells().map((p) => rect(p, colorOf(-1))).join("");
        return out;
    }

    window.ClockDigits = { GRID, FONT_3X5, layout, drawCanvas, svg };
})();
