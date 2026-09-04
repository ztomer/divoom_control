/* sync_now.js — manual "run Auto-Sync now" trigger (Routines > Auto-Sync).
 * Pushes hot-channel content to every toggled sync target immediately
 * instead of waiting for the scheduled interval, with per-device progress
 * on the existing #sync-targets-list rows (see gallery.js's
 * renderSyncTargets). Mirrors gallery_hot.js's single-device update button:
 * disable while running, show status, re-enable when the daemon reports
 * every device done/error. */
document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("sync-now-btn");
    if (!btn) return;

    const PHASE_LABEL = {
        connecting: "Connecting…",
        syncing: "Syncing…",
        done: "Done",
        error: "Failed",
    };

    function rowStatusEl(address) {
        return document.querySelector(`.sync-now-row-status[data-addr="${CSS.escape(address)}"]`);
    }

    btn.addEventListener("click", () => {
        if (btn.disabled) return;
        if (!window.pywebview?.api?.sync_now) return;

        btn.disabled = true;
        btn.textContent = "Syncing…";
        document.querySelectorAll(".sync-now-row-status").forEach(el => { el.textContent = ""; });
        const statusEl = document.getElementById("sync-now-status");
        if (statusEl) statusEl.textContent = "Sync started…";

        window.pywebview.api.sync_now();
    });

    window.onSyncNowProgress = function(ev) {
        if (!ev || !ev.address) return;
        const row = rowStatusEl(ev.address);
        if (!row) return;
        if (ev.phase === "done") {
            row.textContent = `✓ ${ev.served ?? ""}`.trim();
            row.style.color = "var(--success, #22c55e)";
        } else if (ev.phase === "error") {
            row.textContent = `✗ ${ev.error || "failed"}`;
            row.title = ev.error || "";
            row.style.color = "var(--error, #ef4444)";
        } else {
            row.textContent = PHASE_LABEL[ev.phase] || ev.phase;
            row.style.color = "var(--text-muted)";
        }
    };

    window.onSyncNowComplete = function(summary) {
        btn.disabled = false;
        btn.textContent = "Sync Now";
        const statusEl = document.getElementById("sync-now-status");
        if (!statusEl || !summary) return;
        const { total = 0, ok = 0, failed = 0 } = summary;
        if (total === 0) {
            statusEl.textContent = "No devices selected — toggle one above.";
        } else {
            statusEl.textContent = `Synced ${ok}/${total} device${total > 1 ? "s" : ""}` + (failed ? `, ${failed} failed` : "");
        }
        window.showToast(
            failed ? `Sync Now: ${ok} synced, ${failed} failed` : `Sync Now: ${ok} device${ok !== 1 ? "s" : ""} synced`,
            failed && !ok ? "error" : "success", " BLE");
    };
});
