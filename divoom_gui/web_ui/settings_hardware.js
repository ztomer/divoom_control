/* settings_hardware.js — Theme, scanner, LAN, transport, cloud */
/* settings.js — Bluetooth scanning, Wi-Fi screen lists, theme modes, and cloud credentials */

document.addEventListener("DOMContentLoaded", () => {
    // ── 1. MAIN TAB SWITCH NAVIGATION ──
    const navButtons = document.querySelectorAll(".nav-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    // R32: Settings is now an appbar gear pill, not a sidebar nav button.
    const settingsGear = document.getElementById("appbar-settings-btn");

    function activateTab(targetTab, sourceBtn) {
        navButtons.forEach(b => b.classList.remove("active"));
        tabContents.forEach(t => t.classList.remove("active"));
        if (settingsGear) settingsGear.classList.remove("active");

        if (sourceBtn) sourceBtn.classList.add("active");
        const el = document.getElementById(targetTab);
        if (el) el.classList.add("active");

        // Dispatch custom event to notify other scripts (e.g. widgets or gallery)
        window.dispatchEvent(new CustomEvent("tab-changed", { detail: { tab: targetTab } }));
    }

    navButtons.forEach(btn => {
        btn.addEventListener("click", () => activateTab(btn.getAttribute("data-tab"), btn));
    });

    if (settingsGear) {
        settingsGear.addEventListener("click", () => activateTab("settings", settingsGear));
    }

    // R15 §6: honor ?tab=&card= (the menubar "Open Notifications..." item opens
    // the GUI focused on a tab/card). Best-effort; unknown values are ignored.
    try {
        const params = new URLSearchParams(window.location.search);
        const wantTab = params.get("tab");
        if (wantTab) {
            // R32: match any element carrying data-tab (the Settings gear lives
            // in the appbar now, not the sidebar) so ?tab=settings still works.
            const navBtn = document.querySelector(`[data-tab="${wantTab}"]`);
            if (navBtn) navBtn.click();
        }
        const wantCard = params.get("card");
        if (wantCard) {
            // Templates are injected async; give them a tick to mount.
            setTimeout(() => {
                const card = document.getElementById(`widget-card-${wantCard}`)
                    || document.getElementById(`${wantCard}-card`)
                    || document.getElementById(wantCard);
                if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 400);
        }
    } catch (e) { /* no-op */ }

    // Sub-settings tabs navigation click handler (R15 §1+§7: `.settings-tab-btn` → `.tab-btn`)
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn[data-settings-tab]");
        if (btn) {
            const settingsTabButtons = document.querySelectorAll(".tab-btn[data-settings-tab]");
            const settingsTabContents = document.querySelectorAll(".settings-tab-content");

            settingsTabButtons.forEach(b => b.classList.remove("active"));
            settingsTabContents.forEach(t => t.classList.remove("active"));

            btn.classList.add("active");
            const targetSubTab = btn.getAttribute("data-settings-tab");
            const targetEl = document.getElementById(targetSubTab);
            if (targetEl) {
                targetEl.classList.add("active");
            }
        }
    });

    // ── 2. THEME SELECTOR WIRING (R15 §1+§7: `.theme-mode-btn` keeps its name but is also a `.tab-btn`) ──
    const themeButtons = document.querySelectorAll(".theme-mode-btn");
    
    function applyTheme(theme) {
        document.body.classList.remove("theme-dark", "theme-light", "theme-system");
        document.body.classList.add(`theme-${theme}`);
        
        themeButtons.forEach(btn => {
            if (btn.getAttribute("data-theme") === theme) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
        
        localStorage.setItem("aesthetic-theme", theme);
    }
    
    themeButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const selectedTheme = btn.getAttribute("data-theme");
            applyTheme(selectedTheme);
        });
    });
    
    const savedTheme = localStorage.getItem("aesthetic-theme") || "dark";
    applyTheme(savedTheme);

    // ── 3. BLUETOOTH SCREEN SCANNER UI ──
    const scanBtn = document.getElementById("scan-btn");
    const scanSpinner = document.getElementById("scan-spinner");
    const deviceListUl = document.getElementById("device-list");

    // R42 §1: restore the persisted scan timeout/limit into the inputs —
    // they were saved on every change/scan but never read back, so the
    // template defaults reappeared each session.
    function restoreScanSettings() {
        window.pywebview?.api?.get_scan_settings?.().then(json => {
            try {
                const s = JSON.parse(json);
                const t = document.getElementById("scan-timeout");
                const l = document.getElementById("scan-limit");
                if (t && Number.isFinite(s.timeout)) t.value = s.timeout;
                if (l && Number.isFinite(s.limit)) l.value = s.limit;
            } catch (e) { /* keep template defaults */ }
        });
    }
    if (window.pywebview) restoreScanSettings();
    else window.addEventListener("pywebviewready", restoreScanSettings);

    // Settings footer version indicator (backend get_app_version → pyproject/plist).
    function loadAppVersion() {
        const el = document.getElementById("app-version");
        if (!el || !window.pywebview?.api?.get_app_version) return;
        Promise.resolve(window.pywebview.api.get_app_version())
            .then(v => { if (v) el.textContent = "v" + v; })
            .catch(() => {});
    }
    if (window.pywebview) loadAppVersion();
    else window.addEventListener("pywebviewready", loadAppVersion);

    // Persist scan timeout / limit values on change
    ["scan-timeout", "scan-limit"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("change", () => {
                const t = parseInt(document.getElementById("scan-timeout")?.value) || window.SCAN_TIMEOUT_DEFAULT;
                const l = parseInt(document.getElementById("scan-limit")?.value);
                if (window.pywebview && window.pywebview.api && window.pywebview.api.save_scan_settings) {
                    window.pywebview.api.save_scan_settings(t, isNaN(l) ? 0 : l);
                }
            });
        }
    });

    window.runBleScan = function() {
        const timeout = parseInt(document.getElementById("scan-timeout")?.value) || window.SCAN_TIMEOUT_DEFAULT;
        const limit = parseInt(document.getElementById("scan-limit")?.value) || 0;

        if (scanSpinner) scanSpinner.style.display = "inline-block";
        if (scanBtn) scanBtn.disabled = true;
        window.setScanning?.(true);

        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.scan_devices(timeout, limit)
                .then(devicesJson => {
                    if (scanSpinner) scanSpinner.style.display = "none";
                    if (scanBtn) scanBtn.disabled = false;
                    window.setScanning?.(false);

                    const devices = JSON.parse(devicesJson);
                    // R46 #5: merge (don't replace) so a device busy streaming a
                    // live widget — connected, hence not advertising, hence missed
                    // by this scan — stays selectable.
                    const merged = window.mergeDiscoveredDevices
                        ? window.mergeDiscoveredDevices(devices) : devices;
                    populateDeviceSelectors(merged);
                    window.showToast(`Discovered ${devices.length} screens!`, "success");
                    window.renderArrangerCanvas();
                    if (window.renderDeviceDots) window.renderDeviceDots();
                    if (window.refreshKnownDevices) window.refreshKnownDevices();
                })
                .catch(err => {
                    // The scan runs in the daemon, which can die mid-scan (e.g. a
                    // native BLE/CoreBluetooth crash on some Python builds). Don't
                    // leave the spinner stuck — re-enable + surface the error.
                    if (scanSpinner) scanSpinner.style.display = "none";
                    if (scanBtn) scanBtn.disabled = false;
                    window.setScanning?.(false);
                    window.showToast("Scan failed (device backend unavailable). See logs.", "error");
                    console.error("scan_devices failed:", err);
                });
        } else {
            if (scanSpinner) scanSpinner.style.display = "none";
            if (scanBtn) scanBtn.disabled = false;
            window.setScanning?.(false);
            window.showToast("Web interface API unavailable.", "error");
        }
    }

    if (scanBtn) {
        scanBtn.addEventListener("click", window.runBleScan);
    }

    function populateDeviceSelectors(devices) {
        if (deviceListUl) {
            deviceListUl.innerHTML = "";
            if (devices.length === 0) {
                deviceListUl.innerHTML = `<tr><td colspan="4" class="empty-list">No BLE screens found.</td></tr>`;
            } else {
                devices.forEach(d => {
                    const tr = document.createElement("tr");
                    tr.style.cursor = "pointer";
                    const color = window.deviceColor(d.address);
                    const dims = window.getDeviceDimensions ? window.getDeviceDimensions(d.name) : { size: 16 };
                    const isSpk = /timoo|ditoo|tivoo/i.test(d.name || "");
                    tr.innerHTML = `
                        <td>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span class="device-accent-dot" style="background:${color}; box-shadow:0 0 6px ${color}; width:8px; height:8px; border-radius:50%; display:inline-block;"></span>
                                <span>${d.name}</span>
                            </div>
                        </td>
                        <td><span class="device-mac">${d.address}</span></td>
                        <td>${dims.size}x${dims.size}</td>
                        <td>${isSpk ? "Yes" : "No"}</td>
                    `;
                    tr.addEventListener("click", () => {
                        window.connectDevice(d.name, d.address);
                    });
                    deviceListUl.appendChild(tr);
                });
            }
        }
        window.updateDeviceSelectorDropdown();
    }
    window.populateDeviceSelectors = populateDeviceSelectors;

    // ── 4. Wi-Fi (LAN) DEVICES MANAGER ──
    window.loadLanDevices = function() {
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.load_lan_devices()
                .then(json => {
                    try {
                        window.DivoomState.registeredLanDevices = JSON.parse(json);
                        renderLanDevicesList();
                        window.updateDeviceSelectorDropdown();
                    } catch(e) {
                        window.DivoomState.registeredLanDevices = [];
                    }
                });
        }
    }

    function renderLanDevicesList() {
        const tbody = document.getElementById("lan-device-list");
        if (!tbody) return;
        tbody.innerHTML = "";
        if (window.DivoomState.registeredLanDevices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-list">No Wi-Fi screens registered.</td></tr>';
            return;
        }
        window.DivoomState.registeredLanDevices.forEach(d => {
            const tr = document.createElement("tr");
            const dims = window.getDeviceDimensions ? window.getDeviceDimensions(`Wi-Fi Screen: ${d.ip}`) : { size: 16 };
            tr.innerHTML = `
                <td style="font-weight:600; cursor:pointer;" class="lan-connect-cell"> ${d.ip}</td>
                <td>${d.token || 0}</td>
                <td>${dims.size}x${dims.size}</td>
                <td>—</td>
                <td>
                    <button class="glow-btn compact delete-lan-btn" style="margin:0; background:rgba(255, 68, 68, 0.15); border-color:#ef4444; color:#ef4444; padding: 4px 8px; font-size: 11px;" data-ip="${d.ip}">Delete</button>
                </td>
            `;
            tr.querySelector(".lan-connect-cell").addEventListener("click", () => {
                window.connectDevice(`Local Network: ${d.ip}`, `LAN:${d.ip}`);
            });
            tr.querySelector(".delete-lan-btn").addEventListener("click", (e) => {
                e.stopPropagation();
                const ip = e.target.getAttribute("data-ip");
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.delete_lan_device(ip)
                        .then(ok => {
                            if (ok) {
                                window.showToast("Deleted Wi-Fi device", "success");
                                window.loadLanDevices();
                            }
                        });
                }
            });
            tbody.appendChild(tr);
        });
    }

    const addLanBtn = document.getElementById("add-lan-btn");
    if (addLanBtn) {
        addLanBtn.addEventListener("click", () => {
            const ipInput = document.getElementById("lan-ip-input");
            const tokenInput = document.getElementById("lan-token-input");
            const probeResult = document.getElementById("lan-probe-result");
            
            const ip = (ipInput?.value || "").trim();
            const token = parseInt(tokenInput?.value || "0");
            if (!ip) { window.showToast("Enter an IP Address", "error"); return; }
            
            if (probeResult) { probeResult.textContent = "Connecting..."; probeResult.className = "lan-probe-result"; }
            
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.add_lan_device(ip, token)
                    .then(ok => {
                        if (ok) {
                            window.showToast(`Added Wi-Fi device: ${ip}`, "success");
                            if (probeResult) { probeResult.textContent = "Device registered successfully."; probeResult.className = "lan-probe-result success"; }
                            if (ipInput) ipInput.value = "";
                            if (tokenInput) tokenInput.value = "0";
                            window.loadLanDevices();
                        } else {
                            window.showToast("Failed to add Wi-Fi device", "error");
                            if (probeResult) { probeResult.textContent = "Could not register device."; probeResult.className = "lan-probe-result error"; }
                        }
                    });
            }
        });
    }

    // R32: the transport-status polling panel was removed along with the
    // bottom-right corner indicator pill (its only consumer). The per-device
    // dots below the sidebar preview convey device/transport state now.

    // ── 6. CLOUD CREDENTIALS ──
    const saveCredsBtn = document.getElementById("save-creds-btn");
    if (saveCredsBtn) {
        saveCredsBtn.addEventListener("click", () => {
            const email = document.getElementById("settings-email").value.trim();
            const pwd = document.getElementById("settings-password").value.trim();

            if (!email || !pwd) {
                window.showToast("Email and Password are required!", "error");
                return;
            }

            window.showToast("Saving cloud credentials...", "success");
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.save_credentials(email, pwd)
                    .then(res => {
                        if (res) {
                            window.showToast("Credentials configured & login cache generated!", "success");
                            const statusBox = document.getElementById("divoom-cloud-status-box");
                            if (statusBox) {
                                statusBox.style.display = "flex";
                                statusBox.style.background = "rgba(34, 197, 94, 0.15)";
                                statusBox.style.border = "1px solid rgba(34, 197, 94, 0.3)";
                                statusBox.style.color = "#22c55e";
                                statusBox.innerHTML = `<span> Connected as <b>${email}</b></span>`;
                            }
                        } else {
                            window.showToast("Authentication failed. Please verify credentials.", "error");
                            const statusBox = document.getElementById("divoom-cloud-status-box");
                            if (statusBox) {
                                statusBox.style.display = "flex";
                                statusBox.style.background = "rgba(239, 68, 68, 0.15)";
                                statusBox.style.border = "1px solid rgba(239, 68, 68, 0.3)";
                                statusBox.style.color = "#ef4444";
                                statusBox.innerHTML = `<span> Not connected. Save your credentials to log in.</span>`;
                            }
                        }
                    });
            }
        });
    }

    // ── 7. BACKUP & RESTORE WIRING ──
    const exportSettingsBtn = document.getElementById("export-settings-btn");
    const importSettingsBtn = document.getElementById("import-settings-btn");

    if (exportSettingsBtn) {
        exportSettingsBtn.addEventListener("click", () => {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.export_settings_dialog().then(ok => {
                    if (ok) {
                        window.showToast("Settings exported successfully!", "success");
                    }
                });
            }
        });
    }

    if (importSettingsBtn) {
        importSettingsBtn.addEventListener("click", () => {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.import_settings_dialog().then(ok => {
                    if (ok) {
                        window.showToast("Settings imported successfully! Reloading...", "success");
                        setTimeout(() => {
                            window.location.reload();
                        }, 1500);
                    }
                });
            }
        });
    }

    // Initializers on mount after small delays
    setTimeout(window.loadLanDevices, 1200);
});
