/* alarms_editor.js — R34 §4: Alarms weekday table (split from settings_features.js
   to keep it under the 500-LOC rule). Renders into #alarms-list in the Routines
   panel; all handlers are document-delegated so render order doesn't matter. */
document.addEventListener("DOMContentLoaded", () => {
    // ── R34 §4: Alarms editor — weekday table, live writes ─────────────
    // One weekday header row (no per-row day labels), day-cell toggles, only
    // non-empty alarms shown, +Add / Clear all / per-row remove, and IMMEDIATE
    // debounced writes (no Save button).
    const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const ALARM_SLOTS = 10;
    const ALARM_WRITE_DEBOUNCE_MS = 500;   // hour-spinner clicks ≠ N BLE writes
    let alarmState = [];                   // local 10-slot model
    const alarmWriteTimers = {};

    // Empty = never configured: disabled AND no weekdays. (An enabled alarm
    // with week=0 is a one-shot the user explicitly added — keep it visible.)
    function alarmIsEmpty(a) { return !a || (!a.status && !(a.week || 0)); }

    function normalizeAlarms(alarms) {
        alarmState = [];
        for (let i = 0; i < ALARM_SLOTS; i++) {
            const a = (alarms && alarms[i]) || {};
            alarmState.push({ status: a.status ? 1 : 0, hour: a.hour ?? 7,
                              minute: a.minute ?? 0, week: a.week || 0 });
        }
    }

    function renderAlarmsTable() {
        const list = document.getElementById("alarms-list");
        if (!list) return;
        list.innerHTML = "";
        const table = document.createElement("div");
        table.className = "alarms-table";
        const head = document.createElement("div");
        head.className = "alarms-table-row alarms-table-head";
        head.innerHTML = `<span>On</span><span>Time</span>` +
            WEEKDAYS.map(d => `<span>${d}</span>`).join("") + `<span></span>`;
        table.appendChild(head);
        let shown = 0;
        alarmState.forEach((a, i) => {
            if (alarmIsEmpty(a)) return;
            shown++;
            const row = document.createElement("div");
            row.className = "alarms-table-row alarm-row";
            row.dataset.index = i;
            const dayCells = WEEKDAYS.map((d, b) => {
                const on = (a.week || 0) & (1 << b);
                return `<button class="alarm-day-cell${on ? " active" : ""}" data-bit="${b}" title="${d}" aria-pressed="${on ? "true" : "false"}"></button>`;
            }).join("");
            row.innerHTML =
                `<label class="switch alarm-switch" title="Enable">` +
                `<input type="checkbox" class="alarm-enabled" ${a.status ? "checked" : ""}>` +
                `<span class="slider-round"></span></label>` +
                `<span class="alarm-time">` +
                `<input type="number" class="alarm-hour text-input" min="0" max="23" value="${a.hour}">` +
                `<span>:</span>` +
                `<input type="number" class="alarm-min text-input" min="0" max="59" value="${String(a.minute).padStart(2, "0")}">` +
                `</span>` +
                dayCells +
                `<button class="alarm-remove" title="Remove this alarm">×</button>`;
            table.appendChild(row);
        });
        if (!shown) {
            const empty = document.createElement("div");
            empty.className = "empty-list";
            empty.style.padding = "10px 0";
            empty.textContent = "No alarms set — click “+ Add alarm”.";
            table.appendChild(empty);
        }
        list.appendChild(table);
        const addBtn = document.getElementById("alarms-add-btn");
        if (addBtn) addBtn.disabled = !alarmState.some(alarmIsEmpty);
    }

    function writeAlarm(i, label) {
        const a = alarmState[i];
        window.pywebview?.api?.set_alarm?.(i, !!a.status, a.hour, a.minute, a.week).then(res => {
            if (!res) window.showToast(`Failed to ${label || "update alarm"}`, "error", " BLE");
        });
    }
    function queueAlarmWrite(i) {
        clearTimeout(alarmWriteTimers[i]);
        alarmWriteTimers[i] = setTimeout(() => writeAlarm(i), ALARM_WRITE_DEBOUNCE_MS);
    }

    function fetchAlarms() {
        window.pywebview?.api?.get_alarms?.().then(json => {
            let parsed = [];
            try { parsed = JSON.parse(json); } catch (e) { /* render empty */ }
            normalizeAlarms(parsed);
            renderAlarmsTable();
        });
    }
    function ensureAlarms() {
        if (!document.querySelector("#alarms-list .alarms-table")) {
            normalizeAlarms([]);
            renderAlarmsTable();
        }
    }

    window.addEventListener("tab-changed", (e) => {
        if (e.detail && e.detail.tab === "routines") {
            setTimeout(ensureAlarms, 0);
            setTimeout(fetchAlarms, 50);
        }
    });
    // Also fetch alarms when the Time sub-tab is clicked within Routines.
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn[data-routines-tab]");
        if (btn && btn.getAttribute("data-routines-tab") === "routines-time") {
            setTimeout(fetchAlarms, 50);
        }
    });

    // Row interactions (delegated): toggle/day/time → debounced write; × → clear slot.
    document.addEventListener("click", (e) => {
        const dayCell = e.target.closest("#alarms-list .alarm-day-cell");
        if (dayCell) {
            if (window.requireDevice && !window.requireDevice()) return;
            const i = parseInt(dayCell.closest(".alarm-row").dataset.index);
            alarmState[i].week ^= (1 << parseInt(dayCell.dataset.bit));
            dayCell.classList.toggle("active");
            dayCell.setAttribute("aria-pressed", dayCell.classList.contains("active") ? "true" : "false");
            queueAlarmWrite(i);
            return;
        }
        const removeBtn = e.target.closest("#alarms-list .alarm-remove");
        if (removeBtn) {
            if (window.requireDevice && !window.requireDevice()) return;
            const i = parseInt(removeBtn.closest(".alarm-row").dataset.index);
            clearTimeout(alarmWriteTimers[i]);
            alarmState[i] = { status: 0, hour: 0, minute: 0, week: 0 };
            writeAlarm(i, "remove alarm");
            renderAlarmsTable();
        }
    });
    document.addEventListener("change", (e) => {
        const row = e.target.closest("#alarms-list .alarm-row");
        if (!row) return;
        if (window.requireDevice && !window.requireDevice()) return;
        const i = parseInt(row.dataset.index);
        if (e.target.classList.contains("alarm-enabled")) alarmState[i].status = e.target.checked ? 1 : 0;
        else if (e.target.classList.contains("alarm-hour")) alarmState[i].hour = Math.min(23, Math.max(0, parseInt(e.target.value) || 0));
        else if (e.target.classList.contains("alarm-min")) alarmState[i].minute = Math.min(59, Math.max(0, parseInt(e.target.value) || 0));
        else return;
        queueAlarmWrite(i);
    });

    // + Add alarm: first free slot, sane defaults, written immediately.
    document.addEventListener("click", (e) => {
        if (!e.target.closest("#alarms-add-btn")) return;
        if (window.requireDevice && !window.requireDevice()) return;
        const i = alarmState.findIndex(alarmIsEmpty);
        if (i === -1) { window.showToast("All 10 alarm slots are in use", "error"); return; }
        alarmState[i] = { status: 1, hour: 7, minute: 0, week: 0 };
        writeAlarm(i, "add alarm");
        renderAlarmsTable();
    });

    // Clear all: zero every slot on the device and empty the table.
    document.addEventListener("click", (e) => {
        if (!e.target.closest("#alarms-clear-btn")) return;
        if (window.requireDevice && !window.requireDevice()) return;
        for (let i = 0; i < ALARM_SLOTS; i++) {
            clearTimeout(alarmWriteTimers[i]);
            if (alarmIsEmpty(alarmState[i])) continue;
            alarmState[i] = { status: 0, hour: 0, minute: 0, week: 0 };
            writeAlarm(i, "clear alarm");
        }
        renderAlarmsTable();
        window.showToast("All alarms cleared", "success", " BLE");
    });
});
