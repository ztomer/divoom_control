/* channels_grids.js — Clock faces, visualizers, channels, art grids */
document.addEventListener("DOMContentLoaded", () => {
    // ── 3. CLOCK FACES GRID ──
    const CLOCK_FACES = [
        { value: 0, name: "Full Screen" }, { value: 1, name: "Rainbow" },
        { value: 2, name: "With Box" }, { value: 3, name: "Analog Square" },
        { value: 4, name: "Full Screen Neg" }, { value: 5, name: "Analog Round" },
    ];
    const CLOCK_PREVIEWS = {
        0: `<div class="clock-preview-box digital-full">12:00</div>`,
        1: `<div class="clock-preview-box digital-rainbow">12:00</div>`,
        2: `<div class="clock-preview-box digital-box"><span>12:00</span></div>`,
        3: `<div class="clock-preview-box analog-square">
                <svg class="mini-clock-svg" viewBox="0 0 40 40">
                    <rect x="2" y="2" width="36" height="36" rx="4" fill="none" stroke="currentColor" stroke-width="2"/>
                    <line x1="20" y1="20" x2="20" y2="10" stroke="currentColor" stroke-width="2"/>
                    <line x1="20" y1="20" x2="30" y2="20" stroke="currentColor" stroke-width="1.5"/>
                </svg>
            </div>`,
        4: `<div class="clock-preview-box digital-neg">12:00</div>`,
        5: `<div class="clock-preview-box analog-round">
                <svg class="mini-clock-svg" viewBox="0 0 40 40">
                    <circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" stroke-width="2"/>
                    <line x1="20" y1="20" x2="20" y2="10" stroke="currentColor" stroke-width="2"/>
                    <line x1="20" y1="20" x2="28" y2="25" stroke="currentColor" stroke-width="1.5"/>
                </svg>
            </div>`
    };

    // R73: the "Extra Panels" checkboxes. Confirmed on hardware -- the device
    // does not overlay these on the clock face, it CYCLES separate weather /
    // date / temperature / clock screens. With none ticked we stay on the
    // plain set_clock() path, so the default behaviour is unchanged.
    const richBox = (id) => document.getElementById(id)?.checked || false;
    function clockExtras() {
        return {
            humidity: richBox("clock-rich-humidity"),
            weather:  richBox("clock-rich-weather"),
            date:     richBox("clock-rich-date"),
            twentyfour: document.getElementById("clock-rich-24h")?.checked !== false,
        };
    }

    function applyClockStyle(style) {
        if (!window.requireDevice()) return;
        const color = document.getElementById("clock-color-input")?.value || "#ffffff";
        if (!(window.pywebview && window.pywebview.api)) return;
        const x = clockExtras();
        const rich = x.humidity || x.weather || x.date;
        const call = rich
            ? window.pywebview.api.set_clock_rich(style, x.twentyfour, x.humidity, x.weather, x.date, color)
            : window.pywebview.api.set_clock(style, color);
        call.then(res => {
            const what = rich ? "Clock + extra panels applied" : "Clock style applied";
            window.showToast(res ? what : "Failed to apply clock", res ? "success" : " BLE");
            // R50: reflect the SPECIFIC face + color on the device preview.
            if (res && window.setDeviceActivity)
                window.setDeviceActivity(window._activeDeviceMac(), "clock", { style, color });
        });
    }

    // Re-apply when an extra is toggled, so the checkbox is not dead until the
    // user re-picks a face.
    ["clock-rich-humidity", "clock-rich-weather", "clock-rich-date", "clock-rich-24h"]
        .forEach(id => document.getElementById(id)?.addEventListener("change", () => {
            applyClockStyle(window.DivoomState.selectedClockStyle ?? 0);
        }));

    window.DivoomState.selectedClockStyle = 0;
    window.buildSelectorGrid("clock-faces-grid", CLOCK_FACES, (v) => {
        window.DivoomState.selectedClockStyle = v;
        applyClockStyle(v);
    }, 0, CLOCK_PREVIEWS);

    function updateClockPreviewsColor(color) {
        // Style 0 (Full Screen Digital) - update text color and text shadow
        const style0 = document.querySelector(".clock-preview-box.digital-full");
        if (style0) {
            style0.style.color = color;
            style0.style.textShadow = `0 0 6px ${color}`;
        }
        
        // Style 2 (With Box) - update box style: border color and time color
        const style2Span = document.querySelector(".clock-preview-box.digital-box span");
        if (style2Span) {
            style2Span.style.color = color;
            style2Span.style.borderColor = color;
            style2Span.style.textShadow = `0 0 4px ${color}`;
        }
        
        // Style 3 (Analog Square) - update SVG stroke colors
        const style3Svg = document.querySelector(".clock-preview-box.analog-square svg");
        if (style3Svg) {
            style3Svg.querySelectorAll("rect, line").forEach(el => {
                el.style.stroke = color;
            });
            style3Svg.style.color = color;
        }
        
        // Style 4 (Full Screen Neg) - inverted: background is color, text is dark
        const style4 = document.querySelector(".clock-preview-box.digital-neg");
        if (style4) {
            style4.style.backgroundColor = color;
            style4.style.color = "#1a2318";
            style4.style.textShadow = "none";
        }
        
        // Style 5 (Analog Round) - update SVG stroke colors
        const style5Svg = document.querySelector(".clock-preview-box.analog-round svg");
        if (style5Svg) {
            style5Svg.querySelectorAll("circle, line").forEach(el => {
                el.style.stroke = color;
            });
            style5Svg.style.color = color;
        }
    }

    const clockColorInput = document.getElementById("clock-color-input");
    if (clockColorInput) {
        clockColorInput.addEventListener("input", (e) => {
            const color = e.target.value;
            updateClockPreviewsColor(color);
            applyClockStyle(selectedClockStyle);
        });
        
        // Call it initially after a small timeout to let the grid render
        setTimeout(() => {
            updateClockPreviewsColor(clockColorInput.value || "#ffffff");
        }, 500);
    }

    // ── 4. VJ EFFECTS GRID ──
    const VJ_EFFECTS = ["Sparkles", "Lava", "Vertical Rainbow", "Drops", "Rainbow Swirl",
        "CMY Fade", "Rainbow Lava", "Pastel Patterns", "CMY Wave", "Fire", "Countdown",
        "Pink/Blue Fade", "Rainbow Polygons", "Pink/Blue Wave", "Rainbow Cross", "Rainbow Shapes"]
        .map((name, i) => ({ value: i, name }));
        
    const VJ_PREVIEWS = {};
    for (let i = 0; i < 16; i++) {
        const vjIndex = i + 2; // maps python 0-15 to VJ assets index 2-17
        const assetNum = vjIndex > 16 ? 16 : vjIndex;
        VJ_PREVIEWS[i] = `<div class="apk-preview-container">
            <img class="apk-preview-img inactive-img" src="assets/icon_vj_${assetNum}_n3x.webp" alt="VJ ${i}">
            <img class="apk-preview-img active-img" src="assets/icon_vj_${assetNum}_y3x.webp" alt="VJ ${i} Active">
        </div>`;
    }

    window.buildSelectorGrid("vj-effects-grid", VJ_EFFECTS, (v) => {
        if (!window.requireDevice()) return;
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_vj_effect) {
            window.pywebview.api.set_vj_effect(v).then(res => {
                window.showToast(res ? "VJ effect applied" : "Failed to apply VJ effect", res ? "success" : " BLE");
            });
        }
    }, -1, VJ_PREVIEWS);

    // ── 5. MUSIC EQ GRID ──
    const EQ_MAPPING = [1, 6, 3, 5, 10, 13, 4, 14, 9, 2, 11, 12];
    const EQ_PATTERNS = EQ_MAPPING.map((eqId, idx) => ({ value: idx, name: `EQ ${String(idx + 1).padStart(2, "0")}` }));
    const EQ_PREVIEWS = {};
    for (let i = 0; i < EQ_MAPPING.length; i++) {
        const eqIndex = EQ_MAPPING[i];
        let inactiveSrc, activeSrc;
        
        if ([1, 2, 3, 4, 5, 6, 9, 10].includes(eqIndex)) {
            inactiveSrc = `assets/icon_eq_${eqIndex}_n3x.webp`;
            activeSrc = `assets/icon_eq_${eqIndex}_y3x.webp`;
        } else if ([11, 12, 13, 14].includes(eqIndex)) {
            inactiveSrc = `assets/icon_eq_${eqIndex}_n.webp`;
            activeSrc = `assets/icon_eq_${eqIndex}_y.webp`;
        } else {
            inactiveSrc = `assets/icon_eq_unkonow_n.webp`;
            activeSrc = `assets/icon_eq_unkonow_y.webp`;
        }
        
        EQ_PREVIEWS[i] = `<div class="apk-preview-container">
            <img class="apk-preview-img inactive-img" src="${inactiveSrc}" alt="EQ ${eqIndex}">
            <img class="apk-preview-img active-img" src="${activeSrc}" alt="EQ ${eqIndex} Active">
        </div>`;
    }

    window.buildSelectorGrid("eq-visualizer-grid", EQ_PATTERNS, (v) => {
        if (!window.requireDevice()) return;
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_visualization) {
            window.pywebview.api.set_visualization(v).then(res => {
                window.showToast(res ? "EQ pattern applied" : "Failed to apply EQ", res ? "success" : " BLE");
            });
        }
    }, -1, EQ_PREVIEWS);

    // ── 6. AMBIENT COLOR TRIGGERS ──
    const ambientColorInput = document.getElementById("ambient-color-input");
    const ambientSwatches = document.querySelectorAll(".ambient-swatch");
    
    const AMBIENT_EFFECTS = [
        { value: 0, name: "Plain Color" },
        { value: 1, name: "Love (Pulse)" },
        { value: 2, name: "Plants (Breathe)" },
        { value: 3, name: "Sleeping (Fade)" },
        { value: 4, name: "No Mosquitto" }
    ];
    // R67: these tiles used to be FABRICATED colour blocks — a red-and-blue
    // SVG for "Plants", a flat green for "Sleeping", a translucent orange for
    // "No-Mosquito". Nothing produced those colours; they were guesses drawn to
    // look like something. That is why the ambient bug reached the user as
    // "the rest are green/magenta" rather than "the mode never reached the
    // device": the tiles showed a confident picture that had no connection to
    // the panel, so a completely dead feature looked merely wrong.
    //
    // Only ONE of these is knowable in the browser: Plain Colour, which is
    // exactly the colour the user picked. The other four are generated by the
    // device from a fixed internal palette we do not have. So Plain shows the
    // real colour, and the rest say honestly that the device draws them —
    // an honest placeholder beats an invented one (house rule: a placeholder
    // must never masquerade as the real thing).
    const deviceEffectTile = (label) => `
        <div class="ambient-preview device-effect" style="height:90px; border-radius:4px;">
            <span class="ambient-preview-label">${label}</span>
            <span class="ambient-preview-note">drawn by the device</span>
        </div>`;

    const AMBIENT_PREVIEWS = {
        0: `<div class="ambient-preview plain" style="background:#00ffcc; height:90px; border-radius:4px; box-shadow: 0 0 10px rgba(0,255,204,0.3);"></div>`,
        1: deviceEffectTile("Love"),
        2: deviceEffectTile("Plants"),
        3: deviceEffectTile("Sleeping"),
        4: deviceEffectTile("No-Mosquito"),
    };

    let selectedAmbientMode = 0;

    /// Highlight the mode the device actually accepted; `null` clears it.
    function markActiveAmbientMode(mode) {
        document.querySelectorAll("#ambient-mode-grid [data-value]").forEach(el => {
            const isActive = mode !== null && parseInt(el.getAttribute("data-value")) === mode;
            el.classList.toggle("ambient-mode-active", isActive);
        });
    }
    window.markActiveAmbientMode = markActiveAmbientMode;

    function updateAmbientPreviewsColor(color) {
        const plainPreviews = document.querySelectorAll(".ambient-preview.plain");
        plainPreviews.forEach(p => {
            p.style.backgroundColor = color;
            p.style.boxShadow = `0 0 10px ${color}4d`;
        });
    }

    window.applyAmbientColor = function(color) {
        if (!window.requireDevice()) return;
        const brightness = parseInt(document.getElementById("global-brightness-slider")?.value) || 80;
        const modeType = selectedAmbientMode;
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_solid_light) {
            window.pywebview.api.set_solid_light(color, brightness, modeType).then(res => {
                window.showToast(res ? "Ambient mode applied" : "Failed to apply ambient", res ? "success" : " BLE");
                // R67: mark what the DEVICE is on, not what was clicked. The
                // apply can fail (LAN cannot express modes 1-4 at all), and a
                // tile that highlights on click regardless would report success
                // the device never gave.
                markActiveAmbientMode(res ? modeType : null);
                if (res && window.setDeviceActivity)
                    window.setDeviceActivity(window._activeDeviceMac(), "ambient", { color, mode: modeType });
            });
        }
    }

    // R11 item 3a: the color picker/swatches/favorites only affect "Plain Color"
    // (mode 0); the other ambient effects use fixed palettes, so hide the color
    // controls for them.
    function updateAmbientColorVisibility() {
        const show = parseInt(selectedAmbientMode) === 0;
        const controls = document.getElementById("ambient-color-controls");
        const favorites = document.getElementById("ambient-favorites-grid");
        if (controls) controls.style.display = show ? "flex" : "none";
        if (favorites) favorites.style.display = show ? "flex" : "none";
    }

    window.buildSelectorGrid("ambient-mode-grid", AMBIENT_EFFECTS, (v) => {
        selectedAmbientMode = parseInt(v);
        const color = ambientColorInput?.value || "#00ffcc";
        window.applyAmbientColor(color);
        updateAmbientColorVisibility();
    }, 0, AMBIENT_PREVIEWS);

    // Call it initially after grid builds
    setTimeout(() => {
        const initialColor = ambientColorInput?.value || "#00ffcc";
        updateAmbientPreviewsColor(initialColor);
        updateAmbientColorVisibility();
    }, 500);

    // ── 10-favorites (last-selected colors) — Kare-style bitmap clarity, Rams #10 overridden per user ──
    const FAVORITES_KEY = "divoom-ambient-favorites";
    const FAVORITES_MAX = 10;
    function loadFavorites() {
        try { return JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]"); }
        catch (e) { return []; }
    }
    function saveFavorites(favs) {
        localStorage.setItem(FAVORITES_KEY, JSON.stringify(favs));
    }
    function pushFavorite(color) {
        if (!color) return;
        const norm = color.toLowerCase();
        const favs = loadFavorites().filter(c => c.toLowerCase() !== norm);
        favs.unshift(norm);
        if (favs.length > FAVORITES_MAX) favs.length = FAVORITES_MAX;
        saveFavorites(favs);
        renderFavorites();
    }
    function renderFavorites() {
        const grid = document.getElementById("ambient-favorites-grid");
        if (!grid) return;
        const label = grid.querySelector("span");
        grid.innerHTML = "";
        if (label) grid.appendChild(label);
        const favs = loadFavorites();
        favs.forEach(color => {
            const btn = document.createElement("button");
            btn.className = "ambient-swatch ambient-favorite";
            btn.style.background = color;
            btn.setAttribute("data-color", color);
            btn.setAttribute("title", color);
            btn.addEventListener("click", () => {
                if (ambientColorInput) ambientColorInput.value = color;
                ambientSwatches.forEach(s => s.classList.remove("active"));
                updateAmbientPreviewsColor(color);
                window.applyAmbientColor(color);
            });
            grid.appendChild(btn);
        });
    }
    renderFavorites();

    ambientSwatches.forEach(swatch => {
        swatch.addEventListener("click", () => {
            ambientSwatches.forEach(s => s.classList.remove("active"));
            swatch.classList.add("active");
            const color = swatch.getAttribute("data-color");
            if (ambientColorInput) ambientColorInput.value = color;
            updateAmbientPreviewsColor(color);
            pushFavorite(color);
            window.applyAmbientColor(color);
        });
    });

    if (ambientColorInput) {
        ambientColorInput.addEventListener("input", (e) => {
            ambientSwatches.forEach(s => s.classList.remove("active"));
            const color = e.target.value.toLowerCase();
            ambientSwatches.forEach(s => {
                if (s.getAttribute("data-color").toLowerCase() === color) {
                    s.classList.add("active");
                }
            });
            updateAmbientPreviewsColor(color);
        });
        ambientColorInput.addEventListener("change", (e) => {
            const color = e.target.value;
            pushFavorite(color);
            window.applyAmbientColor(color);
        });
    }

    // ── 7. DYNAMIC VJ EFFECTS TOGGLE & GALLERY CACHE SELECTOR (R15 §1+§7: `.channel-card` → `.tab-btn`) ──
    window.updateChannelButtonsVisibility = function(name) {
        const n = (name || "").toLowerCase();

        // R24 #5: FM Radio card — only FM-capable models (Tivoo / Ditoo).
        const fmCard = document.getElementById("fm-radio-card");
        if (fmCard) fmCard.style.display = (n.includes("tivoo") || n.includes("ditoo")) ? "" : "none";

        const vjCard = document.querySelector('.tab-btn[data-channel="vj"]');
        if (!vjCard) return;

        // Timebox Evo supports VJ effects
        const supportsVJ = n.includes("timebox") || n.includes("evo");
        if (supportsVJ) {
            vjCard.style.display = "";
        } else {
            vjCard.style.display = "none";
            // Auto-switch to clock mode if active channel was VJ
            if (window.DivoomState.activeChannel === "vj") {
                const clockCard = document.querySelector('.tab-btn[data-channel="clock"]');
                if (clockCard) clockCard.click();
            }
        }
    };
    
    // Hide VJ by default
    window.updateChannelButtonsVisibility("");

    let _customArtCacheFiles = [];   // R24 #7a: cached so search can filter without refetching

    function renderCustomArtCacheGrid(filter) {
        const grid = document.getElementById("custom-art-cache-grid");
        if (!grid) return;
        const q = (filter || "").trim().toLowerCase();
        const files = q
            ? _customArtCacheFiles.filter(f => (f.name || "").toLowerCase().includes(q))
            : _customArtCacheFiles;
        grid.innerHTML = "";
        if (!files || files.length === 0) {
            grid.innerHTML = `<div class="empty-list" style="grid-column: 1/-1;">${
                _customArtCacheFiles.length === 0
                    ? "No cached gallery files. Download them in Monthly Best first!"
                    : "No matches."}</div>`;
            return;
        }
        files.forEach(f => {
            // Click-to-assign tiles: custom_art.js delegates clicks on the grid
            // and places the tile's art into the selected/next free slot.
            const wrapper = document.createElement("div");
            wrapper.className = "cache-item cache-thumb-item";
            wrapper.dataset.name = f.name || "";
            wrapper.dataset.fileId = f.file_id || f.path;
            wrapper.title = f.name;
            wrapper.draggable = true;
            wrapper.style.cssText = `
                display:flex; flex-direction:column; align-items:center; gap:2px;
                background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.1);
                border-radius:4px; padding:4px; cursor:pointer; position:relative;
            `;

            const img = document.createElement("img");
            img.src = f.preview_url;
            img.dataset.fileId = f.file_id || f.path;
            img.style.cssText = "width:100%; aspect-ratio:1; object-fit:contain; image-rendering:pixelated; border-radius:2px;";

            wrapper.appendChild(img);
            grid.appendChild(wrapper);
        });
        if (window.customArtSyncLibrary) window.customArtSyncLibrary();
    }

    function loadCustomArtCacheGrid() {
        const grid = document.getElementById("custom-art-cache-grid");
        if (!grid) return;
        grid.innerHTML = '<div class="empty-list" style="grid-column: 1/-1;">Loading offline cache...</div>';
        if (window.pywebview && window.pywebview.api && window.pywebview.api.get_cached_gallery_files) {
            window.pywebview.api.get_cached_gallery_files().then(json => {
                try { _customArtCacheFiles = JSON.parse(json) || []; } catch (e) { _customArtCacheFiles = []; }
                const search = document.getElementById("custom-art-search");
                renderCustomArtCacheGrid(search ? search.value : "");
            });
        }
    }

    // R24 #7a: live search over the cached gallery (filters by name; no refetch).
    const customArtSearch = document.getElementById("custom-art-search");
    if (customArtSearch) {
        customArtSearch.addEventListener("input", () => renderCustomArtCacheGrid(customArtSearch.value));
    }

    // Expose for cross-file access from channels_core.js showChannelPanel
    window.loadCustomArtCacheGrid = loadCustomArtCacheGrid;

    // R42 §3: custom art lives in Pixel Art now and is its DEFAULT sub-tab, so
    // entering the section must load the library (the old trigger was the
    // removed Channels "design" panel switch).
    window.addEventListener("tab-changed", (e) => {
        if (e.detail && e.detail.tab === "pixel-art") {
            const active = document.querySelector(".tab-btn[data-pixel-tab].active");
            if (!active || active.getAttribute("data-pixel-tab") === "pixel-custom-art") {
                setTimeout(loadCustomArtCacheGrid, 50);
            }
        }
    });
});
