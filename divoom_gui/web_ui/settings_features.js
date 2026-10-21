document.addEventListener("DOMContentLoaded", () => {
    // Every Tools action names ONE panel, resolved at the gesture (P5.7).
    const panel = () => window.ChannelSettings.mac(true);

    // ── 4. ROUTINES ──
    function saveSchedule() {
        const enabled = document.getElementById("routines-auto-sync-enabled")?.checked || false;
        // 86400 = a day. The "monthly best" content is refreshed almost daily
        // (the CATEGORY is the cloud's name for it, not a monthly cadence), so
        // a weekly push leaves the device up to a week behind.
        const interval = parseInt(document.querySelector("#routines-interval-tabs .tab-btn.active")?.getAttribute("data-interval")) || 86400;
        if (window.pywebview?.api?.save_hot_channel_config) {
            window.pywebview.api.save_hot_channel_config(JSON.stringify({ enabled, interval })).then(ok => {
                const st = document.getElementById("routines-auto-sync-status");
                if (st) st.textContent = ok ? (enabled ? "Auto-sync on" : "Auto-sync off") : "Failed to save";
            });
        }
    }

    window.loadRoutinesAutoSync = function() {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.get_hot_channel_config) {
            window.pywebview.api.get_hot_channel_config().then(json => {
                try {
                    const cfg = JSON.parse(json);
                    const en = document.getElementById("routines-auto-sync-enabled");
                    if (en) en.checked = !!cfg.enabled;
                    const iv = String(cfg.interval || 86400);
                    document.querySelectorAll("#routines-interval-tabs .tab-btn").forEach(b => {
                        b.classList.toggle("active", b.getAttribute("data-interval") === iv);
                    });
                } catch (e) { /* ignore */ }
            });
        }
        if (window.updateSyncTargetList) window.updateSyncTargetList();
    }
    document.getElementById("routines-auto-sync-enabled")?.addEventListener("change", saveSchedule);
    document.addEventListener("click", (e) => {
        const intervalBtn = e.target.closest("#routines-interval-tabs .tab-btn");
        if (intervalBtn) {
            document.querySelectorAll("#routines-interval-tabs .tab-btn").forEach(b => b.classList.remove("active"));
            intervalBtn.classList.add("active");
            saveSchedule();
        }
    });

    window.addEventListener("tab-changed", (e) => {
        if (e.detail && e.detail.tab === "routines") {
            setTimeout(window.loadRoutinesAutoSync, 0);
        }
    });

    // ── Sleep Aid ──
    const sleepVol = document.getElementById("sleep-volume");
    const sleepVolVal = document.getElementById("sleep-vol-val");
    if (sleepVol && sleepVolVal) sleepVol.addEventListener("input", () => { sleepVolVal.textContent = sleepVol.value; });
    document.addEventListener("click", (e) => {
        if (e.target.closest("#sleep-start-btn")) {
            const mac = panel();
            if (!mac) return;
            const m = parseInt(document.getElementById("sleep-minutes")?.value) || 30;
            const c = document.getElementById("sleep-color")?.value || "#2040ff";
            const v = parseInt(document.getElementById("sleep-volume")?.value) || 10;
            window.pywebview?.api?.start_sleep?.(mac, m, c, v).then(r =>
                window.showToast(r ? "Sleep started" : "Failed to start sleep", r ? "success" : "error", " BLE"));
        } else if (e.target.closest("#sleep-stop-btn")) {
            const mac = panel();
            if (!mac) return;
            window.pywebview?.api?.stop_sleep?.(mac).then(r =>
                window.showToast(r ? "Sleep stopped" : "Failed", r ? "success" : "error", " BLE"));
        }
    });

    // ── Round 7: Tools (timer / countdown / noise) ─────────────────────
    document.addEventListener("click", (e) => {
        const timerBtn = e.target.closest(".tool-timer-btn");
        if (timerBtn) {
            const mac = panel();
            if (!mac) return;
            window.pywebview?.api?.set_timer?.(mac, timerBtn.dataset.action).then(r =>
                window.showToast(r ? `Stopwatch ${timerBtn.dataset.action}` : "Failed", r ? "success" : "error", " BLE"));
            return;
        }
        if (e.target.closest("#countdown-start-btn") || e.target.closest("#countdown-stop-btn")) {
            const mac = panel();
            if (!mac) return;
            const action = e.target.closest("#countdown-stop-btn") ? "stop" : "start";
            const mm = parseInt(document.getElementById("countdown-min")?.value) || 0;
            const ss = parseInt(document.getElementById("countdown-sec")?.value) || 0;
            window.pywebview?.api?.set_countdown?.(mac, action, mm, ss).then(r =>
                window.showToast(r ? `Countdown ${action}` : "Failed", r ? "success" : "error", " BLE"));
            return;
        }
        if (e.target.closest("#noise-start-btn") || e.target.closest("#noise-stop-btn")) {
            const mac = panel();
            if (!mac) return;
            const action = e.target.closest("#noise-stop-btn") ? "stop" : "start";
            window.pywebview?.api?.set_noise?.(mac, action).then(r =>
                window.showToast(r ? `Noise meter ${action}` : "Failed", r ? "success" : "error", " BLE"));
        }
    });

    // ── Round 8: Tools sub-tab nav (R15 §1+§7: `.tools-subtab-btn` → `.tab-btn[data-tools-tab]`) ──
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn[data-tools-tab]");
        if (!btn) return;
        document.querySelectorAll(".tab-btn[data-tools-tab]").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tools-subtab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        const target = document.getElementById(btn.getAttribute("data-tools-tab"));
        if (target) target.classList.add("active");
    });

    // ── R33: Routines sub-tab nav ──
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn[data-routines-tab]");
        if (!btn) return;
        document.querySelectorAll(".tab-btn[data-routines-tab]").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".routines-subtab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        const target = document.getElementById(btn.getAttribute("data-routines-tab"));
        if (target) target.classList.add("active");
        if (btn.getAttribute("data-routines-tab") === "routines-sleep-sounds" && window.loadAidSleepList) {
            setTimeout(window.loadAidSleepList, 50);
        }
    });

    // ── Pixel Art sub-tab nav ──
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn[data-pixel-tab]");
        if (!btn) return;
        document.querySelectorAll(".tab-btn[data-pixel-tab]").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".pixel-subtab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        const target = document.getElementById(btn.getAttribute("data-pixel-tab"));
        if (target) target.classList.add("active");
        // Refresh gallery/hot preview when switching to those sub-tabs
        if (btn.getAttribute("data-pixel-tab") === "pixel-gallery" && window.loadGallery) {
            setTimeout(window.loadGallery, 50);
        } else if (btn.getAttribute("data-pixel-tab") === "pixel-hot-channel" && window.loadHotPreview) {
            setTimeout(window.loadHotPreview, 50);
        } else if (btn.getAttribute("data-pixel-tab") === "pixel-playlists" && window.loadPlaylists) {
            setTimeout(window.loadPlaylists, 50);
        } else if (btn.getAttribute("data-pixel-tab") === "pixel-photo-albums" && window.loadPhotoAlbums) {
            setTimeout(window.loadPhotoAlbums, 50);
        } else if (btn.getAttribute("data-pixel-tab") === "pixel-custom-art") {
            // R42 §3: the loader is loadCustomArtCacheGrid (loadCachedGallery
            // never existed) — without it the library showed "No cached gallery
            // files" even with a full cache.
            // R45 #1: also (re)build the slot grid — it can be missing if init
            // raced the template injection at startup.
            if (window.buildCustomArtSlots) setTimeout(window.buildCustomArtSlots, 30);
            if (window.loadCustomArtCacheGrid) setTimeout(window.loadCustomArtCacheGrid, 50);
            if (window.customArtSyncLibrary) setTimeout(window.customArtSyncLibrary, 100);
        }
    });

    // ── Round 8: Device settings / weather / memorial / FM ─────────────
    function api() { return window.pywebview && window.pywebview.api; }
    function toast(r, ok, fail) { window.showToast(r ? ok : (fail || "Failed"), r ? "success" : "error", " BLE"); }

    const wireToggle = (id, fn) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", () => {
            const mac = panel();
            if (mac) api()?.[fn]?.(mac, el.checked).then(r => toast(r, "Saved"));
        });
    };
    wireToggle("screen-mirror-toggle", "set_screen_mirror");

    // R40 §8: clock/temp/power are now segmented pills (.tabs-row with
    // data-api on the container + data-val 0/1 on the buttons). Each maps to
    // the same boolean API the old toggles called.
    document.addEventListener("click", (e) => {
        const btn = e.target.closest("#hour24-seg .tab-btn, #tempf-seg .tab-btn, #lowpower-seg .tab-btn");
        if (!btn) return;
        const seg = btn.parentElement;
        seg.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const fn = seg.getAttribute("data-api");
        const on = btn.getAttribute("data-val") === "1";
        const mac = fn ? panel() : null;
        if (mac) api()?.[fn]?.(mac, on).then(r => toast(r, "Saved"));
    });

    // Display orientation (0-3 = 0/90/180/270°) via tab selector.
    document.addEventListener("click", (e) => {
        const dirBtn = e.target.closest("#screen-dir-tabs .tab-btn");
        if (!dirBtn) return;
        document.querySelectorAll("#screen-dir-tabs .tab-btn").forEach(b => b.classList.remove("active"));
        dirBtn.classList.add("active");
        const mac = panel();
        if (mac) api()?.set_screen_dir?.(mac, parseInt(dirBtn.getAttribute("data-dir")) || 0)
            .then(r => toast(r, "Orientation set"));
    });

    document.addEventListener("click", (e) => {
        if (e.target.closest("#sync-time-btn")) {
            const mac = panel();
            if (mac) api()?.sync_time?.(mac).then(r => toast(r, "Time synced"));
        } else if (e.target.closest("#device-name-save")) {
            const name = document.getElementById("device-name-input")?.value.trim();
            if (!name) { window.showToast("Enter a name", "error"); return; }
            const mac = panel();
            if (mac) {
                // The reply renames the panel the click named, wherever the
                // selection is by then (it renamed the one shown THEN).
                api()?.set_device_name?.(mac, name).then(r => {
                    toast(r, "Name saved");
                    if (r) renamed(mac, name);
                });
            }
        } else if (e.target.closest("#auto-off-save")) {
            const m = parseInt(document.getElementById("auto-off-min")?.value) || 0;
            const mac = panel();
            if (mac) api()?.set_auto_power_off?.(mac, m).then(r => toast(r, m ? `Auto-off ${m}min` : "Auto-off disabled"));
        } else if (e.target.closest("#memorial-save")) {
            const mac = panel();
            if (!mac) return;
            const enabled = document.getElementById("memorial-enabled")?.checked;
            const title = document.getElementById("memorial-title")?.value.trim() || "";
            const mo = parseInt(document.getElementById("memorial-month")?.value) || 1;
            const da = parseInt(document.getElementById("memorial-day")?.value) || 1;
            const hh = parseInt(document.getElementById("memorial-hour")?.value) || 0;
            const mi = parseInt(document.getElementById("memorial-min")?.value) || 0;
            api()?.set_memorial?.(mac, 0, enabled, mo, da, hh, mi, title).then(r => toast(r, "Anniversary saved"));
        } else if (e.target.closest("#factory-reset-btn")) {
            const mac = panel();
            if (!mac) return;
            // Double-confirm: a dialog, then a typed token, then the bridge also
            // requires the literal "RESET" string before it sends anything.
            if (!window.confirm("Factory-reset this device? This wipes its stored config and cannot be undone.")) return;
            const token = window.prompt('This is irreversible. Type RESET (all caps) to confirm:');
            if (token !== "RESET") { window.showToast("Factory reset cancelled", "error"); return; }
            api()?.factory_reset?.(mac, "RESET").then(r => toast(r, "Device factory-reset"));
        } else if (e.target.closest("#notif-send")) {
            const mac = panel();
            if (!mac) return;
            const t = parseInt(document.getElementById("notif-app-select")?.value) || 7;
            const txt = document.getElementById("notif-text")?.value.trim() || "";
            api()?.send_notification?.(mac, t, txt).then(r => toast(r, "Notification sent"));
        }
    });

    // FM radio — frequency (MHz → MHz×10) + presets.
    function tuneFM(mhz) {
        const x10 = Math.round(parseFloat(mhz) * 10);
        const mac = panel();
        if (mac) api()?.set_fm_frequency?.(mac, x10).then(r => toast(r, `Tuned ${mhz} MHz`));
    }
    document.addEventListener("click", (e) => {
        if (e.target.closest("#fm-tune-btn")) {
            tuneFM(document.getElementById("fm-freq")?.value || "101.5");
        } else {
            const preset = e.target.closest(".fm-preset");
            if (preset) {
                const f = preset.getAttribute("data-freq");
                const inp = document.getElementById("fm-freq"); if (inp) inp.value = f;
                tuneFM(f);
            }
        }
    });

    // ── Device Name Auto-load ──
    // The panel's name as IT reports it, for the panel the read was asked
    // about (P5.7): the reply used to land on whichever panel the banner
    // showed when it came back.
    function renamed(mac, name) {
        let changed = false;
        (window.DivoomState.discoveredDevices || []).forEach(d => {
            if (d.address === mac && d.name !== name) { d.name = name; changed = true; }
        });
        if (!changed) return;
        if (window._activeDeviceMac() === mac) {
            const bannerName = document.getElementById("banner-device-name");
            if (bannerName) bannerName.textContent = name;
            if (window._updateDeviceLabel) window._updateDeviceLabel(name);
        }
        if (window.updateDeviceSelectorDropdown) window.updateDeviceSelectorDropdown();
        if (window.populateDeviceSelectors) window.populateDeviceSelectors(window.DivoomState.discoveredDevices);
    }
    window.loadDeviceName = function() {
        const inp = document.getElementById("device-name-input");
        const mac = window.ChannelSettings.selected()?.mac;
        if (!inp || !mac || mac === "MatrixWall") return;
        Promise.resolve(window.pywebview?.api?.get_device_name?.(mac)).then(name => {
            if (name === null || name === undefined) return;
            if (window.ChannelSettings.selected()?.mac === mac) inp.value = name;
            renamed(mac, name);
        }).catch(() => {});
    };

    window.addEventListener("tab-changed", (e) => {
        if (e.detail && e.detail.tab === "settings") {
            setTimeout(window.loadDeviceName, 50);
        }
    });
});
