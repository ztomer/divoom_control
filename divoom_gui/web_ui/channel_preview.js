// channel_preview.js — render a device-preview image for a channel/kind.
//
// The device can't report its framebuffer, so for channels (which render on the
// device) we draw a recognizable representation: the SPECIFIC clock face the
// user picked (R50), the selected ambient mode's palette (R51), EQ bars, etc.
// Image content (live widgets / custom art / cover art) supplies a real frame
// and bypasses this. Split out of app_globals.js to stay under the 500-LOC cap.

// R50: render the SPECIFIC clock face the user picked (6 styles), not a generic
// clock glyph — mirrors the channel tiles (channels_grids.js CLOCK_FACES).
window._clockFaceSVG = function(style, color) {
    const c = color || "#ffffff";
    // "12:00" sized to fit 64px with margin (font-size 13 monospace ≈ 39px wide),
    // vertically centred (baseline y=37). text-anchor=middle keeps it centred.
    const FONT = `font-family="monospace" font-size="13" font-weight="bold"`;
    const digits = (fill) => `<text x="32" y="37" ${FONT} text-anchor="middle" fill="${fill}">12:00</text>`;
    let inner, bg = "#0a0b10";
    switch (Number(style)) {
        case 1: { // Rainbow — per-digit hue via tspans (keeps monospace spacing)
            const hues = ["#ff5a5a", "#ffc864", "#5ede91", "#5aabff", "#c89bff"];
            const tspans = ["1", "2", ":", "0", "0"]
                .map((ch, i) => `<tspan fill="${hues[i]}">${ch}</tspan>`).join("");
            inner = `<text x="32" y="37" ${FONT} text-anchor="middle">${tspans}</text>`;
            break;
        }
        case 2: // With Box — border encloses the digits with padding
            inner = `<rect x="8" y="23" width="48" height="18" rx="3" fill="none"`
                  + ` stroke="${c}" stroke-width="2"/>` + digits(c);
            break;
        case 3: // Analog Square
            inner = `<rect x="16" y="16" width="32" height="32" rx="4" fill="none" stroke="${c}" stroke-width="2.5"/>`
                  + `<line x1="32" y1="32" x2="32" y2="21" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>`
                  + `<line x1="32" y1="32" x2="41" y2="32" stroke="${c}" stroke-width="2" stroke-linecap="round"/>`;
            break;
        case 4: // Full Screen Neg — inverted: color fills the screen, dark digits
            bg = c; inner = digits("#15171c");
            break;
        case 5: // Analog Round
            inner = `<circle cx="32" cy="32" r="17" fill="none" stroke="${c}" stroke-width="2.5"/>`
                  + `<line x1="32" y1="32" x2="32" y2="19" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>`
                  + `<line x1="32" y1="32" x2="41" y2="36" stroke="${c}" stroke-width="2" stroke-linecap="round"/>`;
            break;
        default: // 0 Full Screen digital
            inner = digits(c);
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">`
              + `<rect width="64" height="64" fill="${bg}"/>${inner}</svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
};

window._channelPreviewSVG = function(kind, opts) {
    opts = opts || {};
    const a = opts.color || "#00ffcc";
    const k = (kind || "").toLowerCase();
    let inner;
    if (k === "clock") {
        // R50: reflect the selected face + color (falls back to current state).
        const style = (opts.style != null) ? opts.style
                    : (window.DivoomState.selectedClockStyle ?? 0);
        const color = opts.color
                    || document.getElementById("clock-color-input")?.value || "#ffffff";
        return window._clockFaceSVG(style, color);
    } else if (k === "visualizer" || k === "eq") {
        inner = `<rect x="13" y="36" width="8" height="16" fill="${a}"/><rect x="24" y="22" width="8" height="30" fill="${a}"/>`
              + `<rect x="35" y="30" width="8" height="22" fill="${a}"/><rect x="46" y="16" width="8" height="36" fill="${a}"/>`;
    } else if (k === "vj") {
        inner = `<path d="M32 11 L38 27 L55 32 L38 37 L32 53 L26 37 L9 32 L26 27 Z" fill="${a}"/>`;
    } else if (k === "scoreboard") {
        inner = `<text x="32" y="42" font-size="20" font-family="monospace" font-weight="bold" fill="#fff" text-anchor="middle">0:0</text>`;
    } else if (k === "text") {
        inner = `<text x="32" y="44" font-size="34" font-family="sans-serif" font-weight="bold" fill="#fff" text-anchor="middle">T</text>`;
    } else if (k === "ambient") {
        // R51: reflect the SELECTED ambient mode, not a flat color. Modes 1–4 use
        // fixed palettes (matching the tiles in channels_grids.js); only mode 0
        // (Plain Color) uses the picked color.
        const mode = (opts.mode != null) ? Number(opts.mode) : 0;
        let body;
        if (mode === 2) {            // Plants (Breathe) — red grow-field + blue bars
            body = `<rect width="64" height="64" fill="#ff0000"/>`
                 + [4, 20, 36, 52].map(x => `<rect x="${x}" y="0" width="4" height="64" fill="#0000ff"/>`).join("");
        } else {
            const fill = mode === 1 ? "#ff4d9e"      // Love (Pulse) — pink
                       : mode === 3 ? "#33cc33"      // Sleeping (Fade) — green
                       : mode === 4 ? "#d98a1f"      // No Mosquitto — amber
                       : a;                          // Plain Color — picked color
            body = `<rect width="64" height="64" fill="${fill}"/>`;
        }
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">${body}</svg>`;
        return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
    } else if (k === "design" || k === "custom") {
        inner = `<rect x="16" y="16" width="14" height="14" fill="${a}"/><rect x="34" y="16" width="14" height="14" fill="#fff"/>`
              + `<rect x="16" y="34" width="14" height="14" fill="#fff"/><rect x="34" y="34" width="14" height="14" fill="${a}"/>`;
    } else {
        inner = `<circle cx="32" cy="32" r="7" fill="#888"/>`;
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#0a0b10"/>${inner}</svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
};
