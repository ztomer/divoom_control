/* app_globals.js — Global state, utilities, connection actions, arranger render */
/* app.js — Main UI coordinator, free-form display wall arranger, and local configurations */

// ── 1. GLOBAL STATE INITIALIZATION ──
window.DivoomState = {
    appConnected: false,
    discoveredDevices: [],
    assignedSlots: {},
    selectedColor: "00FFCC",
    activeChannel: "clock",
    registeredLanDevices: [],
    loadedArtworks: [],
    selectedArtworkIndex: null,
    savedTickers: [],
    // R32 §C2: last image pushed to each device (address → image src).
    devicePreviews: {},
    // R46 #2: last-active element per device (address → {kind, src}).
    deviceActivity: {}
};

// R32 §C2: persist last-pushed previews across restarts via localStorage.
try {
    window.DivoomState.devicePreviews = JSON.parse(localStorage.getItem("divoomDevicePreviews") || "{}");
} catch (e) { window.DivoomState.devicePreviews = {}; }
try {
    window.DivoomState.deviceActivity = JSON.parse(localStorage.getItem("divoomDeviceActivity") || "{}");
} catch (e) { window.DivoomState.deviceActivity = {}; }

// ── 2. GLOBAL UTILITY FUNCTIONS ──
window.showToast = function(message, type = "success", transport = null) {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.className = `toast ${type} show`;
    const suffix = transport ? `<span class="toast-transport">${transport}</span>` : '';
    toast.innerHTML = message + suffix;
    setTimeout(() => { toast.classList.remove("show"); }, 3000);
};

window.requireDevice = function() {
    if (!window.DivoomState.appConnected) {
        window.showToast("Connect a device first — scan and connect under Settings.", "error");
        return false;
    }
    return true;
};

window.deviceColor = function(key) {
    let h = 0, s = String(key || "");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return `hsl(${h % 360}, 70%, 55%)`;
};

// ── R49: flat face-on screen preview ──────────────────────────────────
// The device can't report its framebuffer, so we mirror the last frame this
// app (or a daemon live job) pushed. R49: the product photos are 3/4
// perspective renders, so compositing a frame onto them landed it crooked.
// We now show the frame straight in a neutral bezel (#banner-device-screen) —
// a face-on screen, aligned for any model, with no per-model rect to tune.

window._setScreenOverlayFrame = function(src) {
    const screen = document.getElementById("banner-device-screen");
    if (!screen) return;
    if (src) {
        screen.style.backgroundImage = `url("${src}")`;
        screen.classList.add("has-frame");
    } else {
        screen.style.backgroundImage = "";
        screen.classList.remove("has-frame");
    }
};

// Empty-state hint below the screen. When a device IS active, its name is
// already shown (highlighted) in the chip directly below — repeating it here was
// redundant, so we only show this as the "nothing connected" placeholder.
window._updateDeviceLabel = function(name) {
    const label = document.getElementById("banner-device-label");
    if (!label) return;
    const n = (name || "").trim();
    if (!n || n === "None" || n === "No Connected Screen") {
        label.textContent = "No screen connected";
        label.hidden = false;
    } else {
        label.hidden = true;   // the active chip carries the name
    }
};

window.setDevicePreview = function(address, src) {
    if (!address || !src) return;
    window.DivoomState.devicePreviews[address] = src;
    try {
        localStorage.setItem("divoomDevicePreviews", JSON.stringify(window.DivoomState.devicePreviews));
    } catch (e) { /* quota — non-fatal */ }
    const activeMac = (document.getElementById("banner-device-mac")?.textContent || "").trim();
    if (activeMac === address) {
        window._setScreenOverlayFrame(src);
    }
};

window.restoreDevicePreview = function(address, _fallbackSrc) {
    // R49: no product photo anymore — just show this device's last frame in the
    // flat screen (or the empty state when nothing has been pushed yet).
    window._setScreenOverlayFrame(window.DivoomState.devicePreviews[address] || null);
};

// ── R46 #2: per-device "last active element" preview ──────────────────────
// The channel-preview renderers (_clockFaceSVG / _channelPreviewSVG) live in
// channel_preview.js to keep this file under the 500-LOC cap.

// Set a device's "last active" preview: kind="image" uses opts.src (a real
// frame); any channel kind draws its glyph. Persists via setDevicePreview and
// records the kind (for the appbar tooltip / the menubar previews, #3).
window.setDeviceActivity = function(mac, kind, opts) {
    if (!mac || mac === "None") return;
    opts = opts || {};
    const src = (kind === "image" && opts.src) ? opts.src : window._channelPreviewSVG(kind, opts);
    window.DivoomState.deviceActivity = window.DivoomState.deviceActivity || {};
    window.DivoomState.deviceActivity[mac] = { kind: kind, src: src, at: Date.now() };
    try { localStorage.setItem("divoomDeviceActivity", JSON.stringify(window.DivoomState.deviceActivity)); } catch (e) {}
    window.setDevicePreview(mac, src);
    // R46 #3 / R50: push the CHANNEL kind + a PNG thumbnail to the daemon so the
    // menubar can show a per-device tile with the actual face (not a generic
    // glyph). Live-widget image content is skipped here — the daemon sets that
    // kind itself (sysmon/stocks/weather/music) on live_job_start, so we'd only
    // clobber it with "image".
    if (kind !== "image" && window.pywebview?.api?.set_device_activity) {
        const dev = (window.DivoomState.discoveredDevices || []).find(d => d.address === mac);
        const name = (dev && dev.name) || (mac === window._activeDeviceMac()
            ? (document.getElementById("banner-device-name")?.textContent || "").trim() : "");
        // NSImage can't reliably decode SVG, so rasterize to a small PNG first.
        window._rasterizeToPng(src, 36, function(png) {
            try { window.pywebview.api.set_device_activity(mac, kind, name || "", png || ""); }
            catch (e) {}
        });
    }
};

// Rasterize an SVG/image data URL to a square PNG data URL (for the menubar
// tile thumbnail, which NSImage renders from PNG). Async via Image.onload;
// calls cb(null) on any failure so the caller falls back to the SF Symbol glyph.
window._rasterizeToPng = function(src, size, cb) {
    try {
        const img = new Image();
        img.onload = function() {
            try {
                const c = document.createElement("canvas");
                c.width = c.height = size;
                const ctx = c.getContext("2d");
                ctx.imageSmoothingEnabled = false;   // keep pixels crisp
                ctx.drawImage(img, 0, 0, size, size);
                cb(c.toDataURL("image/png"));
            } catch (e) { cb(null); }
        };
        img.onerror = function() { cb(null); };
        img.src = src;
    } catch (e) { cb(null); }
};

window._activeDeviceMac = function() {
    return (document.getElementById("banner-device-mac")?.textContent || "").trim();
};

// R46 #2: mirror the active widget's pushed frame to its device's last-active
// preview (used by the sysmon/music/stocks pollers).
window.markActiveDeviceFrame = function(src) {
    const mac = window._activeDeviceMac();
    if (mac && mac !== "None" && src && window.setDeviceActivity)
        window.setDeviceActivity(mac, "image", { src: src });
};

// R47: device-dots / selector logic (mergeDiscoveredDevices, refreshOwnedDevices,
// renderDeviceDots, setScanning) lives in device_selector.js to keep this file
// under the 500-LOC cap.

window.getDeviceDimensions = function(name) {
    const n = (name || "").toLowerCase();
    if (n.includes("tivoo-max") || n.includes("tivoo max")) return { width: 160, height: 140, size: 16, image: "assets/tivoo_max.png" };
    if (n.includes("timoo")) return { width: 80, height: 80, size: 16, image: "assets/timoo.png" };
    if (n.includes("ditoo")) return { width: 90, height: 90, size: 16, image: "assets/ditoo.png" };
    if (n.includes("timebox") || n.includes("evo")) return { width: 100, height: 100, size: 16, image: "assets/timebox.png" };
    if (n.includes("pixoo") && n.includes("64")) return { width: 260, height: 260, size: 64, image: "assets/pixoo.png" };
    return { width: 200, height: 200, size: 16, image: "assets/pixoo.png" };
};

// ── 3. CONNECTION ACTIONS ──
// Moved to connection_events.js (loaded after this file): connectDevice,
// refreshConnectionState, the live window.Divoom.onDaemonEvent forwarder, and
// startConnectionHeartbeat. Extracted to honour the 500-LOC gate.


// ── R53: daemon-down detection + reconnect ────────────────────────────────
// The background service (daemon) owns the device over the socket and is killed
// on quit (keep-alive off), so it MUST respawn on the next launch. If it's ever
// unreachable, NOTHING works — unlike the device dot, this is app-wide. Unlike
// refreshConnectionState it is NOT gated behind appConnected, so a down daemon
// is caught even with no device connected. Policy: auto-reconnect silently once,
// then surface a persistent banner with a manual Reconnect only if that fails.
window._daemonReconnecting = false;

window.setDaemonBanner = function(show, detail) {
    const banner = document.getElementById("daemon-banner");
    if (!banner) return;
    banner.hidden = !show;
    // R67: show WHY when the daemon told us. The generic line is true but
    // unactionable -- a stale socket, a file in the way and a permission
    // problem all produced the same sentence, and none are fixed the same way.
    const msg = banner.querySelector(".daemon-banner-msg");
    if (!msg) return;
    if (!msg.dataset.defaultText) msg.dataset.defaultText = msg.textContent;
    msg.textContent = (show && detail) ? detail : msg.dataset.defaultText;
};

window.refreshDaemonHealth = async function() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.daemon_health) return;
    let health;
    try { health = JSON.parse(await api.daemon_health()); }
    catch (e) { return; }  // pywebview not ready / transient — try next tick
    if (health && health.daemon) { window.setDaemonBanner(false); return; }
    const detail = health && health.reason
        ? (health.remedy ? health.reason + ". " + health.remedy : health.reason)
        : null;
    // Daemon is down. Attempt one silent auto-reconnect before nagging the user.
    if (!window._daemonReconnecting && api.reconnect_daemon) {
        window._daemonReconnecting = true;
        try {
            const r = JSON.parse(await api.reconnect_daemon());
            if (r && r.daemon) {
                window.setDaemonBanner(false);
                window.showToast("Reconnected to the background service.", "success");
                return;
            }
        } catch (e) { /* fall through to the banner */ }
        finally { window._daemonReconnecting = false; }
    }
    window.setDaemonBanner(true, detail);
};

// Manual reconnect (the banner button). Gives immediate feedback and re-probes.
window.reconnectDaemonManual = async function() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.reconnect_daemon) return;
    const btn = document.getElementById("daemon-reconnect-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Reconnecting..."; }
    let ok = false;
    try { ok = !!(JSON.parse(await api.reconnect_daemon()) || {}).daemon; }
    catch (e) { ok = false; }
    if (btn) { btn.disabled = false; btn.textContent = "Reconnect"; }
    if (ok) {
        window.setDaemonBanner(false);
        window.showToast("Reconnected to the background service.", "success");
    } else {
        window.showToast("Still can't reach the background service.", "error");
    }
};

// R59/event-driven: the GUI's daemon subscription ends (socket closed) when
// the daemon goes down — that replaces the old 4s health poll. Trigger the same
// silent auto-reconnect + banner logic. The follower thread self-heals (it
// resubscribes when the daemon returns), so events resume without a poll.
window.Divoom = window.Divoom || {};
window.Divoom.onDaemonDown = function() {
    if (window.refreshDaemonHealth) window.refreshDaemonHealth();
};

window.startDaemonHeartbeat = function() {
    // No polling: daemon health is event-driven (window.Divoom.onDaemonDown).
    if (window._daemonHeartbeat) return;
    window._daemonHeartbeat = true;  // sentinel so this is idempotent
};

window.updateDeviceSelectorDropdown = function() {
    const sel = document.getElementById("sidebar-device-select");
    if (!sel) return;
    sel.innerHTML = '<option value="">Select Screen...</option>';
    const curr = document.getElementById("banner-device-mac")?.textContent || "";
    
    const addOpt = (val, txt) => {
        const opt = document.createElement("option");
        opt.value = val; opt.textContent = txt;
        if (curr === val) opt.selected = true;
        sel.appendChild(opt);
    };
    
    // R32 §C1: user-facing names are clean — no "BLE:" transport prefix.
    // The transport is already conveyed by the connectivity dots; the name
    // alone (e.g. "Pixoo64") reads better in the selector.
    window.DivoomState.discoveredDevices.forEach(d => addOpt(d.address, d.name));
    window.DivoomState.registeredLanDevices.forEach(d => addOpt(`LAN:${d.ip}`, d.ip));
    if (Object.keys(window.DivoomState.assignedSlots || {}).length > 0) addOpt("MatrixWall", " Virtual Wall");
    // R32 §C3: the dots mirror the (now hidden) select's options.
    if (window.renderDeviceDots) window.renderDeviceDots();
};

// ── 4. FREE-FORM DISPLAY WALL ARRANGER CANVAS ──
const arrangerCanvas = document.getElementById("arranger-canvas");

window.syncArrangerToPython = function() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.update_wall_slots(JSON.stringify(window.DivoomState.assignedSlots));
    }
    if (window.updateSyncTargetList) window.updateSyncTargetList();
    // R32 §C3: wall slots changed → the MatrixWall dot may appear/disappear.
    if (window.renderDeviceDots) window.renderDeviceDots();
};

window.renderArrangerCanvas = function() {
    if (!arrangerCanvas) return;
    arrangerCanvas.innerHTML = "";

    Object.keys(window.DivoomState.assignedSlots).forEach(mac => {
        const slot = window.DivoomState.assignedSlots[mac];
        if (!slot || !slot.name || !mac || mac === "undefined") {
            delete window.DivoomState.assignedSlots[mac];
            return;
        }
        const node = document.createElement("div");
        node.className = "arranger-node";
        const accent = window.deviceColor(mac);
        Object.assign(node.style, {
            left: `${slot.x}px`, top: `${slot.y}px`,
            width: `${slot.width}px`, height: `${slot.height}px`,
            borderColor: accent
        });
        node.style.setProperty("--node-accent", accent);
        node.title = `${slot.name} — ${mac}`;
        
        const previewInner = slot.preview ? `<img src="${slot.preview}" class="arranger-node-preview" alt="">` : "";
        node.innerHTML = `
            <span class="arranger-node-chip" style="background:${accent}"></span>
            <div class="arranger-node-screen">${previewInner}</div>
            <div class="arranger-node-remove" data-mac="${mac}">×</div>
        `;
        
        let isDragging = false, startX, startY, startLeft, startTop;
        
        node.addEventListener("mousedown", (e) => {
            if (e.target.classList.contains("arranger-node-remove")) {
                delete window.DivoomState.assignedSlots[mac];
                window.renderArrangerCanvas();
                window.syncArrangerToPython();
                e.stopPropagation();
                return;
            }
            isDragging = true;
            node.classList.add("dragging");
            startX = e.clientX; startY = e.clientY;
            startLeft = parseInt(node.style.left) || 0;
            startTop = parseInt(node.style.top) || 0;
            e.preventDefault();
        });
        
        document.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            const deltaX = e.clientX - startX, deltaY = e.clientY - startY;
            let newLeft = startLeft + deltaX, newTop = startTop + deltaY;
            const maxLeft = arrangerCanvas.clientWidth - node.clientWidth;
            const maxTop = arrangerCanvas.clientHeight - node.clientHeight;
            newLeft = Math.max(0, Math.min(newLeft, maxLeft));
            newTop = Math.max(0, Math.min(newTop, maxTop));
            
            node.style.left = `${newLeft}px`;
            node.style.top = `${newTop}px`;
            window.DivoomState.assignedSlots[mac].x = newLeft;
            window.DivoomState.assignedSlots[mac].y = newTop;
        });
        
        document.addEventListener("mouseup", () => {
            if (isDragging) {
                isDragging = false;
                node.classList.remove("dragging");
                window.syncArrangerToPython();
            }
        });
        arrangerCanvas.appendChild(node);
    });
};
