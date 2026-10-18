// channel_preview.js — render a device-preview image for a channel/kind.
//
// The device can't report its framebuffer, so for channels (which render on the
// device) we draw a recognizable representation: the SPECIFIC clock face the
// user picked (R50), the selected ambient mode's palette (R51), EQ bars, etc.
// Image content (live widgets / custom art / cover art) supplies a real frame
// and bypasses this. Split out of app_globals.js to stay under the 500-LOC cap.

// 1-bit bitmap font tables (3x5 pixel grid for compact crisp digits)
const CLOCK_DIGITS_3X5 = {
    "0": [0b111, 0b101, 0b101, 0b101, 0b111],
    "1": [0b010, 0b110, 0b010, 0b010, 0b111],
    "2": [0b111, 0b001, 0b111, 0b100, 0b111],
    "3": [0b111, 0b001, 0b111, 0b001, 0b111],
    "4": [0b101, 0b101, 0b111, 0b001, 0b001],
    "5": [0b111, 0b100, 0b111, 0b001, 0b111],
    "6": [0b111, 0b100, 0b111, 0b101, 0b111],
    "7": [0b111, 0b001, 0b010, 0b010, 0b010],
    "8": [0b111, 0b101, 0b111, 0b101, 0b111],
    "9": [0b111, 0b101, 0b111, 0b001, 0b111],
    ":": [0b000, 0b010, 0b000, 0b010, 0b000]
};

function renderBitmapDigitsSVG(text, startX, startY, pixelSize, colors) {
    let svg = "";
    const digitW = 3 * pixelSize;
    const gap = pixelSize;
    for (let i = 0; i < text.length; i++) {
        const char = text[i];
        const matrix = CLOCK_DIGITS_3X5[char];
        if (!matrix) continue;
        const dx = startX + i * (digitW + gap);
        const color = Array.isArray(colors) ? colors[i % colors.length] : colors;
        for (let r = 0; r < 5; r++) {
            const rowBits = matrix[r];
            for (let c = 0; c < 3; c++) {
                if (rowBits & (1 << (2 - c))) {
                    svg += `<rect x="${dx + c * pixelSize}" y="${startY + r * pixelSize}" width="${pixelSize}" height="${pixelSize}" fill="${color}"/>`;
                }
            }
        }
    }
    return svg;
}

// R50: render the SPECIFIC clock face the user picked (6 styles), not a generic
// clock glyph — mirrors the channel tiles (channels_grids.js CLOCK_FACES).
// Uses authentic 1-bit bitmap digits (renderBitmapDigitsSVG) for sharp hardware pixel art.
window._clockFaceSVG = function(style, color) {
    const c = color || "#ffffff";
    let inner, bg = "#0a0b10";
    const rainbowHues = ["#ff5a5a", "#ffc864", "#5ede91", "#5aabff", "#c89bff"];

    switch (Number(style)) {
        case 1: // Rainbow — per-digit hue
            inner = renderBitmapDigitsSVG("12:00", 4, 25, 3, rainbowHues);
            break;
        case 2: // With Box — border encloses the digits
            inner = `<rect x="1" y="21" width="62" height="23" rx="2" fill="none" stroke="${c}" stroke-width="2"/>`
                  + renderBitmapDigitsSVG("12:00", 4, 25, 3, c);
            break;
        case 3: // Analog Square
            inner = `<rect x="12" y="12" width="40" height="40" rx="2" fill="none" stroke="${c}" stroke-width="2.5"/>`
                  + `<line x1="32" y1="32" x2="32" y2="18" stroke="${c}" stroke-width="2.5" stroke-linecap="square"/>`
                  + `<line x1="32" y1="32" x2="44" y2="32" stroke="${c}" stroke-width="2" stroke-linecap="square"/>`;
            break;
        case 4: // Full Screen Neg — inverted: color fills the screen, dark digits
            bg = c;
            inner = renderBitmapDigitsSVG("12:00", 4, 25, 3, "#15171c");
            break;
        case 5: // Analog Round
            inner = `<circle cx="32" cy="32" r="20" fill="none" stroke="${c}" stroke-width="2.5"/>`
                  + `<line x1="32" y1="32" x2="32" y2="17" stroke="${c}" stroke-width="2.5" stroke-linecap="square"/>`
                  + `<line x1="32" y1="32" x2="43" y2="37" stroke="${c}" stroke-width="2" stroke-linecap="square"/>`;
            break;
        default: // 0 Full Screen digital
            inner = renderBitmapDigitsSVG("12:00", 4, 25, 3, c);
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" style="image-rendering:pixelated;">`
              + `<rect width="64" height="64" fill="${bg}"/>${inner}</svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
};

window._channelPreviewSVG = function(kind, opts) {
    opts = opts || {};
    const a = opts.color || "#00ffcc";
    const k = (kind || "").toLowerCase();
    let inner;
    if (k === "clock") {
        return window._clockFaceSVG(opts.style ?? 0, opts.color || "#ffffff");
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
    } else if (k === "cloud" || k === "hot") {
        inner = `<path d="M18,36 A10,10 0 0,1 26,22 A12,12 0 0,1 46,26 A8,8 0 0,1 46,36 Z" fill="${a}"/>`
              + `<polygon points="32,30 28,38 33,38 30,46 40,36 35,36" fill="#ffcc00"/>`;
    } else {
        inner = `<circle cx="32" cy="32" r="7" fill="#888"/>`;
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#0a0b10"/>${inner}</svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
};

// Render slot coordinates and spatial bounds for a device in Virtual Wall mode
window._renderWallSlotSVG = function(slot, addr) {
    const x = (slot && slot.x) ?? 0;
    const y = (slot && slot.y) ?? 0;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">`
              + `<rect width="64" height="64" fill="#0a0b14"/>`
              + `<rect x="4" y="4" width="56" height="56" rx="4" fill="none" stroke="#ff5a1f" stroke-width="2" stroke-dasharray="4,2"/>`
              + `<text x="32" y="27" font-family="sans-serif" font-size="11" font-weight="bold" fill="#ff5a1f" text-anchor="middle">WALL</text>`
              + `<text x="32" y="43" font-family="monospace" font-size="9" fill="#8892b0" text-anchor="middle">(${x},${y})</text>`
              + `</svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
};

// Show the selected display's channel state in the controls: its channel tab
// and every channel control's value, from ITS settings (channel_settings.js).
// Every control is set, whichever channel the display is on -- a colour input
// left alone keeps the previous display's value (P5.2).
window.syncChannelControlsToDisplay = function(mac) {
    if (!mac || mac === "-" || mac === "None" || !window.DisplayPreviewRegistry) return;
    const saved = (typeof window.getDeviceChannel === "function") ? window.getDeviceChannel(mac) : null;
    const disp = window.DisplayPreviewRegistry.get(mac);
    if (saved?.channel && disp.channel !== saved.channel) disp.setActivity(saved.channel, saved.opts || {});
    const ch = disp.channel || "clock";

    window.DivoomState.activeChannel = ch;
    const card = document.querySelector(`.tab-btn[data-channel="${ch}"]`);
    if (card) {
        document.querySelectorAll(".tab-btn[data-channel]").forEach(c => c.classList.remove("active"));
        card.classList.add("active");
    }
    if (typeof window.showChannelPanel === "function") window.showChannelPanel(ch);
    window.paintChannelControls(mac);
};

// Every channel control's value, from `mac`'s settings -- not the tab: a
// write the panel refused puts the values back without moving the user off
// the panel they are looking at.
window.paintChannelControls = function(mac) {
    if (!mac || !window.DisplayPreviewRegistry) return;
    const disp = window.DisplayPreviewRegistry.get(mac);
    const of = (channel) => window.ChannelSettings.of(disp, channel);
    const markGrid = (gridId, value) => document.querySelectorAll(`#${gridId} .selector-cell`).forEach(el => {
        el.classList.toggle("active", value != null && Number(el.getAttribute("data-value")) === Number(value));
    });
    const setValue = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    const setChecked = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };

    const clock = of("clock");
    markGrid("clock-faces-grid", clock.style);
    setValue("clock-color-input", clock.color);
    if (typeof window.updateClockPreviewsColor === "function") window.updateClockPreviewsColor(clock.color);
    setChecked("clock-rich-humidity", clock.humidity);
    setChecked("clock-rich-weather", clock.weather);
    setChecked("clock-rich-date", clock.date);
    setChecked("clock-rich-24h", clock.twentyfour);

    const ambient = of("ambient");
    if (typeof window.markActiveAmbientMode === "function") window.markActiveAmbientMode(ambient.mode);
    setValue("ambient-color-input", ambient.color);
    document.querySelectorAll(".ambient-swatch").forEach(sw =>
        sw.classList.toggle("active", (sw.getAttribute("data-color") || "").toLowerCase() === String(ambient.color).toLowerCase()));
    if (typeof window.updateAmbientPreviewsColor === "function") window.updateAmbientPreviewsColor(ambient.color);
    if (typeof window.updateAmbientColorVisibility === "function") window.updateAmbientColorVisibility(ambient.mode);

    markGrid("vj-effects-grid", of("vj").vj);
    markGrid("eq-visualizer-grid", of("visualizer").eq);
    const score = of("scoreboard");
    setValue("scoreboard-red", score.red);
    setValue("scoreboard-blue", score.blue);
};
