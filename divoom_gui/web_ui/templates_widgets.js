/* templates_widgets.js — Widgets panel template */
window.DivoomTemplates = window.DivoomTemplates || {};
window.DivoomTemplates.widgets = `                <div class="grid-layout three-cols">
                    <!-- macOS Music Tracker -->
                    <div class="card glass-card" id="widget-card-music">
                        <div class="card-header flex-header">
                            <h3>Live cover art</h3>
                            <span class="active-indicator"></span>
                        </div>
                        <div class="card-body">
                            <!-- Cover art + device preview side-by-side, larger than before (Rams #10: as little as possible — no visualizer) -->
                            <div class="music-previews-container mb-12">
                                <div class="music-cover-preview" style="width:144px; height:144px;">
                                    <div class="cover-vinyl"></div>
                                    <img id="music-cover-img" src="assets/pixoo.png" alt="Vinyl Cover">
                                </div>
                                <div class="music-device-preview-wrap" style="flex:1; min-width:0;">
                                    <img id="music-device-preview" class="device-preview-img" alt="Device Preview" style="display:none; max-width:100%; max-height:144px;">
                                </div>
                            </div>

                            <!-- Track Info (Kare: just the essentials — name + artist) -->
                            <div class="music-tracker-card active col gap-8" id="music-track-status">
                                <div class="music-track-info">
                                    <h4 id="music-track-name">No Music Playing</h4>
                                    <p id="music-artist-name">Spotify / Apple Music</p>
                                </div>
                                <!-- Cover art is pushed automatically on track change while sync is on
                                     (R11) — the manual push button is obsolete and was removed. -->
                            </div>
                        </div>
                    </div>
                    
                    <!-- Stock Prices Widget -->
                    <div class="card glass-card clip-shrink" id="widget-card-stock">
                        <div class="card-header flex-header">
                            <h3>Live Stocks &amp; Crypto Tickers</h3>
                            <span class="active-indicator"></span>
                        </div>
                        <div class="card-body clip-shrink">
                            <!-- Preview on top. min-width:0 on flex children so the
                                 ticker box can shrink to fit narrow columns (Kare:
                                 fits the container, Rams #5 unobtrusive). -->
                            <div class="flex gap-12 mb-12" style="align-items:stretch; min-width:0;">
                                <div class="device-preview-wrap large">
                                    <img id="ticker-device-preview" class="device-preview-img" alt="" style="display:none;">
                                </div>
                                <div class="widget-preview-ticker" id="ticker-preview-box" style="flex:1; min-width:0; margin:0; padding:12px;">
                                    <div class="mini-canvas-view" style="min-width:0;">
                                        <div class="ticker-arrow-mock">↑</div>
                                        <div class="ticker-price-mock">$64,285</div>
                                        <div class="ticker-name-mock">BTC</div>
                                    </div>
                                </div>
                            </div>

                            <!-- Input below -->
                            <div class="form-group">
                                <div class="flex-row">
                                    <input type="text" id="stock-symbol-input" placeholder="Symbol e.g. AAPL, BTC-USD" class="text-input" value="BTC-USD">
                                    <button id="add-ticker-btn" class="glow-btn compact">Add</button>
                                </div>
                            </div>

                            <div id="tickers-list" class="tickers-list"></div>
                        </div>
                    </div>
 
                    <!-- System Monitor -->
                    <div class="card glass-card clip-shrink" id="widget-card-sysmon">
                        <div class="card-header flex-header">
                            <h3>System Monitor</h3>
                            <!-- R40 §4: Live (5s) is a header-right toggle (like Auto-Sync Gallery). -->
                            <label class="switch" title="Live updates every 5s"><input type="checkbox" id="sysmon-live" checked><span class="slider-round"></span></label>
                        </div>
                        <div class="card-body" style="min-width:0;">
                            <!-- Device preview (the actual frame the device shows).
                                 Above-the-fold: just the dark frame, no white panel. -->
                            <div class="flex mb-12" style="justify-content:center;">
                                <div class="device-preview-wrap large">
                                    <img id="sysmon-device-preview" class="device-preview-img" alt="" style="display:none;">
                                </div>
                            </div>

                            <!-- Three labeled bars: CPU (green) / MEM (blue) / BAT (yellow).
                                 Colors match the on-device bar colors so it's recognizable
                                 in 1 second (Rams #4). No white/gray background panels. -->
                            <div class="sysmon-bars col gap-6" style="margin-bottom:10px;">
                                <div class="sysmon-bar-row" data-stat="cpu">
                                    <span class="sysmon-bar-label text-warn">CPU</span>
                                    <div class="sysmon-bar-track">
                                        <div class="sysmon-bar-fill" data-fill-color="#ffcc00" style="width:0%; background:#ffcc00;"></div>
                                    </div>
                                    <b class="sysmon-bar-value text-warn" id="sysmon-cpu">–</b>
                                </div>
                                <div class="sysmon-bar-row" data-stat="mem">
                                    <span class="sysmon-bar-label" style="color:#5aaaff;">MEM</span>
                                    <div class="sysmon-bar-track">
                                        <div class="sysmon-bar-fill" data-fill-color="#5aaaff" style="width:0%; background:#5aaaff;"></div>
                                    </div>
                                    <b class="sysmon-bar-value" id="sysmon-mem" style="color:#5aaaff;">–</b>
                                </div>
                                <div class="sysmon-bar-row" data-stat="bat">
                                    <span class="sysmon-bar-label text-error">BAT</span>
                                    <div class="sysmon-bar-track">
                                        <div class="sysmon-bar-fill" data-fill-color="#ff4444" style="width:0%; background:#ff4444;"></div>
                                    </div>
                                    <b class="sysmon-bar-value text-error" id="sysmon-bat">–</b>
                                </div>
                            </div>
                            <!-- Honest unavailable state. These readings come
                                 from the daemon (same source the device is
                                 pushed), so when it cannot answer the card must
                                 SAY SO rather than leave the last numbers up
                                 looking live. -->
                            <div class="sysmon-unavailable" id="sysmon-unavailable" style="display:none;"></div>
                        </div>
                    </div>

                    <!-- R15 §3: Weather is its own card now (was nested
                         inside the sysmon card). The body is JUST the
                         128x128 preview — no text, no button (Kare: the
                         preview is the only thing the user needs to see;
                         auto-push fires on card selection). -->
                    <div class="card glass-card clip-shrink" id="widget-card-weather">
                        <div class="card-header flex-header">
                            <h3>Weather</h3>
                            <!-- R40 §4: Live (15m) header-right toggle; replaces the Push button. -->
                            <label class="switch" title="Live updates every 15 min"><input type="checkbox" id="weather-live"><span class="slider-round"></span></label>
                        </div>
                        <div class="card-body col gap-10" style="align-items:center;">
                            <div id="weather-device-preview" class="device-preview-wrap large">
                                <span id="weather-preview-temp" class="weather-preview-temp">--</span>
                                <svg id="weather-preview-icon" class="weather-preview-icon" viewBox="0 0 16 16" aria-hidden="true">
                                    <circle cx="8" cy="8" r="3" fill="currentColor"/>
                                </svg>
                            </div>
                            <span id="weather-preview-location" class="text-mono-sm" style="color: var(--text-muted);">--</span>
                        </div>
                    </div>

                    <!-- R15 §3: Manual Notification (was Settings → Devices).
                         Just the form — no description text, no Settings framing. -->
                    <div class="card glass-card clip-shrink" id="widget-card-notif-manual">
                        <div class="card-header flex-header">
                            <h3>Notification</h3>
                            <span class="active-indicator"></span>
                        </div>
                        <div class="card-body col gap-12">
                            <div class="row wrap gap-10">
                                <span class="form-label" style="font-size:12px; min-width:60px;">App</span>
                                <select id="notif-app-select" class="text-input" style="flex:1; min-width:140px;">
                                    <option value="6">WhatsApp</option>
                                    <option value="7">Text message</option>
                                    <option value="2">Instagram</option>
                                    <option value="4">Facebook</option>
                                    <option value="5">Twitter</option>
                                    <option value="13">Messenger</option>
                                    <option value="3">Snapchat</option>
                                    <option value="8">Skype</option>
                                    <option value="9">LINE</option>
                                    <option value="10">WeChat</option>
                                    <option value="11">QQ</option>
                                    <option value="12">Viber</option>
                                    <option value="1">KakaoTalk</option>
                                    <option value="14">Other</option>
                                </select>
                            </div>
                            <div class="row wrap gap-10">
                                <input type="text" id="notif-text" class="text-input" maxlength="128" style="flex:1; min-width:140px;" placeholder="Optional text">
                                <button id="notif-send" class="glow-btn compact">Send</button>
                            </div>
                        </div>
                    </div>

                    <!-- R15 §3: macOS Notifications mirror (was Settings → Devices). -->
                    <div class="card glass-card clip-shrink" id="widget-card-notif-mirror">
                        <div class="card-header flex-header">
                            <h3>macOS Notifications</h3>
                            <!-- R40 §4: Mirror is a header-right toggle (status pill moves left of it). -->
                            <div class="row gap-8">
                                <span class="status-pill" id="macnotif-status-pill">unknown</span>
                                <label class="switch" title="Mirror macOS notifications to the device"><input type="checkbox" id="macnotif-toggle"><span class="slider-round"></span></label>
                            </div>
                        </div>
                        <div class="card-body col gap-12">
                            <span id="macnotif-toggle-label" class="panel-hint">Mirror macOS notifications to the device.</span>
                            <div id="macnotif-detail" class="panel-hint text-mono-sm">
                                Status: loading...
                            </div>
                            <details>
                                <summary class="form-label" style="cursor:pointer; user-select:none;">Routing rules</summary>
                                <p class="panel-hint mt-6">Each rule maps a macOS app/bundle-id substring to a Divoom notification type. First match wins. Edit JSON; <em>Save</em> persists to <code id="macnotif-routing-path">~/.config/divoom-control/notification_routing.json</code> and hot-reloads.</p>
                                <textarea id="macnotif-rules-json" class="text-input text-mono-sm" rows="10" spellcheck="false" style="width: 100%; resize: vertical; min-height: 180px;"></textarea>
                                <div class="row gap-8 mt-6">
                                    <button id="macnotif-rules-save" class="glow-btn compact">Save</button>
                                    <button id="macnotif-rules-reset" class="glow-btn compact secondary">Reset to defaults</button>
                                    <span id="macnotif-rules-msg" class="panel-hint" style="font-size: 11px;"></span>
                                </div>
                            </details>
                        </div>
                    </div>
                </div>
    `;
