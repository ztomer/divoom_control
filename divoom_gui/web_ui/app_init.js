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
        ".integrated-appbar .appbar-slider, .integrated-appbar .win-btn"
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

    // ── 5. CANVAS ARRANGER AND PRESETS BINDINGS ──
    const addArrangerBtn = document.getElementById("add-arranger-screen-btn");
    if (addArrangerBtn) {
        addArrangerBtn.addEventListener("click", () => {
            document.querySelectorAll(".arranger-popup").forEach(p => p.remove());
            
            const bleOptions = (window.DivoomState.discoveredDevices || []).map(d => `<option value="${d.address}"> BLE: ${d.name}</option>`);
            const lanOptions = (window.DivoomState.registeredLanDevices || []).map(d => `<option value="LAN:${d.ip}"> LAN: ${d.ip}</option>`);
            const combinedOptions = bleOptions.concat(lanOptions).join("");

            if (!combinedOptions) {
                window.showToast("No devices found. Scan BLE screens or configure a LAN screen first!", "error");
                return;
            }
            
            const popup = document.createElement("div");
            popup.className = "arranger-popup";
            popup.innerHTML = `
                <h3 style="font-family: var(--font-display); font-size:16px; margin-bottom:15px; color: var(--text-main);">Add Screen to Arranger</h3>
                <select id="canvas-add-select" class="custom-select" style="width:100%; margin-bottom:15px;">${combinedOptions}</select>
                <div style="display:flex; gap:10px; justify-content:flex-end;">
                    <button id="canvas-add-cancel" class="glow-btn compact" style="background:rgba(130,131,138,0.1); border: 1px solid var(--border-color); color: var(--text-main); box-shadow:none;">Cancel</button>
                    <button id="canvas-add-confirm" class="glow-btn compact" style="background: var(--primary); border: 1px solid var(--primary); color:#fff; box-shadow:none;">Add Node</button>
                </div>
            `;
            
            document.body.appendChild(popup);
            document.getElementById("canvas-add-cancel").addEventListener("click", () => popup.remove());
            document.getElementById("canvas-add-confirm").addEventListener("click", () => {
                const selectEl = document.getElementById("canvas-add-select");
                const addr = selectEl ? selectEl.value : "";
                popup.remove();
                if (!addr) return;
                if (window.DivoomState.assignedSlots[addr]) {
                    window.showToast("Device already placed on canvas!", "error");
                    return;
                }
                const isLan = addr.startsWith("LAN:");
                let devName = "Divoom Screen";
                if (isLan) {
                    devName = `Wi-Fi Screen: ${addr.split("LAN:")[1]}`;
                } else {
                    const dev = window.DivoomState.discoveredDevices.find(d => d.address === addr);
                    devName = dev ? dev.name : "Divoom Screen";
                }
                const dims = window.getDeviceDimensions(devName);
                const placementX = Math.round((arrangerCanvas.clientWidth - dims.width) / 2);
                const placementY = Math.round((arrangerCanvas.clientHeight - dims.height) / 2);
                
                window.DivoomState.assignedSlots[addr] = {
                    x: placementX, y: placementY, width: dims.width, height: dims.height,
                    size: dims.size, name: devName, image: dims.image
                };
                window.renderArrangerCanvas();
                window.syncArrangerToPython();
            });
        });
    }

    const clearArrangerBtn = document.getElementById("clear-arranger-btn");
    if (clearArrangerBtn) {
        clearArrangerBtn.addEventListener("click", () => {
            window.DivoomState.assignedSlots = {};
            window.renderArrangerCanvas();
            window.syncArrangerToPython();
        });
    }

    const presetsSelect = document.getElementById("presets-select");
    if (presetsSelect) {
        presetsSelect.addEventListener("change", (e) => {
            const name = e.target.value;
            if (!name) return;
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.load_preset_by_name(name).then(slotsJson => {
                    if (slotsJson) {
                        window.DivoomState.assignedSlots = JSON.parse(slotsJson);
                        window.renderArrangerCanvas();
                        window.syncArrangerToPython();
                        window.showToast(`Layout preset '${name}' applied!`, "success");
                    }
                });
            }
        });
    }



    const savePresetBtn = document.getElementById("save-preset-btn");
    if (savePresetBtn) {
        savePresetBtn.addEventListener("click", () => {
            if (Object.keys(window.DivoomState.assignedSlots).length === 0) {
                window.showToast("Add at least one screen before saving", "error");
                return;
            }
            // R42 §5: pywebview's cocoa backend does NOT implement
            // window.prompt — the old fallback returned null and the save
            // silently no-opped (the user believed the preset was saved).
            // Require the toolbar name field and say so.
            const nameInput = document.getElementById("preset-name-input");
            const name = (nameInput?.value || "").trim();
            if (!name) {
                window.showToast("Type a preset name first (toolbar field)", "error");
                nameInput?.focus();
                return;
            }
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.save_preset(name, JSON.stringify(window.DivoomState.assignedSlots)).then(res => {
                    if (res) {
                        window.showToast(`Saved layout '${name}'`, "success");
                        window.pywebview.api.load_preset_names().then(namesJson => {
                            if (namesJson && presetsSelect) {
                                const names = JSON.parse(namesJson);
                                presetsSelect.innerHTML = '<option value="">Load Preset...</option>';
                                names.forEach(n => {
                                    const opt = document.createElement("option");
                                    opt.value = n; opt.textContent = n;
                                    presetsSelect.appendChild(opt);
                                });
                            }
                        });
                    }
                });
            }
        });
    }

    // ── 6. NATIVE FILE BROWSERS (wall art only; custom art uses page/slot grid) ──
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
            if (!path) return;
            if (Object.keys(window.DivoomState.assignedSlots).length === 0) return;
            window.showToast("Splitting image and syncing wall...", "success");
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.display_wall_image(path, 16).then(res => {
                    const success = typeof res === "object" ? res.success : !!res;
                    if (success) {
                        window.showToast("Synchronized display wall", "success", " BLE");
                        // R45 #3: show each screen's DOWNSCALED crop (exactly what
                        // the device renders) in the arranger preview — the daemon
                        // already returns them as {mac: dataURI}; we just dropped them.
                        const previews = (res && typeof res === "object" && res.previews) || {};
                        let any = false;
                        Object.keys(previews).forEach(mac => {
                            const slot = window.DivoomState.assignedSlots[mac];
                            if (slot) { slot.preview = previews[mac]; any = true; }
                        });
                        if (any && window.renderArrangerCanvas) window.renderArrangerCanvas();
                    }
                });
            }
        });
    }

    // ── 7. BRIGHTNESS SLIDERS AND TARGET CHANGE HANDLERS ──
    const globalBrightnessSlider = document.getElementById("global-brightness-slider");
    const globalBrightnessValue = document.getElementById("global-brightness-value");
    
    // R11 4e: thumb tracks brightness — white at 100%, darkening toward black.
    function updateBrightnessThumb(v) {
        const g = Math.round(255 * (parseInt(v) || 0) / 100);
        globalBrightnessSlider.style.setProperty("--thumb-color", `rgb(${g},${g},${g})`);
    }
    if (globalBrightnessSlider) {
        updateBrightnessThumb(globalBrightnessSlider.value);
        globalBrightnessSlider.addEventListener("input", (e) => {
            const val = e.target.value;
            if (globalBrightnessValue) globalBrightnessValue.textContent = val + "%";
            updateBrightnessThumb(val);
        });
        globalBrightnessSlider.addEventListener("change", (e) => {
            const val = parseInt(e.target.value);
            if (!window.DivoomState.appConnected) return;
            if (window.pywebview && window.pywebview.api && window.pywebview.api.set_brightness) {
                window.pywebview.api.set_brightness(val).then(res => {
                    if (res) window.showToast(`Brightness set to ${val}%`, "success", " BLE");
                });
            }
        });
    }

    // Volume slider (Round 6 — new functionality exposure).
    // Protocol range is 0-15 (divoom.music.set_volume). Kare: show the
    // raw value as "N/15" so the user knows the device's actual range.
    // Send on `change` (not `input`) to avoid spamming 0x08 writes.
    const appbarVolumeSlider = document.getElementById("appbar-volume-slider");
    const appbarVolumeValue = document.getElementById("appbar-volume-value");
    if (appbarVolumeSlider) {
        appbarVolumeSlider.addEventListener("input", (e) => {
            const val = e.target.value;
            if (appbarVolumeValue) appbarVolumeValue.textContent = `${val}/15`;
        });
        appbarVolumeSlider.addEventListener("change", (e) => {
            const val = parseInt(e.target.value);
            if (!window.DivoomState.appConnected) return;
            if (window.pywebview && window.pywebview.api && window.pywebview.api.set_volume) {
                window.pywebview.api.set_volume(val).then(res => {
                    if (res) window.showToast(`Volume set to ${val}/15`, "success", " BLE");
                });
            }
        });
    }

    // On startup, read the current volume and update the slider to match.
    // This gives the user a "what's my device doing right now" glance.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_volume) {
        window.pywebview.api.get_volume().then(val => {
            if (val !== null && val !== undefined && appbarVolumeSlider) {
                appbarVolumeSlider.value = val;
                if (appbarVolumeValue) appbarVolumeValue.textContent = `${val}/15`;
            }
        });
    }

    // On startup, read the current brightness and update the slider to
    // match (Round 7 — matches the volume slider pattern from Round 6).
    // Kare: pixel-perfect parity between GUI and device state.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_brightness) {
        window.pywebview.api.get_brightness().then(val => {
            if (val !== null && val !== undefined && globalBrightnessSlider) {
                globalBrightnessSlider.value = val;
                if (globalBrightnessValue) globalBrightnessValue.textContent = val + "%";
            }
        });
    }

    // On startup, read the current work mode and highlight the active
    // channel card in the Control Panel (Round 7).
    // 0=clock, 1=lightning, 2=cloud, 3=vj, 4=visualizer, 5=design,
    // 6=scoreboard. Ambient has no mode int (it's a tool, not a channel).
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_work_mode) {
        window.pywebview.api.get_work_mode().then(mode => {
            if (mode === null || mode === undefined) return;
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
                    
                    const statusBox = getEl("divoom-cloud-status-box");
                    if (statusBox) {
                        const isConn = !!conf.cloud_connected;
                        statusBox.style.display = "flex";
                        statusBox.style.background = isConn ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)";
                        statusBox.style.border = isConn ? "1px solid rgba(34, 197, 94, 0.3)" : "1px solid rgba(239, 68, 68, 0.3)";
                        statusBox.style.color = isConn ? "#22c55e" : "#ef4444";
                        statusBox.innerHTML = `<span>${isConn ? ' Connected as <b>' + (conf.cloud_email || conf.email) + '</b>' : ' Not connected. Save credentials to log in.'}</span>`;
                    }
                }
            });
            
            window.pywebview.api.load_preset_names().then(namesJson => {
                if (namesJson && presetsSelect) {
                    const names = JSON.parse(namesJson);
                    presetsSelect.innerHTML = '<option value="">Load Preset...</option>';
                    names.forEach(n => {
                        const opt = document.createElement("option");
                        opt.value = n; opt.textContent = n;
                        presetsSelect.appendChild(opt);
                    });
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
        
        // Close modals on tab change
        window.addEventListener("tab-changed", () => {
            document.querySelectorAll(".arranger-popup").forEach(p => p.remove());
        });
    }, 1000);
});

