/* aid_sleep.js — browse Divoom's cloud AidSleep sound library
   (AidSleep/GetAllList) and play one on the device (AidSleep/Play, BLE-only,
   no cloud round-trip). No thumbnails from this API — a plain text list,
   like cloud_clock_faces.js's clock-face browser. */

document.addEventListener("DOMContentLoaded", () => {
    const typeTabs = document.getElementById("aid-sleep-type-tabs");
    const listEl = document.getElementById("aid-sleep-list");
    if (!typeTabs || !listEl) return;

    let currentType = 0;

    function renderSleepList(sounds) {
        if (!sounds || sounds.length === 0) {
            listEl.innerHTML = `<div class="empty-list">No sleep sounds in this category.</div>`;
            return;
        }
        listEl.innerHTML = sounds.map(s => `
            <div class="cloud-clock-row" data-sleep-id="${s.SleepId}">
                <span class="cloud-clock-name">${s.Name}</span>
                <button type="button" class="cloud-clock-apply-btn">Play</button>
            </div>
        `).join("");
    }

    function loadAidSleepList() {
        if (!window.pywebview?.api?.get_aid_sleep_list) return;
        listEl.innerHTML = `<div class="empty-list">Loading…</div>`;
        window.pywebview.api.get_aid_sleep_list(currentType).then(reply => {
            const sounds = window.DivoomCloud.unwrap(reply, listEl, "No sleep sounds.");
            if (sounds === null) return;
            renderSleepList(sounds);
        }).catch(() => {
            listEl.innerHTML = `<div class="empty-list">Failed to load sleep sounds.</div>`;
        });
    }
    window.loadAidSleepList = loadAidSleepList;

    typeTabs.addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn[data-sleep-type]");
        if (!btn) return;
        typeTabs.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentType = parseInt(btn.getAttribute("data-sleep-type"));
        loadAidSleepList();
    });

    listEl.addEventListener("click", (e) => {
        const btn = e.target.closest(".cloud-clock-apply-btn");
        if (!btn) return;
        if (!window.requireDevice || !window.requireDevice()) return;
        const row = btn.closest(".cloud-clock-row");
        const sleepId = parseInt(row?.getAttribute("data-sleep-id"));
        if (!sleepId || !window.pywebview?.api?.play_aid_sleep) return;
        btn.disabled = true;
        window.pywebview.api.play_aid_sleep(sleepId, currentType).then(res => {
            btn.disabled = false;
            window.showToast(res ? "Playing on device" : "Failed to play sound", res ? "success" : "error", " BLE");
            if (res && window.setDeviceActivity) {
                window.setDeviceActivity(window._activeDeviceMac(), "aid_sleep", { sleepId, sleepType: currentType });
            }
        }).catch(() => {
            btn.disabled = false;
            window.showToast("Failed to play sound", "error");
        });
    });
});
