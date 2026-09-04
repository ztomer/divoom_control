/* settings_notifications.js — macOS Notification Center Mirroring & MCP Server toggles */

document.addEventListener("DOMContentLoaded", () => {
    function api() { return window.pywebview && window.pywebview.api; }
    function dev() { return !window.requireDevice || window.requireDevice(); }
    function toast(r, ok, fail) { window.showToast(r ? ok : (fail || "Failed"), r ? "success" : "error", " BLE"); }

    // ── R14 §3 — macOS notification mirroring (Settings → Devices card) ──
    const macToggle    = document.getElementById("macnotif-toggle");
    const macDetail    = document.getElementById("macnotif-detail");
    const macPill      = document.getElementById("macnotif-status-pill");
    const macRulesJson = document.getElementById("macnotif-rules-json");
    const macRulesSave = document.getElementById("macnotif-rules-save");
    const macRulesReset = document.getElementById("macnotif-rules-reset");
    const macRulesMsg  = document.getElementById("macnotif-rules-msg");
    const macRoutingPathEl = document.getElementById("macnotif-routing-path");

    let permissionsDialogShownThisSession = false;

    window.showMacPermissionsDialog = function(errorMessage) {
        document.querySelectorAll(".arranger-popup.mac-permissions-popup").forEach(p => p.remove());

        const popup = document.createElement("div");
        popup.className = "arranger-popup mac-permissions-popup";
        popup.style.maxWidth = "480px";
        popup.style.width = "90%";
        popup.innerHTML = `
            <h3 style="font-family: var(--font-display); font-size:16px; margin-bottom:15px; color: var(--text-main);">macOS Notification Permissions Required</h3>
            <p style="font-size:12px; color:var(--text-main); margin-bottom:15px; line-height:1.4;">
                To mirror macOS notifications to your Divoom screens, the background Python runtime needs Full Disk Access to read the Notification Center database.
            </p>
            <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:12px; margin-bottom:15px; font-size:11px; line-height:1.5; color:rgba(255,255,255,0.7);">
                <strong style="display:block; margin-bottom:4px; color:#ef4444;">Step-by-step instructions:</strong>
                1. Open <b>System Settings</b> on your Mac.<br>
                2. Navigate to <b>Privacy &amp; Security</b> &rarr; <b>Full Disk Access</b>.<br>
                3. Click the <b>+ (Plus)</b> icon at the bottom of the list.<br>
                4. Select and add <b>python3</b> (located in your Python installation directory, e.g. <code>/opt/homebrew/bin/python3</code> or <code>/usr/bin/python3</code>).<br>
                5. Make sure the toggle next to <b>python3</b> is turned <b>ON</b>.<br>
                6. Restart the Divoom Control application.
            </div>
            <div style="display:flex; gap:10px; justify-content:flex-end;">
                <button id="mac-permissions-close" class="glow-btn compact" style="background: var(--primary); border: 1px solid var(--primary); color:#fff; box-shadow:none;">Close</button>
            </div>
        `;
        document.body.appendChild(popup);
        document.getElementById("mac-permissions-close").addEventListener("click", () => popup.remove());
    };

    function setMacPill(state) {
        if (!macPill) return;
        macPill.textContent = state;
        if (state.toLowerCase().includes("error")) {
            macPill.dataset.state = "error";
        } else {
            macPill.dataset.state = state.toLowerCase();
        }
    }

    function renderMacNotifStatus(s) {
        if (!s) return;
        if (macRoutingPathEl && s.routing_path) macRoutingPathEl.textContent = s.routing_path;
        if (!s.platform_supported) {
            if (macToggle) { macToggle.disabled = true; macToggle.checked = false; }
            setMacPill("unsupported");
            if (macDetail) macDetail.textContent = "macOS notifications are only available on macOS.";
            return;
        }
        if (macToggle) macToggle.disabled = false;

        const isPermissionError = s.error && (
            s.error.includes("PermissionError") || 
            s.error.includes("FULL DISK ACCESS") || 
            s.error.includes("sqlite3.OperationalError") ||
            s.error.includes("Full Disk Access")
        );

        if (s.running) {
            setMacPill("running");
            if (macToggle) macToggle.checked = true;
        } else {
            if (isPermissionError) {
                setMacPill("Permission Error");
            } else {
                setMacPill(s.error ? "error" : "stopped");
            }
            if (macToggle) macToggle.checked = false;
        }

        if (isPermissionError) {
            if (macPill && !document.getElementById("macnotif-fix-permissions-btn")) {
                const fixBtn = document.createElement("button");
                fixBtn.id = "macnotif-fix-permissions-btn";
                fixBtn.className = "glow-btn compact";
                fixBtn.style.marginLeft = "10px";
                fixBtn.style.padding = "2px 8px";
                fixBtn.style.fontSize = "10px";
                fixBtn.style.background = "rgba(239,68,68,0.15)";
                fixBtn.style.borderColor = "rgba(239,68,68,0.3)";
                fixBtn.style.color = "#ef4444";
                fixBtn.textContent = "Fix Permissions...";
                fixBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    window.showMacPermissionsDialog(s.error);
                });
                macPill.parentNode.appendChild(fixBtn);
            }
            
            if (!permissionsDialogShownThisSession) {
                permissionsDialogShownThisSession = true;
                window.showMacPermissionsDialog(s.error);
            }
        } else {
            const fixBtn = document.getElementById("macnotif-fix-permissions-btn");
            if (fixBtn) fixBtn.remove();
        }

        const c = s.counters || { seen: 0, routed: 0, dropped: 0 };
        if (macDetail) {
            macDetail.textContent = [
                `status:    ${s.running ? "running" : (isPermissionError ? "Permission Error" : (s.error || "stopped"))}`,
                `db:        ${s.db_path || "(not found)"}`,
                `seen:      ${c.seen}`,
                `routed:    ${c.routed}`,
                `dropped:   ${c.dropped}`,
            ].join("\n");
        }
        if (macRulesJson && s.rules && !macRulesJson.dataset.dirty) {
            macRulesJson.value = JSON.stringify(s.rules, null, 2);
        }
    }

    function refreshMacNotifStatus() {
        const a = api();
        if (!a?.get_notification_listener_status) return;
        a.get_notification_listener_status().then(renderMacNotifStatus);
    }

    refreshMacNotifStatus();
    // R59/event-driven: the daemon now broadcasts `notif_status` on every
    // monitor start/stop/error transition, so the 5s poll is gone. Keep the
    // one-shot probe above for the already-running monitor on first open.

    if (macToggle) {
        macToggle.addEventListener("change", async () => {
            const a = api();
            if (!a) return;
            try {
                if (macToggle.checked) {
                    const r = await a.start_notification_listener();
                    if (r && r.error) {
                        macToggle.checked = false;
                        toast(r.error, "Mirror failed");
                        const isPermErr = r.error.includes("PermissionError") || 
                                          r.error.includes("FULL DISK ACCESS") || 
                                          r.error.includes("sqlite3.OperationalError") ||
                                          r.error.includes("Full Disk Access");
                        if (isPermErr) {
                            window.showMacPermissionsDialog(r.error);
                        }
                    }
                } else {
                    await a.stop_notification_listener();
                }
            } finally {
                refreshMacNotifStatus();
            }
        });
    }

    if (macRulesJson) {
        macRulesJson.addEventListener("input", () => {
            macRulesJson.dataset.dirty = "1";
            if (macRulesMsg) { macRulesMsg.textContent = "unsaved changes"; macRulesMsg.dataset.state = "warn"; }
        });
    }

    if (macRulesSave) {
        macRulesSave.addEventListener("click", async () => {
            const a = api();
            if (!a?.save_notification_routing) return;
            const r = await a.save_notification_routing(macRulesJson.value || "[]");
            if (r.error) {
                if (macRulesMsg) { macRulesMsg.textContent = r.error; macRulesMsg.dataset.state = "error"; }
                return;
            }
            delete macRulesJson.dataset.dirty;
            macRulesJson.value = JSON.stringify(r.rules, null, 2);
            if (macRulesMsg) { macRulesMsg.textContent = "saved"; macRulesMsg.dataset.state = "ok"; }
        });
    }

    if (macRulesReset) {
        macRulesReset.addEventListener("click", async () => {
            const a = api();
            if (!a?.save_notification_routing) return;
            // Pass an empty list to revert to DEFAULT_ROUTING.
            const r = await a.save_notification_routing("[]");
            if (r.error) {
                if (macRulesMsg) { macRulesMsg.textContent = r.error; macRulesMsg.dataset.state = "error"; }
                return;
            }
            delete macRulesJson.dataset.dirty;
            macRulesJson.value = JSON.stringify(r.rules, null, 2);
            if (macRulesMsg) { macRulesMsg.textContent = "reset to defaults"; macRulesMsg.dataset.state = "ok"; }
        });
    }

    // ── R15 §5: MCP server toggle ────────────────────────────────
    // R40 §9: keep-daemon-alive toggle (Connectivity → Background agent).
    const keepDaemonToggle = document.getElementById("keep-daemon-toggle");
    if (keepDaemonToggle) {
        keepDaemonToggle.addEventListener("change", () => {
            api()?.set_keep_daemon_alive?.(keepDaemonToggle.checked).then(ok => {
                window.showToast(ok ? (keepDaemonToggle.checked
                    ? "Menu bar will stay running after quit"
                    : "Menu bar will close with the dashboard") : "Failed to save",
                    ok ? "success" : "error");
            });
        });
    }

    // Quit-menu-bar-on-exit toggle (Connectivity → Quit menu bar with dashboard).
    const quitMenubarToggle = document.getElementById("quit-menubar-toggle");
    if (quitMenubarToggle) {
        quitMenubarToggle.addEventListener("change", () => {
            api()?.set_quit_menubar_on_exit?.(quitMenubarToggle.checked).then(ok => {
                window.showToast(ok ? (quitMenubarToggle.checked
                    ? "Menu bar will quit with the dashboard"
                    : "Menu bar will keep running (relaunch from tray)") : "Failed to save",
                    ok ? "success" : "error");
            });
        });
    }

    // Reflect the PERSISTED lifecycle-flag values into the toggles. This must wait
    // for the pywebview API to exist: at DOMContentLoaded `window.pywebview` is
    // often not injected yet, so a bare api() read was silently skipped and a
    // true-valued flag (e.g. quit_menubar_on_exit's default) showed as off — the
    // toggle kept its unchecked HTML default. Same guard as restoreScanSettings.
    function syncLifecycleToggles() {
        if (keepDaemonToggle)
            api()?.get_keep_daemon_alive?.().then(v => { keepDaemonToggle.checked = !!v; });
        if (quitMenubarToggle)
            api()?.get_quit_menubar_on_exit?.().then(v => { quitMenubarToggle.checked = !!v; });
    }
    if (window.pywebview) syncLifecycleToggles();
    else window.addEventListener("pywebviewready", syncLifecycleToggles);

    const mcpToggle = document.getElementById("mcp-toggle");
    const mcpStatusDetail = document.getElementById("mcp-status-detail");
    const mcpLog = document.getElementById("mcp-log");

    function renderMcpStatus(s) {
        if (!s) return;
        const running = !!s.running;
        if (mcpToggle) mcpToggle.checked = running;
        if (mcpStatusDetail) {
            mcpStatusDetail.textContent = running
                ? (s.pid ? `PID: ${s.pid}  mac: ${s.mac || "--"}` : "running")
                : "stopped";
        }
        if (mcpLog) {
            const lines = Array.isArray(s.last_log_lines) ? s.last_log_lines : [];
            mcpLog.textContent = lines.length ? lines.join("\n") : "No log entries yet.";
        }
    }

    function refreshMcpStatus() {
        if (!api()?.mcp_server_status) return;
        Promise.resolve(api().mcp_server_status()).then(s => renderMcpStatus(s));
    }

    if (mcpToggle) {
        mcpToggle.addEventListener("change", () => {
            if (mcpToggle.checked) {
                if (!api()?.start_mcp_server) return;
                mcpToggle.disabled = true;
                Promise.resolve(api().start_mcp_server("")).then(s => {
                    mcpToggle.disabled = false;
                    renderMcpStatus(s);
                });
            } else {
                if (!api()?.stop_mcp_server) return;
                mcpToggle.disabled = true;
                Promise.resolve(api().stop_mcp_server()).then(s => {
                    mcpToggle.disabled = false;
                    renderMcpStatus(s);
                });
            }
        });
    }

    // Refresh status on tab activation.
    window.addEventListener("tab-changed", (e) => {
        if (e.detail && e.detail.tab === "settings") {
            refreshMcpStatus();
        }
    });

    refreshMcpStatus();
});
