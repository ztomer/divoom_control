// Device selector: the per-device switch dots below the sidebar preview, plus
// the logic that keeps daemon-owned (connected, non-advertising) screens in the
// list so they stay selectable. Split out of app_globals.js to stay under the
// 500-LOC file cap.

// R46 #5: a re-scan replaced discoveredDevices wholesale, so a device the
// daemon is busy STREAMING to (connected → not advertising → scan misses it)
// vanished from the selector. Union the fresh scan with the known devices by
// address (fresh data wins) so an in-use device stays selectable.
//
// R62 (user-reported): the union was PERMANENT — once an address was seen
// this session it never showed "not in range" again even after genuinely
// dropping out of BLE range, since nothing ever downgraded it. A single scan
// miss isn't reliable proof of absence (a scan can legitimately skip a
// present device), so this counts CONSECUTIVE misses per address and only
// flips `unconfirmed` after `MISS_THRESHOLD` in a row — same signal quality
// as the original session-restore "not in range" state, just live instead
// of one-shot. `daemonOwned` devices are exempt: a live-widget stream keeps
// the device connected (hence not advertising, hence always "missed" by a
// scan) by design — that's not absence.
window.MISS_THRESHOLD = 2;
window.mergeDiscoveredDevices = function(fresh) {
    const byAddr = {};
    (window.DivoomState.discoveredDevices || []).forEach(d => {
        if (d && d.address) byAddr[d.address] = d;
    });
    const freshAddrs = new Set((fresh || []).filter(d => d && d.address).map(d => d.address));
    Object.keys(byAddr).forEach(addr => {
        if (freshAddrs.has(addr) || byAddr[addr].daemonOwned) return;
        const misses = (byAddr[addr].scanMisses || 0) + 1;
        byAddr[addr] = Object.assign({}, byAddr[addr], {
            scanMisses: misses,
            unconfirmed: misses >= window.MISS_THRESHOLD ? true : !!byAddr[addr].unconfirmed,
        });
    });
    (fresh || []).forEach(d => {
        // A fresh scan finding this address means it's confirmed present RIGHT
        // NOW — clear the miss counter and any "not in range" flag.
        if (d && d.address) byAddr[d.address] = Object.assign({}, byAddr[d.address] || {}, d, {
            scanMisses: 0, unconfirmed: false,
        });
    });
    window.DivoomState.discoveredDevices = Object.values(byAddr);
    return window.DivoomState.discoveredDevices;
};

// R47: a device the daemon OWNS (active link or a background live-widget job)
// is connected, so it doesn't advertise and a BLE scan never sees it. Without
// this it shows as "connected" in the appbar but has no selector chip — you
// can't switch to it or stop its widget. Pull the daemon's activity registry
// and union those macs into the selector so an owned device is ALWAYS
// selectable, tagged with what it's streaming.
window.refreshOwnedDevices = function() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.get_device_activity) return;
    api.get_device_activity().then(raw => {
        let act;
        try { act = JSON.parse(raw) || {}; } catch (e) { return; }
        let changed = false;
        Object.keys(act).forEach(mac => {
            if (mac === "MatrixWall") return;   // the wall has its own button
            const info = act[mac] || {};
            const kind = info.kind || "";
            const state = info.state || "";   // G5: daemon-owned device health
            const streaming = kind && kind !== "idle";
            const known = (window.DivoomState.discoveredDevices || [])
                .find(d => d.address === mac);
            if (!known) {
                window.DivoomState.discoveredDevices.push({
                    address: mac, name: info.name || "Screen",
                    daemonOwned: true, activityKind: kind, activityState: state,
                });
                changed = true;
            } else {
                // The daemon reporting ANY activity entry for this mac means it
                // currently owns/knows the device — definitely present, not just
                // remembered from a prior session.
                if (known.unconfirmed) { known.unconfirmed = false; changed = true; }
                if (info.name && known.name !== info.name) {
                    known.name = info.name; changed = true;
                }
                if (known.activityKind !== kind) {
                    known.activityKind = kind; changed = true;
                }
                if (known.activityState !== state) {
                    known.activityState = state; changed = true;
                }
                if (streaming && !known.daemonOwned) {
                    known.daemonOwned = true; changed = true;
                }
            }
        });
        if (changed && window.renderDeviceDots) window.renderDeviceDots();
    }).catch(() => {});
};

// ── R48: per-device switch chips — named, self-labeling, click to switch ──
// Replaces the unlabeled colored dots (Rams R4: understandable without hover;
// Rams R7: works at 4+ devices; Kare: affordance is obvious at a glance).
window.renderDeviceDots = function() {
    const host = document.getElementById("device-dots");
    if (!host) return;
    const activeMac = (document.getElementById("banner-device-mac")?.textContent || "").trim();
    const entries = [];
    (window.DivoomState.discoveredDevices || []).forEach(d => {
        if (d.address) entries.push({
            value: d.address, name: d.name || "Bluetooth Screen",
            streaming: !!(d.daemonOwned && d.activityKind && d.activityKind !== "idle"),
            kind: d.activityKind || "",
            // G5: an owned device whose link degraded/dropped (self-healing).
            degraded: d.activityState === "degraded" || d.activityState === "disconnected",
            // Restored from a prior session/known-devices cache, not yet
            // confirmed present by a scan or the daemon's owned-device
            // activity this session — same "not in range" treatment as the
            // knownPending merge below.
            known: !!d.unconfirmed,
        });
    });
    (window.DivoomState.registeredLanDevices || []).forEach(d => {
        if (d.ip) entries.push({ value: `LAN:${d.ip}`, name: `Wi-Fi: ${d.ip}` });
    });
    // Merge known-but-undetected devices from the persistent cache
    const knownPending = window.__knownUndetectedDevices;
    if (knownPending && knownPending.length) {
        const existing = new Set(entries.map(e => e.value));
        knownPending.forEach(d => {
            if (!existing.has(d.address)) {
                entries.push({ value: d.address, name: d.name, known: true });
                existing.add(d.address);
            }
        });
    }
    host.innerHTML = "";
    entries.forEach(e => {
        const isActive = e.value === activeMac;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "device-chip" + (isActive ? " chip-active" : "");
        // R47: streaming = daemon owns it (live widget); degraded = link struggling.
        if (e.streaming && !isActive) chip.classList.add("chip-streaming");
        if (e.degraded) chip.classList.add("chip-degraded");
        if (e.known && !isActive) chip.classList.add("chip-known");
        // data-value: R34 §2 — connectDevice pulses this element while connecting.
        chip.dataset.value = e.value;
        chip.title = e.degraded ? `${e.name} — ${e.kind} (reconnecting)`
                   : e.streaming ? `${e.name} — ${e.kind}`
                   : (e.known && !isActive) ? `${e.name} — not in range (click to retry)` : e.name;
        chip.setAttribute("role", "tab");
        chip.setAttribute("aria-selected", isActive ? "true" : "false");

        // Color dot — 8 px, same hue as before; currentColor drives the animation.
        const color = window.deviceColor(e.value);
        const dotEl = document.createElement("span");
        dotEl.className = "device-chip-dot";
        dotEl.style.background = color;
        dotEl.style.color = color;

        const nameEl = document.createElement("span");
        nameEl.className = "device-chip-name";
        nameEl.textContent = e.name;

        chip.appendChild(dotEl);
        chip.appendChild(nameEl);

        // Right-aligned state badge — only when non-idle (streaming, degraded,
        // or known-but-currently-undetected). Rams R4: a faded chip alone is too
        // subtle to read as "not connectable right now" at a glance — say so.
        if (e.degraded) {
            const st = document.createElement("span");
            st.className = "device-chip-state";
            st.textContent = "reconnecting";
            chip.appendChild(st);
        } else if (e.streaming) {
            const st = document.createElement("span");
            st.className = "device-chip-state";
            st.textContent = e.kind;
            chip.appendChild(st);
        } else if (e.known && !isActive) {
            // Never mislabel the actively-connected device "not in range" —
            // it clearing (unconfirmed=false) usually races a fast connect,
            // but active status is the stronger, more current signal.
            const st = document.createElement("span");
            st.className = "device-chip-state device-chip-state-known";
            st.textContent = "not in range";
            chip.appendChild(st);
        }

        chip.addEventListener("click", () => window.connectDevice(e.name, e.value));
        host.appendChild(chip);
    });
    if (window.renderWallButton) window.renderWallButton();
};

// The Virtual Wall gets a distinct chip — same visual language as device chips
// (named, self-labeling) but with a dashed border and a "joined panels" glyph
// (two landscape rects sharing a surface) that is deliberately distinct from the
// 2×2 filled-rects used by the Pixel Art nav tab. Count folded into the label.
// Shown only when a wall is configured (Rams: no empty control).
window.renderWallButton = function() {
    const host = document.getElementById("wall-button");
    if (!host) return;
    const slots = window.DivoomState.assignedSlots || {};
    const n = Object.keys(slots).length;
    host.innerHTML = "";
    host.hidden = n === 0;
    if (n === 0) return;
    const activeMac = (document.getElementById("banner-device-mac")?.textContent || "").trim();
    const isActive = activeMac === "MatrixWall";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "wall-button" + (isActive ? " active" : "");
    btn.dataset.value = "MatrixWall";
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
    btn.title = `Virtual Wall — drive ${n} screen${n === 1 ? "" : "s"} as one display`;
    // Glyph: a wide bounding rect split by a vertical line = "multi-display span".
    // Distinct from the 2×2 filled squares of the Pixel Art tab.
    btn.innerHTML =
        '<svg class="wall-button-glyph" viewBox="0 0 16 11" width="14" height="10"' +
        ' fill="none" stroke="currentColor" stroke-width="1.5"' +
        ' stroke-linejoin="round" aria-hidden="true">' +
        '<rect x="1" y="1" width="14" height="9" rx="1"/>' +
        '<line x1="8" y1="1" x2="8" y2="10"/></svg>' +
        `<span class="wall-button-label">Wall (${n})</span>`;
    btn.addEventListener("click", () => window.connectDevice("Virtual Wall", "MatrixWall"));
    host.appendChild(btn);
};

// R47: surface a scan in progress in the main UI (the Scan button is buried in
// Settings, so a scan used to give no feedback in the sidebar where the device
// dots live).
window.setScanning = function(on) {
    const el = document.getElementById("scan-indicator");
    if (el) el.hidden = !on;
};

// Load known devices from persistent cache and merge in undetected ones
window.refreshKnownDevices = function() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.get_known_devices) return;
    api.get_known_devices().then(json => {
        try {
            const known = JSON.parse(json) || [];
            window.__knownUndetectedDevices = known;
            window.renderDeviceDots();
        } catch (e) {
            window.__knownUndetectedDevices = [];
        }
    });
};
