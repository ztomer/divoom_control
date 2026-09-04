/* templates_routines.js — Schedule panel (Auto-Sync + Time); R45 #5 rename
   (was "Routines"; the inner "Schedule" tab is now "Auto-Sync" to avoid a
   Schedule > Schedule collision). Code identifiers (routines-*) unchanged. */
window.DivoomTemplates = window.DivoomTemplates || {};
window.DivoomTemplates.routines = `
        <div class="tabs-section">
        <div class="tabs-row" role="tablist" aria-label="Schedule">
            <button class="tab-btn active" data-routines-tab="routines-schedule" data-tab="routines-schedule" role="tab" aria-selected="true"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5 8L8 11L12 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>Auto-Sync</button>
            <button class="tab-btn" data-routines-tab="routines-time" data-tab="routines-time" role="tab" aria-selected="false"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>Time</button>
            <button class="tab-btn" data-routines-tab="routines-sleep-sounds" data-tab="routines-sleep-sounds" role="tab" aria-selected="false"><svg class="tab-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5,1.5 C6,1.5 3.5,4.5 3.5,8 C3.5,11.5 6,14.5 9.5,14.5 C11,14.5 12.3,14 13.3,13.1 C11.7,13.6 9.9,13.3 8.5,12.2 C6.3,10.4 5.9,7.1 7.7,4.9 C8.5,3.9 9.6,3.3 10.8,3.1 C10.2,2.1 9.9,1.5 9.5,1.5 Z"/></svg>Sleep Sounds</button>
        </div>
        </div>

        <!-- SCHEDULE sub-tab (ex-Settings → Routines) -->
        <div class="routines-subtab-content active" id="routines-schedule">
        <!-- R42 §7: +15% over the R41 336px (names were getting clipped). -->
        <div class="grid-layout" style="grid-template-columns: 1fr; max-width: 386px;">
            <div class="card glass-card">
                <div class="card-header flex-header">
                    <h3>Auto-Sync Gallery</h3>
                    <div class="row gap-8" style="align-items:center;">
                        <button id="sync-now-btn" class="glow-btn compact">Sync Now</button>
                        <label class="switch">
                            <input type="checkbox" id="routines-auto-sync-enabled">
                            <span class="slider-round"></span>
                        </label>
                    </div>
                </div>
                <div class="card-body">
                    <div id="sync-targets-list" class="sync-targets-list mb-18"></div>

                    <div class="mb-18">
                        <label class="form-label label-sm">Sync every</label>
                        <div class="tabs-row" role="tablist" id="routines-interval-tabs">
                            <button class="tab-btn active" data-interval="3600">1h</button>
                            <button class="tab-btn" data-interval="21600">6h</button>
                            <button class="tab-btn" data-interval="43200">12h</button>
                            <button class="tab-btn" data-interval="86400">24h</button>
                            <button class="tab-btn" data-interval="604800">7d</button>
                            <button class="tab-btn" data-interval="2592000">30d</button>
                        </div>
                    </div>

                    <span id="routines-auto-sync-status" class="panel-hint" style="display:block; margin-top:8px;"></span>
                    <span id="sync-now-status" class="panel-hint" style="display:block; margin-top:4px;"></span>
                </div>
            </div>
        </div>
        </div>

        <!-- TIME sub-tab (ex-Tools → Time) -->
        <div class="routines-subtab-content" id="routines-time">
        <div class="grid-layout" style="grid-template-columns: 1fr; max-width: 600px;">
            <div class="card glass-card">
                <div class="card-header flex-header">
                    <h3>Anniversary / Memorial</h3>
                    <!-- R40 §4: Enabled is a header-right toggle. -->
                    <label class="switch" title="Enable anniversary display"><input type="checkbox" id="memorial-enabled" checked><span class="slider-round"></span></label>
                </div>
                <div class="card-body col gap-12">
                    <div class="row wrap gap-10">
                        <input type="text" id="memorial-title" class="text-input" maxlength="16" style="flex:1; min-width:120px;" placeholder="Title (e.g. Birthday)">
                    </div>
                    <div class="row wrap gap-8">
                        <span class="form-label text-12">Date</span>
                        <input type="number" id="memorial-month" class="text-input" min="1" max="12" value="1" style="width:60px;" title="month">
                        <span>/</span>
                        <input type="number" id="memorial-day" class="text-input" min="1" max="31" value="1" style="width:60px;" title="day">
                        <span class="form-label text-12" style="margin-left:8px;">at</span>
                        <input type="number" id="memorial-hour" class="text-input" min="0" max="23" value="9" style="width:60px;" title="hour">
                        <span>:</span>
                        <input type="number" id="memorial-min" class="text-input" min="0" max="59" value="0" style="width:60px;" title="minute">
                        <button id="memorial-save" class="glow-btn compact" style="margin-left:auto;">Save</button>
                    </div>
                </div>
            </div>
            <div class="card glass-card">
                <div class="card-header flex-header">
                    <h3>Alarms</h3>
                    <!-- R34 §4: table model — add/clear here, per-row remove, live writes. -->
                    <div class="row gap-8">
                        <button id="alarms-clear-btn" class="glow-btn compact" style="background:transparent; border:1px solid var(--secondary); color:var(--text-main); box-shadow:none;">Clear all</button>
                        <button id="alarms-add-btn" class="glow-btn compact">+ Add alarm</button>
                    </div>
                </div>
                <div class="card-body">
                    <p class="panel-hint" style="margin-top:0;">Changes are sent to the device immediately. Click a weekday cell to toggle it.</p>
                    <div id="alarms-list" class="alarms-list"></div>
                </div>
            </div>
        </div>
        </div>

        <!-- SLEEP SOUNDS sub-tab (AidSleep cloud sound library) -->
        <div class="routines-subtab-content" id="routines-sleep-sounds">
        <div class="grid-layout" style="grid-template-columns: 1fr; max-width: 600px;">
            <div class="card glass-card">
                <div class="card-header flex-header">
                    <h3>Sleep Sounds</h3>
                </div>
                <div class="card-body">
                    <p class="panel-hint" style="margin-top:0;">Browse Divoom's cloud-hosted sleep-sound library and play one on the device.</p>
                    <div class="tabs-row" role="tablist" id="aid-sleep-type-tabs" style="margin-bottom:12px;">
                        <button class="tab-btn active" data-sleep-type="0">Natural Sound</button>
                        <button class="tab-btn" data-sleep-type="1">White Noise</button>
                        <button class="tab-btn" data-sleep-type="2">Music</button>
                    </div>
                    <div id="aid-sleep-list" class="cloud-clock-list"></div>
                </div>
            </div>
        </div>
        </div>
    `;
