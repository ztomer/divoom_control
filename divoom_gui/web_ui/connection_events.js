/* connection_events.js — connection actions + live status (extracted from
 * app_globals.js to keep files under the 500-LOC gate).
 *
 * Loaded AFTER app_globals.js (which owns DivoomState + the shared utilities
 * this module calls). Two update paths feed the connection dot + banner:
 *   1. event-driven  — window.Divoom.onDaemonEvent, pushed by the GUI's daemon
 *      subscription on every connect/disconnect (R58/UI-reliability). Immediate.
 *   2. polling        — refreshConnectionState, the heartbeat that catches a
 *      mid-session DEGRADED drop the connect/disconnect events don't cover.
 * The heartbeat is the safety net; the event is the fast path.
 *
 * #6: every path below funnels through window.setConnectionState — the SOLE
 * writer of the dot class, the banner, and DivoomState.appConnected. Three
 * writers with no funnel is how the UI got stuck on "connecting" while the
 * daemon was connected: the click flow owned the dot, the heartbeat refused
 * to heal upward (early-return unless already connected), and a status event
 * arriving mid-click wrote around both.
 */

// ── THE funnel for connection surface state ─────────────────────────────
// mode: "connecting" | "active" | "degraded" | "inactive".
// A degraded link stays "connected" (the daemon self-heals); "connecting"
// never wipes the banner (a pending click must not erase the last known
// device before its outcome is known).
window.setConnectionState = function(s) {
    s = s || {};
    const mode = s.mode || "inactive";
    const dot = document.getElementById("global-status-dot");
    if (dot) {
        let cls = "transport-dot ";
        if (mode === "connecting") cls += "connecting";
        else if (mode === "degraded") cls += "active degraded";
        else if (mode === "active") cls += "active " + (s.transport || "ble");
        else cls += "inactive";
        dot.className = cls;
        dot.title = mode === "active" ? "Connected"
            : mode === "degraded" ? "Link degraded — reconnecting"
            : mode === "connecting" ? "Connecting..." : "Disconnected";
        dot.removeAttribute("style");
    }
    window.DivoomState.appConnected = (mode === "active" || mode === "degraded");
    if ((mode === "active" || mode === "degraded") && s.mac) {
        let name = s.name || s.mac;
        const found = (window.DivoomState.discoveredDevices || [])
            .find(d => d.address === s.mac);
        if (found && found.name) name = found.name;
        const bannerName = document.getElementById("banner-device-name");
        const bannerMac = document.getElementById("banner-device-mac");
        if (bannerName) bannerName.textContent = name;
        if (bannerMac) bannerMac.textContent = s.mac;
    } else if (mode === "inactive") {
        const bannerName = document.getElementById("banner-device-name");
        const bannerMac = document.getElementById("banner-device-mac");
        if (bannerName) bannerName.textContent = "None";
        if (bannerMac) bannerMac.textContent = "None";
    }
};

// ── 3. CONNECTION ACTIONS ──
// updateSidebarSpeakerIcon was removed — speaker status now lives in
// Settings → Devices tables. Kept as a no-op for backward compatibility.
window.updateSidebarSpeakerIcon = function(_hasSpeaker) {
    return;
};

window.connectDevice = function(name, address) {
    window.showToast(`Connecting to ${name}...`, "success");
    window.setConnectionState({ mode: "connecting" });
    // R35 §2: pulse the sidebar device dot being connected, in the device's
    // own accent color (CSS var --dot-pulse-color, amber fallback for the
    // global dot). Cleared by re-render on success or explicitly on failure.
    const deviceDot = document.querySelector(
        `#device-dots [data-value="${(window.CSS && CSS.escape) ? CSS.escape(address) : address}"]`);
    if (deviceDot) {
        deviceDot.classList.add("connecting");
        // Pulse in the device's accent color (CSS var, fallback amber).
        deviceDot.style.setProperty("--dot-pulse-color", window.deviceColor(address));
    }

    if (window.pywebview && window.pywebview.api) {
        // R57 watchdog: if the daemon never answers the connect (dead/!wedged
        // central that the Rust BleCentral timeout + client read_timeout failed
        // to catch — defense in depth), don't leave the UI stuck on "connecting".
        // The client read_timeout is ~30s; fire the watchdog a beat after.
        let connectWatchdog = null;
        connectWatchdog = setTimeout(() => {
            window.setConnectionState({ mode: "inactive" });
            window.showToast(`Background service not responding for ${name}. Try Reconnect.`, "error");
            if (window.renderDeviceDots) window.renderDeviceDots();
        }, 35000);
        window.pywebview.api.connect_single_device(address).then(res => {
            clearTimeout(connectWatchdog);
            if (res) {
                const type = address === "MatrixWall" ? "wall" : (address.startsWith("LAN:") ? "lan" : "ble");
                const label = type === "wall" ? " Wall" : (type === "lan" ? " LAN" : " BLE");
                window.showToast(`Connected to ${name}!`, "success", label);
                window.setConnectionState({ mode: "active", transport: type, mac: address, name: name });
                window._updateDeviceLabel(name);
                // R32 §C2: prefer the last-pushed preview; fall back to the
                // product icon when this device hasn't been pushed to yet.
                const dims = window.getDeviceDimensions(name);
                window.restoreDevicePreview(address, dims.image);
                if (window.renderDeviceDots) window.renderDeviceDots();
                if (window.loadDeviceName) window.loadDeviceName();
                if (window.restoreActiveWidgetForDevice) window.restoreActiveWidgetForDevice(address);
                // banner-device-res and banner-device-speaker moved to Settings → Devices.
                // Their textContent assignments are intentionally skipped here.
                const isSpk = name.toLowerCase().includes("timoo") || name.toLowerCase().includes("ditoo") || name.toLowerCase().includes("tivoo");
                window.updateSidebarSpeakerIcon(isSpk);
                const sidebarSelect = document.getElementById("sidebar-device-select");
                if (sidebarSelect) sidebarSelect.value = address;
                if (window.updateSyncTargetList) window.updateSyncTargetList();
                if (window.updateChannelButtonsVisibility) window.updateChannelButtonsVisibility(name);
            } else {
                window.setConnectionState({ mode: "inactive" });
                // BLE Hardening P1: show the daemon's actionable reason (asleep /
                // BT off / held by the phone app), not a generic failure.
                if (window.pywebview?.api?.get_last_connect_error) {
                    window.pywebview.api.get_last_connect_error().then(msg => {
                        window.showToast(msg && msg.trim()
                            ? `${name}: ${msg}` : `Failed to connect to ${name}`, "error");
                    });
                } else {
                    window.showToast(`Failed to connect to ${name}`, "error");
                }
                // R34 §2: stop the pulse + restore the per-device hue.
                if (window.renderDeviceDots) window.renderDeviceDots();
                window._updateDeviceLabel(null);
                window.updateSidebarSpeakerIcon(false);
                if (window.updateSyncTargetList) window.updateSyncTargetList();
                if (window.updateChannelButtonsVisibility) window.updateChannelButtonsVisibility("None");
            }
        });
    } else {
        // No bridge (page loaded before pywebview attached): never leave the
        // dot parked on "connecting" with nothing that can clear it.
        window.setConnectionState({ mode: "inactive" });
        window.showToast("Backend not ready — retry in a moment.", "error");
    }
};

// ── BLE Hardening P6: appbar connection heartbeat ─────────────────────────
// The connect/disconnect handlers set the dot at transition time, but a link
// can DROP mid-session (device sleeps, RF blip). Poll the daemon's honest
// connection_state so the dot reflects DEGRADED (amber) and a genuine drop,
// not a stale solid "connected". (The fast path is the event-driven
// window.Divoom.onDaemonEvent below; this heartbeat is the safety net.)
window._activeTransportType = function() {
    const mac = (document.getElementById("banner-device-mac")?.textContent || "").trim();
    if (mac === "MatrixWall") return "wall";
    if (mac.startsWith("LAN:")) return "lan";
    return "ble";
};

window.refreshConnectionState = function() {
    // No latch: an authoritative answer heals in BOTH directions. The old
    // early-return unless appConnected meant a false flag could never become
    // true again no matter what the daemon reported (#6).
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.get_connection_state) return;
    api.get_connection_state().then(raw => {
        let s;
        try { s = JSON.parse(raw); } catch (e) { return; }
        const state = s && s.state;
        if (state === "degraded") {
            // Reports connected but a write/drop just failed — show amber, keep
            // appConnected (the daemon's live-job self-heal may revive it).
            window.setConnectionState({ mode: "degraded" });
        } else if (state === "disconnected" || !s || !s.connected) {
            // Genuinely dropped — or the daemon explicitly reports disconnected
            // while a stale connected:true lingered. Flip the dot + the global
            // flag so the UI stops claiming a live link; a disconnected state
            // must NOT be masked by a stale connected flag.
            window.setConnectionState({ mode: "inactive" });
        } else {
            // Honest connected (ble/lan/wall) — colour the dot by transport type.
            window.setConnectionState({ mode: "active", transport: window._activeTransportType() });
        }
    }).catch(() => {});
};

// R58/UI-reliability: live daemon event forwarder. The GUI subscribes to the
// daemon and calls this with every `status`/`notification` event, so the
// dashboard reflects connect/disconnect IMMEDIATELY (event-driven) instead of
// waiting for the 4s polling heartbeat. The event carries honest state
// (`connected` + `mac`/`lan_ip`) — see daemon `status_payload` / `initial_status`.
window.Divoom = window.Divoom || {};
window.Divoom.onDaemonEvent = function(ev) {
    if (!ev || typeof ev !== "object") return;
    const type = ev.type;
    if (type !== "status") return;  // notifications are surfaced natively by macOS
    const connected = ev.connected === true;
    const degraded = ev.state === "degraded";
    const dropped = ev.state === "disconnected";
    const mac = ev.lan_ip ? ("LAN:" + ev.lan_ip) : (ev.mac || null);
    // A degraded link stays "connected" (the daemon self-heals); a genuine drop
    // or an explicit `disconnected` state flips appConnected so the rest of the
    // UI stops acting connected — an honest state must NOT be masked by a stale
    // connected flag (the P6 honest-state regression). As the authoritative
    // writer, a status event also clears a stale "connecting" dot left by a
    // click flow whose promise never settled (#6).
    // Per-panel first (2026-09-12): the daemon names the panel a status is
    // about, and with a fleet the global dot is the SELECTED panel's link,
    // not whichever panel last spoke. An event naming nobody is fleet-wide.
    const list = window.DivoomState.discoveredDevices || [];
    const known = mac ? list.find(d => d.address === mac) : null;
    const stateWord = (!connected || dropped) ? "disconnected" : (degraded ? "degraded" : "active");
    if (known) {
        known.activityState = stateWord;
        known.daemonOwned = connected && !dropped;
    } else if (!mac) {
        list.forEach(d => { d.activityState = stateWord; if (stateWord === "disconnected") d.daemonOwned = false; });
    }
    const activeMac = (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null;
    // A selection that is not a known panel (a bench placeholder, a stale
    // restore) does not own the dot; the event then speaks for the app.
    const selectionIsReal = !!activeMac && list.some(d => d.address === activeMac);
    const aboutSelected = !mac || !selectionIsReal || mac === activeMac;
    if (aboutSelected) {
        if (!connected || dropped) {
            window.setConnectionState({ mode: "inactive" });
        } else if (degraded) {
            window.setConnectionState({ mode: "degraded", mac: mac });
        } else {
            window.setConnectionState({ mode: "active", transport: mac && mac.startsWith("LAN:") ? "lan" : "ble", mac: mac });
        }
    }
    if (window.renderDeviceDots) window.renderDeviceDots();
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
};

// R59/event-driven: the daemon pushes owned-device changes as `owned_devices`
// events, so the 4s get_device_activity poll is gone. Merge the event's device
// list into discoveredDevices (mirrors the old refreshOwnedDevices merge): drop
// all daemonOwned flags, then re-mark the ones the daemon reports as owned.
window.Divoom = window.Divoom || {};
window.Divoom.onOwnedDevices = function(ev) {
    if (!ev || !Array.isArray(ev.devices)) return;
    const list = window.DivoomState.discoveredDevices || [];
    list.forEach(d => { d.daemonOwned = false; });
    ev.devices.forEach(dev => {
        const address = dev.address;
        if (!address) return;
        let known = list.find(d => d.address === address);
        if (!known) {
            known = { address: address, name: dev.name || "Screen", daemonOwned: true };
            list.push(known);
        } else {
            known.daemonOwned = true;
            if (dev.name && known.name !== dev.name) known.name = dev.name;
        }
        known.activityKind = dev.kind || "idle";
        known.activityState = dev.state || "active";
    });
    if (window.renderDeviceDots) window.renderDeviceDots();
    // The bench and deck jewels read daemonOwned too (2026-09-12).
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
};

// R59/event-driven: macOS notification-monitor status. The daemon broadcasts
// `notif_status` (same shape as get_notification_listener_status) so the 5s
// poll is gone. renderMacNotifStatus lives in settings_notifications.js.
window.Divoom.onNotifStatus = function(ev) {
    if (window.renderMacNotifStatus) window.renderMacNotifStatus(ev);
};

// R59/event-driven: hot-channel update progress. The daemon broadcasts
// `hot_progress` (phases: starting/done/error) so the 600ms poll is gone.
window.Divoom.onHotProgress = function(ev) {
    if (!ev || !ev.phase) return;
    if (window.applyProgress) window.applyProgress(ev);
    if (ev.phase === "done" || ev.phase === "error") {
        if (window.finishProgress) window.finishProgress(ev);
        if (window._pollTimer) { clearInterval(window._pollTimer); window._pollTimer = null; }
    }
};

// Activity event: daemon or menubar switched channel or started a job
window.Divoom.onActivity = function(ev) {
    if (!ev || !ev.mac || !ev.kind) return;
    const mac = ev.mac;
    const kind = ev.kind;
    const opts = ev.opts || {};
    if (typeof window.saveDeviceChannel === "function") {
        window.saveDeviceChannel(mac, kind, opts);
    }
    if (window.DisplayPreviewRegistry) {
        window.DisplayPreviewRegistry.get(mac).setActivity(kind, opts);
    }
    window.DivoomState.deviceActivity = window.DivoomState.deviceActivity || {};
    window.DivoomState.deviceActivity[mac] = { kind: kind, at: Date.now(), opts: opts };
    if (mac === (typeof window._activeDeviceMac === "function" ? window._activeDeviceMac() : null)) {
        window.DivoomState.activeChannel = kind;
        const card = document.querySelector(`.tab-btn[data-channel="${kind}"]`);
        if (card) {
            document.querySelectorAll(".tab-btn[data-channel]").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
        }
        if (typeof window.showChannelPanel === "function") {
            window.showChannelPanel(kind);
        }
        if (typeof window.syncChannelControlsToDisplay === "function") {
            window.syncChannelControlsToDisplay(mac);
        }
    }
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
};

window.startConnectionHeartbeat = function() {
    // No polling: connection state, owned devices, and daemon health are all
    // event-driven now (window.Divoom.onDaemonEvent / onOwnedDevices /
    // onDaemonDown). The GUI's daemon subscription pushes updates immediately.
    if (window._connHeartbeat) return;
    window._connHeartbeat = true;  // sentinel so this is idempotent
};
