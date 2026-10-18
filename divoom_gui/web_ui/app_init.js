/* app_init.js — DOMContentLoaded initialisation (all event wiring + session restore) */
document.addEventListener("DOMContentLoaded", () => {

    // BLE Hardening P6: poll the daemon's honest connection_state so the appbar
    // dot reflects a mid-session drop / DEGRADED link, not a stale "connected".
    if (window.startConnectionHeartbeat) window.startConnectionHeartbeat();

    // R53: check the background service (daemon) is up on open and every 4s. It's
    // killed on quit, so a restart must respawn it; if that failed the app is
    // unusable with no indication. The heartbeat auto-reconnects, then surfaces a
    // Reconnect banner. Wire the banner button to a manual reconnect.
    if (window.startDaemonHeartbeat) window.startDaemonHeartbeat();
    const daemonReconnectBtn = document.getElementById("daemon-reconnect-btn");
    if (daemonReconnectBtn)
        daemonReconnectBtn.addEventListener("click", () => window.reconnectDaemonManual());

    // ── 0. FRAMELESS WINDOW DRAG (appbar) ──
    // The window drag is handled by pywebview's built-in drag-region
    // mechanism: <header class="integrated-appbar pywebview-drag-region">
    // matches the DRAG_REGION_SELECTOR, and customize.js
    // (webview/js/customize.js:69-89) walks the DOM looking for that
    // selector and dispatches `pywebviewMoveWindow` to the cocoa
    // backend (BrowserView.move).
    //
    // macOS multi-monitor coordinate double-count: the bundled
    // BrowserView.move adds `self.screen.origin.x` to the X coord
    // the JS sends, which jumps the window off-screen when the
    // window is on a secondary monitor with non-zero origin
    // (upstream issue #1820, May 2026). We apply the
    // upstream-recommended monkey-patch in gui_main.py before
    // `webview.create_window` that drops the `self.screen.origin.x`
    // term from BrowserView.move. The patch is a no-op on
    // single-monitor setups.
    //
    // R11 4d: pywebview's drag handler (customize.js) starts a window move on
    // ANY mousedown whose ancestor is the .pywebview-drag-region (the appbar) —
    // it has no no-drag exclusion, so dragging an appbar slider moved the whole
    // window. Stop the mousedown from bubbling to body for the interactive
    // appbar controls so they work as controls, not drag handles.
    document.querySelectorAll(
        ".integrated-appbar .appbar-slider, .integrated-appbar .win-btn, .appbar-stage-controls, .appbar-stage-actions"
    ).forEach((el) => el.addEventListener("mousedown", (e) => e.stopPropagation()));

    // Inject HTML Templates
    if (document.getElementById('pixel-art') && window.DivoomTemplates?.pixelArt) {
        document.getElementById('pixel-art').innerHTML = window.DivoomTemplates.pixelArt;
    }
    if (document.getElementById('data-sources') && window.DivoomTemplates?.widgets) {
        document.getElementById('data-sources').innerHTML = window.DivoomTemplates.widgets;
    }
    if (document.getElementById('settings') && window.DivoomTemplates?.settings) {
        document.getElementById('settings').innerHTML = window.DivoomTemplates.settings;
    }
    /* R33: Routines replaces Tools in sidebar */
    if (document.getElementById('routines') && window.DivoomTemplates?.routines) {
        document.getElementById('routines').innerHTML = window.DivoomTemplates.routines;
    }
    /* R40 §8: Device Settings section */
    if (document.getElementById('device-settings') && window.DivoomTemplates?.deviceSettings) {
        document.getElementById('device-settings').innerHTML = window.DivoomTemplates.deviceSettings;
    }

    // ── 5. VIRTUAL DISPLAY WALL (SPLIT & SYNC) ──
    const browseWallArtBtn = document.getElementById("browse-wall-art-btn");
    const filePathInput = document.getElementById("file-path-input");
    const filePreviewContainer = document.getElementById("file-preview-container");
    const filePreviewImg = document.getElementById("file-preview-img");

    if (browseWallArtBtn) {
        browseWallArtBtn.addEventListener("click", () => {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.open_file_dialog) {
                window.pywebview.api.open_file_dialog().then(path => {
                    if (path) {
                        if (filePathInput) filePathInput.value = path;
                        if (filePreviewImg) filePreviewImg.src = "file://" + path;
                        if (filePreviewContainer) filePreviewContainer.style.display = "flex";
                    }
                });
            }
        });
    }

    const applyWallArtBtn = document.getElementById("apply-wall-art");
    if (applyWallArtBtn) {
        applyWallArtBtn.addEventListener("click", () => {
            const path = filePathInput?.value.trim();
            if (!path) {
                window.showToast("Please select an image file first", "error");
                return;
            }
            const allSlots = window.SpatialRooms ? window.SpatialRooms.getWallSlots() : (window.DivoomState.assignedSlots || {});
            const wallMacs = Object.keys(allSlots).filter(mac => (allSlots[mac].room || '').toLowerCase() === 'wall');
            const activeSlots = (wallMacs.length > 0)
                ? Object.fromEntries(wallMacs.map(mac => [mac, allSlots[mac]]))
                : allSlots;
            const slotCount = Object.keys(activeSlots).length;
            // Panels the daemon will not make slots (P6.1), in the same scope
            // as the wall: its room when one is named, else every panel. Said
            // in the one toast this click raises, so the next cannot hide it.
            const refused = (window.SpatialRooms ? window.SpatialRooms.getWallRefusals() : [])
                .filter(r => wallMacs.length === 0 || r.room.toLowerCase() === 'wall');
            const leftOut = refused.map(r => `${r.name} is left out. ${r.reason}`).join(' ');
            if (slotCount === 0) {
                window.showToast(leftOut || "No screens configured on the Spatial Bench!", "error");
                return;
            }
            window.DivoomState.assignedSlots = activeSlots;
            window.showToast(leftOut ? `Splitting image and syncing wall. ${leftOut}`
                                     : "Splitting image and syncing wall...", "success");
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.update_wall_slots(JSON.stringify(activeSlots));
                window.pywebview.api.display_wall_image("MatrixWall", path, 16).then(res => {
                    const success = typeof res === "object" ? res.success : !!res;
                    if (success) {
                        window.showToast("Synchronized display wall", "success", " BLE");
                        const previews = (res && typeof res === "object" && res.previews) || {};
                        Object.keys(previews).forEach(mac => {
                            if (window.setDevicePreview) window.setDevicePreview(mac, previews[mac]);
                            if (window.setDeviceActivity) window.setDeviceActivity(mac, "image", { src: previews[mac] });
                        });
                        if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
                    } else {
                        const named = wallFailureText(res, activeSlots);
                        const errMsg = named || (res && res.error) || "Failed to split and sync wall image";
                        window.showToast(errMsg, "error");
                    }
                });
            }
        });
    }

    // ── 7. Brightness and volume are per panel: panel_facts.js reads them from
    // the daemon for the panel shown and is their one sender (P5.1). ──

    // On startup, read the current work mode and highlight the active
    // channel card in the Control Panel (Round 7).
    // 0=clock, 1=lightning, 2=cloud, 3=vj, 4=visualizer, 5=design,
    // 6=scoreboard. Ambient has no mode int (it's a tool, not a channel).
    // The panel asked is the one shown at startup, and the cards follow its
    // answer only while it is still the one shown (P5.7).
    const modeMac = window.ChannelSettings?.selected()?.mac;
    if (modeMac && modeMac !== "MatrixWall" && window.pywebview?.api?.get_work_mode) {
        window.pywebview.api.get_work_mode(modeMac).then(mode => {
            if (mode === null || mode === undefined) return;
            if (window.ChannelSettings.selected()?.mac !== modeMac) return;
            const modeToChannel = {0: "clock", 3: "vj", 4: "visualizer", 5: "design", 6: "scoreboard"};
            const channel = modeToChannel[mode];
            if (!channel) return;
            // Deactivate all cards, then activate the matching one.
            // (R15 §1+§7: `.channel-card` → `.tab-btn`.)
            document.querySelectorAll(".tab-btn[data-channel]").forEach(c => c.classList.remove("active"));
            const card = document.querySelector(`.tab-btn[data-channel="${channel}"]`);
            if (card) card.classList.add("active");
        });
    }

    const sidebarDeviceSelect = document.getElementById("sidebar-device-select");
    if (sidebarDeviceSelect) {
        sidebarDeviceSelect.addEventListener("change", (e) => {
            const addr = e.target.value;
            if (!addr) return;
            if (addr === "MatrixWall") {
                window.connectDevice("Virtual Wall", "MatrixWall");
            } else if (addr.startsWith("LAN:")) {
                const ip = addr.split("LAN:")[1];
                window.connectDevice(`Wi-Fi Screen: ${ip}`, addr);
            } else {
                const dev = window.DivoomState.discoveredDevices.find(d => d.address === addr);
                const name = dev ? dev.name : "Bluetooth Device";
                window.connectDevice(name, addr);
            }
        });
    }

    // ── 8. INITIAL SESSION RESTORE ON MOUNT ──
    setTimeout(() => {
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.load_config().then(configJson => {
                if (configJson) {
                    const conf = JSON.parse(configJson);
                    const getEl = id => document.getElementById(id);
                    if (conf.email && getEl("settings-email")) getEl("settings-email").value = conf.email;
                    if (conf.timeout != null && getEl("scan-timeout")) {
                        const el = getEl("scan-timeout");
                        let t = parseFloat(conf.timeout);
                        if (el.max) t = Math.min(t, parseFloat(el.max));
                        el.value = t;
                    }
                    if (conf.limit != null && getEl("scan-limit")) getEl("scan-limit").value = conf.limit;
                    
                    if (conf.slots) { window.DivoomState.assignedSlots = conf.slots; window.renderArrangerCanvas(); }
                    if (conf.devices && conf.devices.length > 0) {
                        // R61 follow-up (user-reported): these are PERSISTED devices
                        // from a prior session, not devices confirmed present right
                        // now. Tag them unconfirmed so renderDeviceDots() shows the
                        // existing "not in range" treatment until a real scan or the
                        // daemon's owned-device activity confirms them — without
                        // this, mergeDiscoveredDevices' union-only scan merge (R46 #5)
                        // can add/update but never downgrade an address, so every
                        // device ever seen looked permanently in-range after every
                        // restart, even when genuinely unreachable.
                        window.DivoomState.discoveredDevices =
                            conf.devices.map(d => Object.assign({}, d, { unconfirmed: true }));
                        if (window.populateDeviceSelectors) window.populateDeviceSelectors(conf.devices);
                        window.renderArrangerCanvas();
                    }
                    
                    if (conf.last_connected_device) {
                        const addr = conf.last_connected_device;
                        let name = "Divoom Screen";
                        if (addr === "MatrixWall") name = "Virtual Wall";
                        else if (addr.startsWith("LAN:")) name = `Wi-Fi: ${addr.split("LAN:")[1]}`;
                        else {
                            const dev = window.DivoomState.discoveredDevices.find(d => d.address === addr);
                            if (dev) name = dev.name;
                        }
                        setTimeout(() => window.connectDevice(name, addr), 500);
                    }

                    if (window.refreshKnownDevices) window.refreshKnownDevices();

                    if (window.runBleScan) {
                        setTimeout(() => {
                            window.showToast("Startup: Auto-scanning screens...", "success");
                            window.runBleScan();
                        }, 1000);
                    }
                    
                    window.renderCloudStatus(conf.cloud_connected ? "connected" : "signed_out", conf);
                }
            });
        }
        
        // Realtime Custom Art Preview Helper
        window.showCustomArtPreview = function(path) {
            if (!path) {
                if (customArtPreviewContainer) customArtPreviewContainer.style.display = "none";
                return;
            }
            if (customArtPreviewImg) {
                const src = (path.startsWith("data:") || path.startsWith("file://") || path.startsWith("http"))
                    ? path
                    : "file://" + path;
                customArtPreviewImg.src = src;
            }
            if (customArtPreviewContainer) {
                customArtPreviewContainer.style.display = "flex";
            }
        };
    }, 1000);
});


// P6.3: the daemon names each wall panel whose write failed (`failed`, mac ->
// reason) and each slot with no panel (`degraded`). Say which, by the name the
// bench shows, or "" when the reply names none.
function wallFailureText(res, slots) {
    const named = (mac) => {
        const key = Object.keys(slots || {}).find(k => k.toLowerCase() === String(mac).toLowerCase());
        return (key && slots[key].name) || mac;
    };
    const failed = (res && typeof res === "object" && res.failed) || {};
    const unlinked = (res && typeof res === "object" && res.degraded) || [];
    const parts = Object.keys(failed).map(mac => `${named(mac)} did not take the image (${failed[mac]}).`)
        .concat(unlinked.map(mac => `${named(mac)} is not connected.`));
    return parts.join(" ");
}
