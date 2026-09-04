/* templates_device_settings.js — R40 §8: Device Settings sidebar section.

   One glass pane holding (in order): device name, clock format, temp unit,
   power mode, auto power-off, orientation, mirror, update time — then the
   Danger zone at the very bottom of the same pane. The clock/temp/power
   controls are segmented pills (each maps to the same boolean API as the old
   toggles); all element IDs are preserved so settings_features.js wiring is
   unchanged except the new pills. */
window.DivoomTemplates = window.DivoomTemplates || {};
window.DivoomTemplates.deviceSettings = `
        <div class="card glass-card" style="max-width:448px;">
            <div class="card-body" style="display:flex; flex-direction:column; gap:16px;">

                <!-- 1. Device name (R42 §8: controls right-aligned like the pills) -->
                <div class="ds-row" style="display:flex; gap:10px; align-items:center;">
                    <span class="form-label" style="font-size:12px;">Device name</span>
                    <input type="text" id="device-name-input" class="text-input" maxlength="24" style="width:150px; margin-left:auto;" placeholder="Read from device…">
                    <button id="device-name-save" class="glow-btn compact">Save</button>
                </div>

                <!-- R44 §3: the three 2-option pills share one fixed width and
                     equal-width buttons so their left+right edges line up. -->
                <!-- 2. Clock format -->
                <div class="ds-row" style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
                    <span class="form-label" style="font-size:12px;">Clock format</span>
                    <div class="tabs-row ds-pill-2" role="tablist" id="hour24-seg" data-api="set_hour_type" style="margin-right:0; margin-left:auto;">
                        <button class="tab-btn active" data-val="0">12-hour</button>
                        <button class="tab-btn" data-val="1">24-hour</button>
                    </div>
                </div>

                <!-- 3. Temperature unit -->
                <div class="ds-row" style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
                    <span class="form-label" style="font-size:12px;">Temperature</span>
                    <div class="tabs-row ds-pill-2" role="tablist" id="tempf-seg" data-api="set_temp_unit" style="margin-right:0; margin-left:auto;">
                        <button class="tab-btn active" data-val="0">Celsius</button>
                        <button class="tab-btn" data-val="1">Fahrenheit</button>
                    </div>
                </div>

                <!-- 4. Power mode -->
                <div class="ds-row" style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
                    <span class="form-label" style="font-size:12px;">Power mode</span>
                    <div class="tabs-row ds-pill-2" role="tablist" id="lowpower-seg" data-api="set_low_power" style="margin-right:0; margin-left:auto;">
                        <button class="tab-btn active" data-val="0">Normal</button>
                        <button class="tab-btn" data-val="1">Low power</button>
                    </div>
                </div>

                <!-- 5. Auto power-off (R42 §8: input+min+Save cluster right-aligned) -->
                <div class="ds-row" style="display:flex; gap:10px; align-items:center;">
                    <span class="form-label" style="font-size:12px;">Auto power-off</span>
                    <input type="number" id="auto-off-min" class="text-input" min="0" max="240" value="0" style="width:80px; margin-left:auto;" title="minutes (0 = off)">
                    <span style="font-size:12px; color:var(--text-muted);">min</span>
                    <button id="auto-off-save" class="glow-btn compact">Save</button>
                </div>

                <!-- 6. Orientation -->
                <div class="ds-row" style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
                    <span class="form-label" style="font-size:12px;">Orientation</span>
                    <div class="tabs-row" role="tablist" id="screen-dir-tabs" style="margin-right:0; margin-left:auto;">
                        <button class="tab-btn active" data-dir="0">0°</button>
                        <button class="tab-btn" data-dir="1">90°</button>
                        <button class="tab-btn" data-dir="2">180°</button>
                        <button class="tab-btn" data-dir="3">270°</button>
                    </div>
                </div>

                <!-- 7. Mirror -->
                <div class="ds-row" style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="form-label" style="font-size:12px;">Mirror / flip display</span>
                    <label class="switch" style="margin:0;"><input type="checkbox" id="screen-mirror-toggle"><span class="slider-round"></span></label>
                </div>

                <!-- 8. Update device time -->
                <button id="sync-time-btn" class="glow-btn" style="width:100%;">Update device time</button>

                <!-- 9-10. spacer -->
                <div style="flex:1; min-height:24px;"></div>

                <!-- 11. Danger zone (bottom of the same pane) -->
                <div class="danger-card" style="border-radius:8px; padding:14px; margin-top:4px;">
                    <h3 style="margin:0 0 8px;">Danger zone</h3>
                    <p class="panel-hint" style="margin:0 0 10px;">Factory reset wipes the device's stored configuration. This cannot be undone.</p>
                    <button id="factory-reset-btn" class="glow-btn danger">Factory reset device…</button>
                </div>
            </div>
        </div>
    `;
