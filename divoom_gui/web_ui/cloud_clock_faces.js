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

    function loadCloudClockTypes() {
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

    listEl.addEventListener("click", (e) => {
        const btn = e.target.closest(".cloud-clock-apply-btn");
        if (!btn) return;
        if (!window.requireDevice || !window.requireDevice()) return;
        const row = btn.closest(".cloud-clock-row");
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
    });
});
