/* cloud_clock_faces.js — browse Divoom's public clock-face catalog
   (Channel/GetDialType + Channel/GetDialList) and apply one via the
   existing set_clock() path. No thumbnails are available from this API —
   only ClockId/Name — so the list is a plain text list, not a grid. */

document.addEventListener("DOMContentLoaded", () => {
    const typeSelect = document.getElementById("cloud-clock-type-select");
    const listEl = document.getElementById("cloud-clock-list");
    if (!typeSelect || !listEl) return;

    function renderClockList(faces) {
        if (!faces || faces.length === 0) {
            listEl.innerHTML = `<div class="empty-list">No clock faces in this category.</div>`;
            return;
        }
        listEl.innerHTML = faces.map(f => `
            <div class="cloud-clock-row" data-clock-id="${f.ClockId}">
                <span class="cloud-clock-name">${f.Name}</span>
                <button type="button" class="cloud-clock-apply-btn">Apply</button>
            </div>
        `).join("");
    }

    function loadCloudClockList(dialType) {
        if (!window.pywebview?.api?.get_dial_list) return;
        listEl.innerHTML = `<div class="empty-list">Loading…</div>`;
        window.pywebview.api.get_dial_list(dialType).then(reply => {
            const faces = window.DivoomCloud.unwrap(reply, listEl, "No clock faces.");
            if (faces === null) return;   // the reason is on screen
            renderClockList(faces);
        }).catch(() => {
            listEl.innerHTML = `<div class="empty-list">Failed to load clock faces.</div>`;
        });
    }

    // ── The store: faces WITH a picture (2026-09-13) ──────────────────────
    const storeEl = document.getElementById("cloud-clock-store");

    function selectedPanelSize() {
        const mac = (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null;
        const dev = (window.DivoomState?.discoveredDevices || []).find(d => d.address === mac);
        const dims = window.getDeviceDimensions ? window.getDeviceDimensions(dev?.name || "") : { size: 16 };
        return { size: dims.size || 16, name: dev?.name || "the panel" };
    }

    // One card: the face as drawn, and as the selected panel would show it.
    // Both come from ONE decoded picture (the daemon's), the device view is
    // the page's own rasterizer at the panel's diode count -- no second
    // renderer to drift.
    function renderStoreCard(face, panel) {
        const card = document.createElement("div");
        card.className = "clock-face-card";
        card.dataset.clockId = face.clock_id;
        card.innerHTML = `
            <div><img class="clock-face-original" alt=""><div class="clock-face-caption">as drawn</div></div>
            <div><img class="clock-face-device" alt=""><div class="clock-face-caption">on ${panel.name} (${panel.size}x${panel.size})</div></div>
            <div class="clock-face-meta">
                <span class="clock-face-name" title="${face.name || ""}">${face.name || "Clock face"}</span>
                <span class="text-12" style="color: var(--text-muted);">${face.category || ""} · id ${face.clock_id}</span>
                <button type="button" class="cloud-clock-apply-btn">Apply</button>
            </div>`;
        return card;
    }

    function fillStorePreviews(card, face, panel) {
        const orig = card.querySelector(".clock-face-original");
        const dev = card.querySelector(".clock-face-device");
        if (!face.image_file_id || !window.pywebview?.api?.get_animated_preview) return;
        window.pywebview.api.get_animated_preview(face.image_file_id).then(src => {
            if (!src || typeof src !== "string" || !src.startsWith("data:")) { orig.alt = "no picture"; return; }
            orig.src = src;
            if (window._rasterizeToPng) window._rasterizeToPng(src, panel.size, png => { if (png) dev.src = png; });
        }).catch(() => { orig.alt = "no picture"; });
    }

    window.renderClockFaceStore = function(faces) {
        if (!storeEl) return;
        storeEl.innerHTML = "";
        if (!faces || faces.length === 0) {
            storeEl.innerHTML = `<div class="empty-list">The store has no faces with pictures right now.</div>`;
            return;
        }
        const panel = selectedPanelSize();
        faces.forEach(face => {
            const card = renderStoreCard(face, panel);
            storeEl.appendChild(card);
            fillStorePreviews(card, face, panel);
        });
    };

    function loadClockFaceStore() {
        if (!storeEl || window.DivoomState.cloudClockStoreLoaded) return;
        if (!window.pywebview?.api?.get_store_clock_faces) return;
        window.DivoomState.cloudClockStoreLoaded = true;
        storeEl.innerHTML = `<div class="empty-list">Loading the store…</div>`;
        window.pywebview.api.get_store_clock_faces().then(reply => {
            const faces = window.DivoomCloud.unwrap(reply, storeEl, "The store is empty.");
            if (faces === null) { window.DivoomState.cloudClockStoreLoaded = false; return; }
            window.renderClockFaceStore(faces);
        }).catch(() => { window.DivoomState.cloudClockStoreLoaded = false; });
    }

    function loadCloudClockTypes() {
        loadClockFaceStore();
        if (window.DivoomState.cloudClockTypesLoaded) return;
        if (!window.pywebview?.api?.get_dial_types) return;
        window.DivoomState.cloudClockTypesLoaded = true;
        window.pywebview.api.get_dial_types().then(reply => {
            const types = window.DivoomCloud.unwrap(reply, listEl,
                                                    "No clock face categories.");
            if (types === null) {
                // Allow a retry: the category list failing is usually the
                // service being down, which the user can fix and come back.
                window.DivoomState.cloudClockTypesLoaded = false;
                return;
            }
            if (types.length === 0) return;
            typeSelect.innerHTML = types.map(t => `<option value="${t}">${t}</option>`).join("");
            loadCloudClockList(types[0]);
        }).catch(() => {
            window.DivoomState.cloudClockTypesLoaded = false;  // allow retry on next panel visit
        });
    }
    window.loadCloudClockTypes = loadCloudClockTypes;

    typeSelect.addEventListener("change", () => loadCloudClockList(typeSelect.value));

    // The Clock panel is active by default on page load (before any tab
    // click fires channels_core.js's showChannelPanel), so trigger the
    // initial fetch here too.
    if (document.getElementById("panel-clock")?.classList.contains("active")) {
        loadCloudClockTypes();
    }

    const onApplyClick = (e) => {
        const btn = e.target.closest(".cloud-clock-apply-btn");
        if (!btn) return;
        if (!window.requireDevice || !window.requireDevice()) return;
        const row = btn.closest("[data-clock-id]");
        const clockId = parseInt(row?.getAttribute("data-clock-id"));
        if (!clockId || !window.pywebview?.api?.set_clock) return;
        const color = document.getElementById("clock-color-input")?.value || "#ffffff";
        btn.disabled = true;
        window.pywebview.api.set_clock(clockId, color).then(res => {
            btn.disabled = false;
            window.showToast(res ? "Clock face applied" : "Failed to apply clock face", res ? "success" : "error", " BLE");
            if (res && window.setDeviceActivity) {
                window.setDeviceActivity(window._activeDeviceMac(), "clock", { style: clockId, color });
            }
        }).catch(() => {
            btn.disabled = false;
            window.showToast("Failed to apply clock face", "error");
        });
    };
    listEl.addEventListener("click", onApplyClick);
    if (storeEl) storeEl.addEventListener("click", onApplyClick);
});
