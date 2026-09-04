/* connection_events.js — connection actions + live status (extracted from
 * app_globals.js to keep files under the 500-LOC gate).
 *
 * Loaded AFTER app_globals.js (which owns DivoomState + the shared utilities
 * this module calls). Two update paths feed the connection dot + banner:
 *   1. event-driven  — window.Divoom.onDaemonEvent, pushed by the GUI's daemon
 *      subscription on every connect/disconnect (R58/UI-reliability). Immediate.
 *   2. polling        — refreshConnectionState, the 4s heartbeat that catches a
 *      mid-session DEGRADED drop the connect/disconnect events don't cover.
 * The heartbeat is the safety net; the event is the fast path.
 */

// ── 3. CONNECTION ACTIONS ──
// updateSidebarSpeakerIcon was removed — speaker status now lives in
// Settings → Devices tables. Kept as a no-op for backward compatibility.
window.updateSidebarSpeakerIcon = function(_hasSpeaker) {
    return;
};

window.connectDevice = function(name, address) {
    window.showToast(`Connecting to ${name}...`, "success");
    const statusDot = document.getElementById("global-status-dot");
    if (statusDot) { statusDot.className = "transport-dot connecting"; statusDot.removeAttribute("style"); }
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
            window.DivoomState.appConnected = false;
            window.showToast(`Background service not responding for ${name}. Try Reconnect.`, "error");
            if (statusDot) { statusDot.className = "transport-dot inactive"; statusDot.removeAttribute("style"); }
            if (window.renderDeviceDots) window.renderDeviceDots();
            document.getElementById("banner-device-name").textContent = "None";
            document.getElementById("banner-device-mac").textContent = "None";
        }, 35000);
        window.pywebview.api.connect_single_device(address).then(res => {
            clearTimeout(connectWatchdog);
            if (res) {
                window.DivoomState.appConnected = true;
                const type = address === "MatrixWall" ? "wall" : (address.startsWith("LAN:") ? "lan" : "ble");
                const label = type === "wall" ? " Wall" : (type === "lan" ? " LAN" : " BLE");
                window.showToast(`Connected to ${name}!`, "success", label);
                if (statusDot) { statusDot.className = `transport-dot active ${type}`; statusDot.removeAttribute("style"); }

                document.getElementById("banner-device-name").textContent = name;
                document.getElementById("banner-device-mac").textContent = address;
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
                window.DivoomState.appConnected = false;
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
                if (statusDot) { statusDot.className = "transport-dot inactive"; statusDot.removeAttribute("style"); }
                // R34 §2: stop the pulse + restore the per-device hue.
                if (window.renderDeviceDots) window.renderDeviceDots();
                document.getElementById("banner-device-name").textContent = "None";
                document.getElementById("banner-device-mac").textContent = "None";
                window._updateDeviceLabel(null);
                window.updateSidebarSpeakerIcon(false);
                if (window.updateSyncTargetList) window.updateSyncTargetList();
                if (window.updateChannelButtonsVisibility) window.updateChannelButtonsVisibility("None");
            }
        });
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
    if (!window.DivoomState.appConnected) return;
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.get_connection_state) return;
    api.get_connection_state().then(raw => {
        let s;
        try { s = JSON.parse(raw); } catch (e) { return; }
        const dot = document.getElementById("global-status-dot");
        if (!dot) return;
        const state = s && s.state;
        if (state === "degraded") {
            // Reports connected but a write/drop just failed — show amber, keep
            // appConnected (the daemon's live-job self-heal may revive it).
            dot.className = "transport-dot active degraded";
            dot.title = "Link degraded — reconnecting";
        } else if (state === "disconnected" || !s || !s.connected) {
            // Genuinely dropped — or the daemon explicitly reports disconnected
            // while a stale connected:true lingered. Flip the dot + the global
            // flag so the UI stops claiming a live link; a disconnected state
            // must NOT be masked by a stale connected flag.
            window.DivoomState.appConnected = false;
            dot.className = "transport-dot inactive";
            dot.title = "Disconnected";
        } else {
            // Honest connected (ble/lan/wall) — colour the dot by transport type.
            const type = window._activeTransportType();
            dot.className = `transport-dot active ${type}`;
            dot.title = "";
        }
        dot.removeAttribute("style");
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
    const dot = document.getElementById("global-status-dot");
    const connected = ev.connected === true;
    const degraded = ev.state === "degraded";
    const dropped = ev.state === "disconnected";
    if (dot) {
        if (!connected || dropped) {
            dot.className = "transport-dot inactive";
            dot.title = "Disconnected";
        } else if (degraded) {
            // Link unhealthy (a write/drop just failed) — amber, still owned.
            dot.className = "transport-dot active degraded";
            dot.title = "Link degraded — reconnecting";
        } else {
            const isLan = !!ev.lan_ip;
            dot.className = `transport-dot active ${isLan ? "lan" : "ble"}`;
            dot.title = "Connected";
        }
        dot.removeAttribute("style");
    }
    // A degraded link stays "connected" (the daemon self-heals); a genuine drop
    // or an explicit `disconnected` state flips appConnected so the rest of the
    // UI stops acting connected — an honest state must NOT be masked by a stale
    // connected flag (the P6 honest-state regression).
    window.DivoomState.appConnected = connected && !dropped;
    const mac = ev.lan_ip ? ("LAN:" + ev.lan_ip) : (ev.mac || null);
    const bannerName = document.getElementById("banner-device-name");
    const bannerMac = document.getElementById("banner-device-mac");
    if (connected && mac) {
        // Resolve a friendly name from the last scan when known.
        let name = mac;
        const found = (window.DivoomState.discoveredDevices || [])
            .find(d => d.address === mac);
        if (found && found.name) name = found.name;
        if (bannerName) bannerName.textContent = name;
        if (bannerMac) bannerMac.textContent = mac;
    } else {
        if (bannerName) bannerName.textContent = "None";
        if (bannerMac) bannerMac.textContent = "None";
    }
    if (window.renderDeviceDots) window.renderDeviceDots();
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

window.startConnectionHeartbeat = function() {
    // No polling: connection state, owned devices, and daemon health are all
    // event-driven now (window.Divoom.onDaemonEvent / onOwnedDevices /
    // onDaemonDown). The GUI's daemon subscription pushes updates immediately.
    if (window._connHeartbeat) return;
    window._connHeartbeat = true;  // sentinel so this is idempotent
};
