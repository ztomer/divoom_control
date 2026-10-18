/* display_write.js — what a display write did, said once (P6.4).

   Every write that changes what a display shows (channel, clock, VJ,
   visualizer, ambient light, text, scoreboard, brightness, volume, a wall
   image) answers with one shape, made by `write_outcome` in
   `divoom_gui/api/__init__.py`:

       {success: true}
       {success: false, error, failed: {mac: reason}, degraded: [mac]}

   On a wall, `failed` names each panel whose write failed and why, and
   `degraded` each slot with no panel (P6.3, `divoomd/src/wall/outcome.rs`).
   Each of these writes used to answer a bare true/false, so on the wall the
   toast said "Failed to switch channel" and the daemon's reason, naming the
   panel, reached only the log. This is the one place that turns the reply
   into the toast, so no write can drop the panel's name again. */
(function () {
    "use strict";

    const esc = (t) => String(t).replace(/[&<>"']/g, c => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    /* The name the bench shows for `mac`: its wall slot's, else the panel's
       own, else the mac. */
    function benchName(mac, slots) {
        const key = String(mac).toLowerCase();
        const pick = (obj) => {
            const k = Object.keys(obj || {}).find(x => x.toLowerCase() === key);
            return k && obj[k] && obj[k].name;
        };
        const st = window.DivoomState || {};
        const dev = (st.discoveredDevices || []).find(d => String(d.address).toLowerCase() === key);
        return pick(slots) || pick(st.assignedSlots) || (dev && dev.name) || mac;
    }

    function succeeded(res) {
        return !!(res && typeof res === "object" && res.success === true);
    }

    /* Each panel the reply names, by its bench name, and why; "" when it
       names none. `what` is what the panel did not take ("it", "the image"). */
    function panelsText(res, what, slots) {
        if (!res || typeof res !== "object") return "";
        const failed = res.failed || {};
        const parts = Object.keys(failed)
            .map(mac => `${esc(benchName(mac, slots))} did not take ${what} (${esc(failed[mac])}).`)
            .concat((res.degraded || []).map(mac => `${esc(benchName(mac, slots))} is not connected.`));
        return parts.join(" ");
    }

    /* Toast what the write did; returns whether it succeeded. `opts.done` and
       `opts.failed` are the two messages; `opts.what` is what a panel took
       (default "it"), `opts.slots` the wall slots the write used. */
    function report(res, opts) {
        const o = opts || {};
        if (succeeded(res)) {
            window.showToast(o.done, "success", o.transport === undefined ? " BLE" : o.transport);
            return true;
        }
        const named = panelsText(res, o.what || "it", o.slots);
        const why = named || (res && typeof res === "object" && res.error ? esc(res.error) : "");
        window.showToast(why ? `${o.failed}: ${why}` : o.failed, "error");
        return false;
    }

    window.DisplayWrite = { report, succeeded, panelsText, benchName };
})();
