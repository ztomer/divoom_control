/* sync_now.js — manual "run Auto-Sync now" trigger (Schedule > Auto-Sync).
 * Runs the hot-channel update on every toggled panel now instead of at the
 * scheduled time. Each Auto-Sync row shows that panel's verdict line, the
 * SHORT form of the line under the Hot tab's Update button (U.5,
 * hot_verdict.js): the daemon's record of the panel's newest run by any path
 * -- this button, the Update button, the daily schedule -- failures included.
 * While a run is under way the row says "→ Checking now (2 of 4)"; when it
 * ends the row re-reads the record. Nothing here is kept apart from that
 * record, so nothing vanishes on the next render. */
document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("sync-now-btn");
    if (!btn) return;

    function rowStatusEl(address) {
        return document.querySelector(`.sync-now-row-status[data-addr="${CSS.escape(address)}"]`);
    }

    // Paint one row (or every row) from the panel's record.
    function paintRow(address) {
        const el = rowStatusEl(address);
        if (el && window.HotVerdict) window.HotVerdict.render(el, window.HotVerdict.get(address), { short: true });
    }
    function paintAll() {
        document.querySelectorAll(".sync-now-row-status").forEach(el => paintRow(el.dataset.addr));
    }
    window.paintSyncRows = function () {
        if (window.HotVerdict) window.HotVerdict.refreshAll().then(paintAll); else paintAll();
    };
    window.addEventListener("divoom:hot-verdict", (e) => {
        if (e.detail && e.detail.mac && !running.has(e.detail.mac)) paintRow(e.detail.mac);
    });

    const running = new Set();

    btn.addEventListener("click", () => {
        if (btn.disabled) return;
        if (!window.pywebview?.api?.sync_now) return;
        btn.disabled = true;
        btn.textContent = "Syncing…";
        window.pywebview.api.sync_now();
    });

    window.onSyncNowProgress = function(ev) {
        if (!ev || !ev.address) return;
        const row = rowStatusEl(ev.address);
        if (ev.phase === "checking") {
            running.add(ev.address);
            if (row && window.HotVerdict) {
                window.HotVerdict.renderChecking(row, ev.total > 1 ? `${ev.index} of ${ev.total}` : "");
            }
        } else if (ev.phase === "finished") {
            running.delete(ev.address);
            if (window.HotVerdict) window.HotVerdict.refresh(ev.address).then(() => paintRow(ev.address));
        }
    };

    window.onSyncNowComplete = function() {
        running.clear();
        btn.disabled = false;
        btn.textContent = "Sync Now";
        window.paintSyncRows();
    };
});
