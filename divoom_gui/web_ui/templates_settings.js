/* templates_settings.js — Settings panel template */
window.DivoomTemplates = window.DivoomTemplates || {};
// Single JS-side default for the scan timeout (seconds). Bootstrap fallback only:
// the daemon's DEFAULT_SCAN_TIMEOUT is the authority and is loaded into the input
// via get_scan_settings on open (restoreScanSettings). Keep in sync with it.
window.SCAN_TIMEOUT_DEFAULT = 20;
window.DivoomTemplates.settings = `                <!-- R15 §1+§7: tab chrome is now .tabs-row + .tab-btn
                     (defined in tabs.css) — same active state as Channels and
                     Tools. The glass-card wrapper unifies appearance with
                     the Channels tab row, which sits inside a card header. -->
                <div class="tabs-section" style="width:100%;">
                <div class="tabs-row" role="tablist" aria-label="Settings">
                    <button class="tab-btn active" data-settings-tab="settings-devices" data-tab="settings-devices" role="tab" aria-selected="true"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 13.5h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>Devices</button>
                    <button class="tab-btn" data-settings-tab="settings-divoom" data-tab="settings-divoom" role="tab" aria-selected="false"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 12h6a3 3 0 0 0 .4-6A4 4 0 0 0 4 7a3 3 0 0 0 1 5z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>Divoom</button>
                    <button class="tab-btn" data-settings-tab="settings-connectivity" data-tab="settings-connectivity" role="tab" aria-selected="false"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5a7 7 0 0 1 10 0M5.5 11a3.5 3.5 0 0 1 5 0" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="8" cy="13" r="1" fill="currentColor"/></svg>Connectivity</button>
                    <button class="tab-btn" data-settings-tab="settings-appearance" data-tab="settings-appearance" role="tab" aria-selected="false"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor"/></svg>Appearance</button>
                </div>
                </div><!-- /.tabs-section — R28 r2: close the pane HERE so the
                       content panels below are siblings, not nested inside the
                       tab glass pane (was wrapping the whole panel). -->

                <!-- 1. DEVICES TAB -->
                <div class="settings-tab-content active" id="settings-devices">
                    <div class="grid-layout">
                        <!-- BLE Scanner -->
                        <div class="card glass-card">
                            <div class="card-header">
                                <h3>Bluetooth Scanner</h3>
                            </div>
                            <div class="card-body">
                                <div class="flex gap-10" style="margin-bottom:15px;">
                                    <div style="flex:1;">
                                        <label class="form-label label-xs">Timeout (s)</label>
                                        <input type="number" id="scan-timeout" min="3" max="120" value="${window.SCAN_TIMEOUT_DEFAULT}" class="text-input">
                                    </div>
                                    <div style="flex:1;">
                                        <label class="form-label label-xs">Devices</label>
                                        <input type="number" id="scan-limit" min="0" max="10" value="4" class="text-input">
                                    </div>
                                </div>

                                <button id="scan-btn" class="glow-btn">
                                    <span class="spinner" id="scan-spinner"></span> Scan Devices
                                </button>

                                <div style="margin-top: 20px;">
                                    <label class="label-caption">Discovered Bluetooth Screens</label>
                                    <table class="braun-table">
                                        <thead>
                                            <tr>
                                                <th>Device Name</th>
                                                <th>Address</th>
                                                <th>Resolution</th>
                                                <th>Speaker</th>
                                            </tr>
                                        </thead>
                                        <tbody id="device-list">
                                            <tr><td colspan="4" class="empty-list">No Bluetooth screens found.</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>

                        <!-- Wi-Fi Devices -->
                        <div class="card glass-card">
                            <div class="card-header">
                                <h3>Wi-Fi Screens</h3>
                            </div>
                            <div class="card-body">
                                <div class="flex gap-10" style="margin-bottom:15px;">
                                    <div style="flex:2;">
                                        <label class="form-label label-xs">IP Address</label>
                                        <input type="text" id="lan-ip-input" class="text-input" placeholder="192.168.1.42">
                                    </div>
                                    <div style="flex:1;">
                                        <label class="form-label label-xs">Token</label>
                                        <input type="number" id="lan-token-input" class="text-input" value="0" min="0">
                                    </div>
                                    <div style="display:flex; align-items:flex-end;">
                                        <button id="add-lan-btn" class="glow-btn compact" style="height:38px;">Add</button>
                                    </div>
                                </div>
                                <div class="lan-probe-result" id="lan-probe-result" style="margin-bottom:10px;"></div>

                                <div style="margin-top: 10px;">
                                    <label class="label-caption">Registered Wi-Fi Screens</label>
                                    <table class="braun-table">
                                        <thead>
                                            <tr>
                                                <th>IP Address</th>
                                                <th>Token</th>
                                                <th>Resolution</th>
                                                <th>Speaker</th>
                                                <th>Action</th>
                                            </tr>
                                        </thead>
                                        <tbody id="lan-device-list">
                                            <tr><td colspan="5" class="empty-list">No Wi-Fi screens registered.</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                        <!-- R40 §8: Device Settings / Display / Danger zone moved to
                             the new "Device Settings" sidebar section
                             (templates_device_settings.js). This tab keeps only the
                             scan/connect tables above. -->
                        <!-- R15 §3: the Notification + macOS Notifications cards
                             moved to Live Widgets (siblings of the Weather card)
                             so all "things the device can show right now" live
                             in one place. -->
                    </div>
                </div>

                <!-- 2. DIVOOM TAB -->
                <div class="settings-tab-content" id="settings-divoom">
                    <div class="grid-layout single-col" style="max-width: 540px;">
                        <!-- Divoom Cloud -->
                        <div class="card glass-card">
                            <div class="card-header">
                                <h3>Divoom Cloud</h3>
                            </div>
                            <div class="card-body">
                                <div class="form-group">
                                    <input type="email" id="settings-email" class="text-input" placeholder="Email Address">
                                </div>
                                <div class="form-group">
                                    <input type="password" id="settings-password" class="text-input" placeholder="Account Password">
                                </div>
                                <button id="save-creds-btn" class="glow-btn pulse-glow" style="display:inline-flex; align-items:center; justify-content:center;">
                                    <svg class="kare-icon" viewBox="0 0 16 16" style="margin-right: 6px;">
                                        <path d="M2,2 L11,2 L14,5 L14,14 L2,14 Z" fill="none" stroke="currentColor" stroke-width="2"/>
                                        <rect x="5" y="2" width="5" height="4" fill="none" stroke="currentColor" stroke-width="1"/>
                                        <rect x="7" y="3" width="1" height="2"/>
                                        <rect x="4" y="9" width="8" height="5" fill="none" stroke="currentColor" stroke-width="1.5"/>
                                    </svg>
                                    Save Credentials
                                </button>
                                <div id="divoom-cloud-status-box" style="margin-top: 15px; padding: 12px; border-radius: 6px; font-size: 12px; font-weight: 600; display: none; align-items: center; gap: 8px;"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 3. CONNECTIVITY TAB. R32 §E: the "Connectivity & Privacy"
                     explainer legend was removed — the four corner transport dots
                     already communicate state, and the prose was redundant. -->
                <div class="settings-tab-content" id="settings-connectivity">
                    <div class="grid-layout single-col" style="max-width: 540px;">
                    <!-- R40 §9: daemon (menu bar) lifecycle. -->
                    <div class="card glass-card">
                        <div class="card-header flex-header">
                            <h3>Background agent</h3>
                            <label class="switch" title="Keep the daemon + menu bar running after the dashboard quits"><input type="checkbox" id="keep-daemon-toggle"><span class="slider-round"></span></label>
                        </div>
                        <div class="card-body">
                            <p class="panel-hint">Keep the menu-bar agent (and the device daemon) running when you quit the dashboard. When off, quitting the dashboard also closes the menu bar, and choosing <em>Quit Divoom</em> from the menu bar also closes the dashboard.</p>
                        </div>
                    </div>
                    <!-- Menu-bar cleanup on quit (only applies when Background agent is off). -->
                    <div class="card glass-card">
                        <div class="card-header flex-header">
                            <h3>Quit menu bar with dashboard</h3>
                            <label class="switch" title="Also quit the menu-bar agent when you close the dashboard"><input type="checkbox" id="quit-menubar-toggle"><span class="slider-round"></span></label>
                        </div>
                        <div class="card-body">
                            <p class="panel-hint">On (default): closing the dashboard also quits the menu-bar agent for a fully clean shutdown (no leftover tray icon). Off: the menu bar keeps running so you can relaunch the dashboard from it. Ignored when <em>Background agent</em> is on.</p>
                        </div>
                    </div>
                    <!-- R15 §5: MCP server (Model Context Protocol) — exposes
                         12 device-control tools over stdio JSON-RPC. Connect
                         Claude Desktop, Cursor, Cline, or Continue to control
                         the device with natural language. See docs/MCP_SERVER.md. -->
                    <div class="card glass-card">
                        <div class="card-header flex-header">
                            <h3>MCP Server</h3>
                            <!-- R42 §9: toggle lives header-right, like Background agent. -->
                            <label class="switch" title="Run the MCP server">
                                <input type="checkbox" id="mcp-toggle">
                                <span class="slider-round"></span>
                            </label>
                        </div>
                        <div class="card-body col gap-10">
                            <p class="panel-hint">Runs <code>divoom-control mcp-server</code> which routes all device calls through the daemon. Point any MCP-compatible client at this machine's <code>divoom-control</code> binary; see <code>docs/MCP_SERVER.md</code> for setup.</p>
                            <div class="row gap-10">
                                <span id="mcp-status-detail" class="panel-hint text-mono-sm" style="margin-left:auto;">PID: --</span>
                            </div>
                            <pre id="mcp-log" class="panel-hint text-mono-sm" style="max-height: 140px; overflow-y: auto; background: rgba(0,0,0,0.25); padding: 8px; border-radius: 4px; white-space: pre-wrap;">No log entries yet.</pre>
                        </div>
                    </div>
                    </div>
                </div>

                <!-- 4. APPEARANCE TAB -->
                <div class="settings-tab-content" id="settings-appearance">
                    <div class="grid-layout single-col" style="max-width: 540px;">
                        <!-- Aesthetic Theme Mode -->
                        <div class="card glass-card">
                            <div class="card-header">
                                <h3>Theme</h3>
                            </div>
                            <div class="card-body">
                                <div class="tabs-row theme-buttons" role="tablist" aria-label="Theme">
                                    <button class="tab-btn theme-mode-btn active" data-theme="dark" role="tab" aria-selected="true" title="Dark Mode">
                                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                                            <path d="M12,2 C10,2 6,4 6,9 C6,13 9,14 12,14 C6,16 2,12 2,8 C2,4 6,2 12,2 Z" fill="currentColor"/>
                                        </svg>
                                        Dark
                                    </button>
                                    <button class="tab-btn theme-mode-btn" data-theme="light" role="tab" aria-selected="false" title="Light Mode">
                                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                                            <circle cx="8" cy="8" r="3" fill="currentColor"/>
                                            <path d="M8,1 L8,3 M8,13 L8,15 M1,8 L3,8 M13,8 L15,8 M3,3 L4.5,4.5 M11.5,11.5 L13,13 M3,13 L4.5,11.5 M11.5,4.5 L13,3" stroke="currentColor" stroke-width="2"/>
                                        </svg>
                                        Light
                                    </button>
                                    <button class="tab-btn theme-mode-btn" data-theme="system" role="tab" aria-selected="false" title="System Auto">
                                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                                            <rect x="1" y="2" width="14" height="10" rx="1" fill="none" stroke="currentColor" stroke-width="2"/>
                                            <rect x="6" y="12" width="4" height="2"/>
                                            <rect x="4" y="14" width="8" height="1"/>
                                        </svg>
                                        Auto
                                    </button>
                                </div>
                            </div>
                        </div>

                        <!-- Backup & Restore -->
                        <div class="card glass-card">
                            <div class="card-header">
                                <h3>Backup &amp; Restore</h3>
                            </div>
                            <div class="card-body col gap-12">
                                <p style="font-size:11px; color:rgba(255,255,255,0.45);">
                                    Export or import your entire configuration, presets, alarms, and settings.
                                </p>
                                <div class="flex gap-10" style="margin-top:4px;">
                                    <button id="export-settings-btn" class="glow-btn compact" title="Export settings to JSON file">
                                        Export to File...
                                    </button>
                                    <button id="import-settings-btn" class="glow-btn compact" title="Import settings from JSON file" style="background:rgba(34,197,94,0.1); border-color:rgba(34,197,94,0.3);">
                                        Import from File...
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="settings-version panel-hint" style="text-align:center; margin-top:14px; opacity:0.6; font-size:11px;">Divoom Control <span id="app-version">v...</span></div>
                </div>
    `;
