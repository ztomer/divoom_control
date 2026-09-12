/* preview_controller.js — Unified per-display preview model and registry.
 *
 * Provides a single object model (DisplayPreview) per physical/virtual display
 * that encapsulates screen resolution, active channel, raster/SVG frame caching,
 * authentic 1-bit bitmap digit rendering, and multi-canvas blitting.
 *
 * Fleet coordination is managed by DisplayPreviewRegistry.
 */

(function () {
    "use strict";

    // 1-bit bitmap font tables (3x5 pixel grid for compact crisp digits)
    const BITMAP_FONT_3X5 = {
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
        ":": [0b000, 0b010, 0b000, 0b010, 0b000],
        " ": [0b000, 0b000, 0b000, 0b000, 0b000]
    };

    /**
     * DisplayPreview: encapsulates state and rendering for a single display.
     */
    class DisplayPreview {
        constructor(mac, spec) {
            this.mac = mac || "default";
            this.spec = spec || { width: 16, height: 16, size: 16, name: "Screen" };
            this.channel = "clock";
            this.mode = "glyph"; // "frame" (raster data-url) | "glyph" (procedural)
            this.frameSrc = null;
            this.opts = { style: 0, color: "#ffffff" };
            this.cachedImg = null;
            this.cachedSrc = null;
            this.imgLoaded = false;
            this.wallSlot = null;
            this.activeJob = null;
            this.lastUpdated = Date.now();
        }

        bindJob(kind, params) {
            this.activeJob = { kind: (kind || "").toLowerCase(), params: params || {}, startedAt: Date.now() };
            this.setActivity(kind, params);
        }

        unbindJob() {
            this.activeJob = null;
        }

        isBoundTo(kind) {
            return !!(this.activeJob && this.activeJob.kind === (kind || "").toLowerCase());
        }

        updateSpec(spec) {
            if (!spec) return;
            this.spec = Object.assign({}, this.spec, spec);
        }

        setActivity(channel, opts) {
            const ch = (channel || "clock").toLowerCase();
            const isArtwork = !!(opts && (opts.fileId || opts.file_id || opts.takeover || opts.gallery));
            if (this.activeJob && (ch !== "image" ? this.activeJob.kind !== ch : isArtwork)) {
                this.unbindJob();
            }
            this.channel = ch;
            this.opts = Object.assign({}, this.opts, opts || {});
            if (this.opts.src) {
                this.setFrame(this.opts.src);
            } else {
                this.mode = "glyph";
                this.frameSrc = null;
                this.cachedImg = null;
                this.cachedSrc = null;
                this.imgLoaded = false;
            }
            this.lastUpdated = Date.now();
        }

        setFrame(src) {
            if (!src) return;
            this.frameSrc = src;
            this.mode = "frame";
            this.lastUpdated = Date.now();
            if (this.cachedSrc !== src) {
                this.cachedSrc = src;
                this.imgLoaded = false;
                const img = new Image();
                img.onload = () => {
                    this.imgLoaded = true;
                    this.cachedImg = img;
                };
                img.onerror = () => {
                    this.imgLoaded = false;
                    this.cachedImg = null;
                };
                img.src = src;
                this.cachedImg = img;
            }
        }

        setWallSlot(slot) {
            this.wallSlot = slot;
            this.lastUpdated = Date.now();
        }

        /**
         * Renders the preview content directly onto an HTMLCanvasElement.
         * Guarantees 100% sharp pixelated reproduction without anti-aliasing.
         */
        renderTo(canvas, tick) {
            if (!canvas) return;
            const ctx = canvas.getContext("2d");
            if (!ctx) return;
            ctx.imageSmoothingEnabled = false;

            const w = canvas.width;
            const h = canvas.height;

            // 1. Clear background
            ctx.fillStyle = "#07080a";
            ctx.fillRect(0, 0, w, h);

            // 2. If a real raster/SVG frame is loaded, draw it
            if (this.mode === "frame" && this.cachedImg && this.imgLoaded) {
                ctx.drawImage(this.cachedImg, 0, 0, w, h);
                return;
            }

            // 3. If explicitly in Virtual Wall channel, render the wall slot glyph
            if (this.channel === "wall") {
                this.renderWallGlyph(ctx, w, h);
                return;
            }

            // 4. Render procedural channel glyph
            switch (this.channel) {
                case "clock":
                    this.renderClockGlyph(ctx, w, h, tick);
                    break;
                case "visualizer":
                case "eq":
                    this.renderEqGlyph(ctx, w, h, tick);
                    break;
                case "vj":
                    this.renderVjGlyph(ctx, w, h, tick);
                    break;
                case "ambient":
                    this.renderAmbientGlyph(ctx, w, h);
                    break;
                case "scoreboard":
                    this.renderScoreboardGlyph(ctx, w, h);
                    break;
                case "text":
                    this.renderTextGlyph(ctx, w, h, tick);
                    break;
                case "cloud":
                case "hot":
                    this.renderCloudGlyph(ctx, w, h);
                    break;
                case "design":
                case "custom":
                    this.renderCustomArtGlyph(ctx, w, h);
                    break;
                case "sysmon":
                    this.renderSysmonGlyph(ctx, w, h, tick);
                    break;
                default:
                    this.renderClockGlyph(ctx, w, h, tick);
            }
        }

        renderClockGlyph(ctx, w, h, tick) {
            const style = Number(this.opts.style || 0);
            const color = this.opts.color || "#ffffff";
            const scale = Math.max(1, Math.floor(w / 16));

            if (style === 4) {
                // Style 4: Full Screen Neg (inverted background)
                ctx.fillStyle = color;
                ctx.fillRect(0, 0, w, h);
            }

            if (style === 3 || style === 5) {
                // Analog Square (3) or Analog Round (5)
                const cx = Math.floor(w / 2);
                const cy = Math.floor(h / 2);
                const r = Math.floor(w * 0.38);

                ctx.strokeStyle = (style === 4) ? "#15171c" : color;
                ctx.lineWidth = Math.max(1, Math.floor(scale * 0.8));

                if (style === 5) {
                    ctx.beginPath();
                    ctx.arc(cx, cy, r, 0, Math.PI * 2);
                    ctx.stroke();
                } else {
                    ctx.strokeRect(cx - r, cy - r, r * 2, r * 2);
                }

                // Clock hands (hour & minute)
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.lineTo(cx, cy - Math.floor(r * 0.6));
                ctx.moveTo(cx, cy);
                ctx.lineTo(cx + Math.floor(r * 0.5), cy);
                ctx.stroke();
                return;
            }

            // Digital Clock: draw authentic 1-bit bitmap digits "12:00"
            const text = "12:00";
            const digitW = 3 * scale;
            const digitH = 5 * scale;
            const gap = 1 * scale;
            const totalW = (text.length * 3 + (text.length - 1)) * scale;
            const startX = Math.max(0, Math.floor((w - totalW) / 2));
            const startY = Math.max(0, Math.floor((h - digitH) / 2));

            const rainbowColors = ["#ff5a5a", "#ffc864", "#5ede91", "#5aabff", "#c89bff"];

            for (let i = 0; i < text.length; i++) {
                const char = text[i];
                const matrix = BITMAP_FONT_3X5[char] || BITMAP_FONT_3X5[" "];
                const dx = startX + i * (digitW + gap);
                const charColor = (style === 1) ? rainbowColors[i % rainbowColors.length]
                                : (style === 4 ? "#15171c" : color);

                ctx.fillStyle = charColor;

                for (let r = 0; r < 5; r++) {
                    const rowBits = matrix[r];
                    for (let c = 0; c < 3; c++) {
                        if (rowBits & (1 << (2 - c))) {
                            ctx.fillRect(dx + c * scale, startY + r * scale, scale, scale);
                        }
                    }
                }
            }

            if (style === 2) {
                // Style 2: With Box border
                ctx.strokeStyle = color;
                ctx.lineWidth = scale;
                ctx.strokeRect(startX - scale * 2, startY - scale * 2, totalW + scale * 4, digitH + scale * 4);
            }
        }

        renderEqGlyph(ctx, w, h, tick) {
            const numBars = 4;
            const barW = Math.max(1, Math.floor(w / 8));
            const gap = Math.max(1, Math.floor(w / 16));
            const startX = Math.floor((w - (numBars * barW + (numBars - 1) * gap)) / 2);

            for (let i = 0; i < numBars; i++) {
                const heightPhase = Math.sin((tick || 0) * 0.15 + i * 1.2) * 0.5 + 0.5;
                const barH = Math.max(2, Math.floor(h * 0.7 * heightPhase));
                const bx = startX + i * (barW + gap);
                const by = h - barH - Math.floor(h * 0.15);

                for (let y = 0; y < barH; y += Math.max(1, Math.floor(h / 16))) {
                    const py = by + (barH - y);
                    ctx.fillStyle = py < h * 0.4 ? "#ff5a1f" : py < h * 0.65 ? "#ffcc00" : "#00cc66";
                    ctx.fillRect(bx, py, barW, Math.max(1, Math.floor(h / 16)));
                }
            }
        }

        renderVjGlyph(ctx, w, h, tick) {
            const cx = Math.floor(w / 2);
            const cy = Math.floor(h / 2);
            const r = Math.floor(w * 0.35);
            ctx.fillStyle = this.opts.color || "#00ffcc";

            ctx.beginPath();
            ctx.moveTo(cx, cy - r);
            ctx.lineTo(cx + Math.floor(r * 0.3), cy - Math.floor(r * 0.3));
            ctx.lineTo(cx + r, cy);
            ctx.lineTo(cx + Math.floor(r * 0.3), cy + Math.floor(r * 0.3));
            ctx.lineTo(cx, cy + r);
            ctx.lineTo(cx - Math.floor(r * 0.3), cy + Math.floor(r * 0.3));
            ctx.lineTo(cx - r, cy);
            ctx.lineTo(cx - Math.floor(r * 0.3), cy - Math.floor(r * 0.3));
            ctx.closePath();
            ctx.fill();
        }

        renderAmbientGlyph(ctx, w, h) {
            const mode = Number(this.opts.mode || 0);
            if (mode === 2) {
                // Plants (breathe): red grow-field with blue light bars
                ctx.fillStyle = "#ff0000";
                ctx.fillRect(0, 0, w, h);
                ctx.fillStyle = "#0000ff";
                const step = Math.floor(w / 4);
                for (let x = Math.floor(step / 4); x < w; x += step) {
                    ctx.fillRect(x, 0, Math.max(1, Math.floor(w / 16)), h);
                }
            } else {
                const fill = (mode === 1) ? "#ff4d9e"
                           : (mode === 3) ? "#33cc33"
                           : (mode === 4) ? "#d98a1f"
                           : (this.opts.color || "#00cc66");
                ctx.fillStyle = fill;
                ctx.fillRect(0, 0, w, h);
            }
        }

        renderScoreboardGlyph(ctx, w, h) {
            const scale = Math.max(1, Math.floor(w / 16));
            ctx.fillStyle = "#ffffff";
            // Draw "0:0"
            const text = "0:0";
            const digitW = 3 * scale;
            const digitH = 5 * scale;
            const gap = 1 * scale;
            const totalW = (text.length * 3 + (text.length - 1)) * scale;
            const startX = Math.max(0, Math.floor((w - totalW) / 2));
            const startY = Math.max(0, Math.floor((h - digitH) / 2));

            for (let i = 0; i < text.length; i++) {
                const matrix = BITMAP_FONT_3X5[text[i]] || BITMAP_FONT_3X5[" "];
                const dx = startX + i * (digitW + gap);
                for (let r = 0; r < 5; r++) {
                    const row = matrix[r];
                    for (let c = 0; c < 3; c++) {
                        if (row & (1 << (2 - c))) {
                            ctx.fillRect(dx + c * scale, startY + r * scale, scale, scale);
                        }
                    }
                }
            }
        }

        renderTextGlyph(ctx, w, h, tick) {
            const scale = Math.max(1, Math.floor(w / 8));
            ctx.fillStyle = "#ffffff";
            const cx = Math.floor(w / 2);
            const cy = Math.floor(h / 2);
            // Draw a bold 7-segment style "T"
            ctx.fillRect(cx - scale * 3, cy - scale * 3, scale * 6, scale);
            ctx.fillRect(cx - Math.floor(scale / 2), cy - scale * 3, scale, scale * 6);
        }

        renderCloudGlyph(ctx, w, h) {
            const scale = Math.max(1, Math.floor(w / 16));
            const cx = Math.floor(w / 2);
            const cy = Math.floor(h / 2);
            ctx.fillStyle = this.opts.color || "#00ffcc";

            // Divoom Cloud silhouette
            ctx.beginPath();
            ctx.arc(cx - scale * 2, cy, scale * 3, 0, Math.PI * 2);
            ctx.arc(cx + scale * 2, cy - scale, scale * 4, 0, Math.PI * 2);
            ctx.arc(cx + scale * 4, cy + scale, scale * 2.5, 0, Math.PI * 2);
            ctx.fill();

            // Lightning bolt in center
            ctx.fillStyle = "#ffcc00";
            ctx.beginPath();
            ctx.moveTo(cx, cy - scale * 2);
            ctx.lineTo(cx - scale * 2, cy + scale);
            ctx.lineTo(cx, cy + scale);
            ctx.lineTo(cx - scale, cy + scale * 4);
            ctx.lineTo(cx + scale * 3, cy);
            ctx.lineTo(cx + scale, cy);
            ctx.closePath();
            ctx.fill();
        }

        renderCustomArtGlyph(ctx, w, h) {
            const scale = Math.max(1, Math.floor(w / 16));
            const c = this.opts.color || "#ff5a1f";
            // 4-quadrant pixel art icon
            ctx.fillStyle = c;
            ctx.fillRect(scale * 3, scale * 3, scale * 4, scale * 4);
            ctx.fillRect(scale * 9, scale * 9, scale * 4, scale * 4);
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(scale * 9, scale * 3, scale * 4, scale * 4);
            ctx.fillRect(scale * 3, scale * 9, scale * 4, scale * 4);
        }

        renderSysmonGlyph(ctx, w, h, tick) {
            ctx.fillStyle = "#00cc66";
            const numBars = 7;
            const barW = Math.max(1, Math.floor(w / 16));
            const gap = Math.max(1, Math.floor(w / 16));
            const startX = Math.floor((w - (numBars * (barW + gap))) / 2);

            for (let i = 0; i < numBars; i++) {
                const sine = Math.sin((tick || 0) * 0.1 + i * 0.4) * 0.5 + 0.5;
                const barH = Math.max(2, Math.floor(h * 0.6 * sine));
                const bx = startX + i * (barW + gap);
                const by = h - barH - Math.floor(h * 0.2);
                ctx.fillRect(bx, by, barW, barH);
            }
        }

        renderWallGlyph(ctx, w, h) {
            ctx.strokeStyle = "#ff5a1f";
            ctx.lineWidth = Math.max(1, Math.floor(w / 32));
            ctx.setLineDash([4, 2]);
            ctx.strokeRect(2, 2, w - 4, h - 4);
            ctx.setLineDash([]);

            ctx.fillStyle = "#ff5a1f";
            const scale = Math.max(1, Math.floor(w / 16));
            // Draw "W"
            const cx = Math.floor(w / 2);
            const cy = Math.floor(h / 2);
            ctx.fillRect(cx - scale * 3, cy - scale * 2, scale, scale * 4);
            ctx.fillRect(cx - scale * 1, cy, scale, scale * 2);
            ctx.fillRect(cx + scale * 1, cy, scale, scale * 2);
            ctx.fillRect(cx + scale * 3, cy - scale * 2, scale, scale * 4);
        }
    }

    /**
     * DisplayPreviewRegistry: manages all DisplayPreview instances across N devices.
     */
    class DisplayPreviewRegistry {
        constructor() {
            this.displays = new Map();
            this.loadPersistedState();
        }

        get(mac, spec) {
            const key = mac || "default";
            if (!this.displays.has(key)) {
                this.displays.set(key, new DisplayPreview(key, spec));
            } else if (spec) {
                this.displays.get(key).updateSpec(spec);
            }
            return this.displays.get(key);
        }

        getAll() {
            return Array.from(this.displays.values());
        }

        getDisplaysBoundTo(kind) {
            const k = (kind || "").toLowerCase();
            return this.getAll().filter(d => d.isBoundTo(k));
        }

        getActive() {
            const mac = (typeof window._activeDeviceMac === "function")
                ? window._activeDeviceMac()
                : "default";
            return this.get(mac);
        }

        syncFromFleet(devices) {
            if (!Array.isArray(devices)) return;
            devices.forEach(dev => {
                if (!dev || !dev.address) return;
                const spec = (typeof window.getDeviceDimensions === "function")
                    ? window.getDeviceDimensions(dev.name)
                    : { width: 16, height: 16, size: 16, name: dev.name };
                this.get(dev.address, spec);
            });
        }

        loadPersistedState() {
            try {
                const acts = JSON.parse(localStorage.getItem("divoomDeviceActivity") || "{}");
                const prevs = JSON.parse(localStorage.getItem("divoomDevicePreviews") || "{}");
                Object.keys(acts).forEach(mac => {
                    const act = acts[mac];
                    if (act && act.kind) {
                        const display = this.get(mac);
                        display.setActivity(act.kind, act.opts || {});
                        if (act.src) display.setFrame(act.src);
                    }
                });
                Object.keys(prevs).forEach(mac => {
                    if (prevs[mac]) {
                        this.get(mac).setFrame(prevs[mac]);
                    }
                });
            } catch (_) {}
        }
    }

    window.DisplayPreview = DisplayPreview;
    window.DisplayPreviewRegistry = new DisplayPreviewRegistry();
})();
