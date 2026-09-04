/* widgets_sysmon.js — the System Monitor card (split from widgets.js for the
   500-line rule).

   The readings and the 16x16 frame both come from the DAEMON's `sysmon` RPC —
   the same sample and the same renderer the device is pushed — so the card and
   the matrix cannot drift. The GUI used to sample psutil and draw its own PIL
   version, which is the second-implementation shape R67/C2 removed elsewhere.

   Exposes window.refreshSysmonPreview; widgets.js owns which card is selected
   and drives the Live (5s) timer. */
document.addEventListener("DOMContentLoaded", () => {

    // These readings come from the DAEMON -- the same source and the same
    // renderer the device is pushed -- so "cannot reach the daemon" is a state
    // this card has to be able to show. It used to `return` silently, which
    // left the previous numbers on screen: a dead daemon looked exactly like a
    // healthy idle machine, and the frame beside it stayed frozen on whatever
    // it last drew. An honest placeholder must never masquerade as live data.
    function showSysmonUnavailable(error) {
        const note = document.getElementById("sysmon-unavailable");
        if (note) {
            note.textContent = error
                ? `System stats unavailable — ${error}`
                : "System stats unavailable — the daemon is not responding.";
            note.style.display = "block";
        }
        // Blank the numbers rather than leaving stale ones dressed as current.
        for (const stat of ["cpu", "mem", "bat"]) {
            const row = document.querySelector(`.sysmon-bar-row[data-stat="${stat}"]`);
            if (!row) continue;
            const fill = row.querySelector(".sysmon-bar-fill");
            const text = row.querySelector(".sysmon-bar-value");
            if (fill) fill.style.width = "0%";
            if (text) text.textContent = "–";
        }
        const img = document.getElementById("sysmon-device-preview");
        if (img) { img.style.display = "none"; img.removeAttribute("src"); }
    }

    function clearSysmonUnavailable() {
        const note = document.getElementById("sysmon-unavailable");
        if (note) { note.style.display = "none"; note.textContent = ""; }
    }

    function refreshSysmonPreview() {
        if (!(window.pywebview && window.pywebview.api && window.pywebview.api.get_system_stats_preview)) return;
        window.pywebview.api.get_system_stats_preview(0).then(json => {
            try {
                const r = JSON.parse(json);
                if (!r.ok) { showSysmonUnavailable(r.error); return; }
                clearSysmonUnavailable();
                const s = r.stats || {};
                // Update the three labeled bars (Kare: bitmap clarity, color-coded)
                function setBar(stat, value) {
                    const row = document.querySelector(`.sysmon-bar-row[data-stat="${stat}"]`);
                    if (!row) return;
                    const fill = row.querySelector(".sysmon-bar-fill");
                    const text = row.querySelector(".sysmon-bar-value");
                    const pct = value != null ? Math.max(0, Math.min(100, value)) : 0;
                    if (fill) fill.style.width = `${pct}%`;
                    if (text) text.textContent = value != null ? `${pct}%` : "n/a";
                }
                setBar("cpu", s.cpu);
                setBar("mem", s.mem);
                setBar("bat", s.battery);
                const img = document.getElementById("sysmon-device-preview");
                if (img && r.preview) { img.src = r.preview; img.style.display = "inline-block"; }
                // R44 §7: when System Monitor is the active widget, mirror its
                // frame into the lower-left device screen overlay too.
                // R46 #2: mirror the sysmon frame as the device's last-active element.
                if (r.preview && selectedWidget === "sysmon") window.markActiveDeviceFrame?.(r.preview);
            } catch (e) { /* ignore */ }
        });
    }

    window.refreshSysmonPreview = refreshSysmonPreview;
});
