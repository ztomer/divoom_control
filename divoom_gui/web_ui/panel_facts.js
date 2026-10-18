/* panel_facts.js — what each panel IS, and how bright and loud it is, as the
   daemon says, by mac (P5.1).

   Before this the GUI guessed panel SIZE from the device name twice, and
   differently (one guesser in app_globals.js, another in spatial_stage.js),
   although device_status has carried each panel's model
   and resolution since P3.1. Brightness and volume were read once at startup
   with no mac, written with no mac, gated on the one app-wide appConnected
   flag, and the deck's per-panel brightness was a localStorage memory of what
   the slider last sent. The volume slider had two senders.

   Now: the facts are written onto discoveredDevices[i] -- the GUI's one
   per-panel record (the per-device rule) -- from get_panels, and the levels
   are read with get_panel_levels(mac) every time a panel is shown. The two
   sliders have ONE sender each, here, and it names the panel and refuses a
   panel that is not linked. */
(function () {
    "use strict";

    // The daemon's own starting size (divoomd/src/panel_model.rs
    // DEFAULT_PIXELS, the vendor app's DevicePixel16). Used ONLY where a
    // number is unavoidable and the daemon has not said; never shown as a fact.
    window.PANEL_FALLBACK_PIXELS = 16;

    const api = () => (window.pywebview && window.pywebview.api) || null;
    const parse = (raw) => {
        if (raw && typeof raw === "object") return raw;
        try { return JSON.parse(raw); } catch (_) { return null; }
    };
    const record = (mac) => (window.DivoomState.discoveredDevices || []).find(d => d.address === mac) || null;

    // ── What a panel is ──────────────────────────────────────────────────
    window.applyPanelFacts = function (panels) {
        (panels || []).forEach(p => {
            const dev = p && record(p.mac);
            if (!dev) return;
            dev.model = p.model || null;
            dev.width = Number.isInteger(p.width) ? p.width : null;
            dev.height = Number.isInteger(p.height) ? p.height : null;
            dev.features = p.features || null;
        });
    };

    let factsRequest = 0;
    window.refreshPanelFacts = function () {
        const a = api();
        if (!a || typeof a.get_panels !== "function") return Promise.resolve();
        const ticket = ++factsRequest;
        return Promise.resolve(a.get_panels()).then(raw => {
            const r = parse(raw);
            if (ticket !== factsRequest || !r || !r.ok) return;
            window.applyPanelFacts(r.panels);
            if (window.SpatialStage && window.SpatialStage.refresh) window.SpatialStage.refresh();
        }, () => {});
    };

    // The panel's pixel edge, or null when the daemon has not said.
    window.panelPixels = function (mac) {
        const dev = record(mac);
        return dev && Number.isInteger(dev.width) && dev.width > 0 ? dev.width : null;
    };

    // true / false from the vendor app's per-model switch; null when unknown.
    window.panelHasSpeaker = function (mac) {
        const dev = record(mac);
        return dev && dev.features && typeof dev.features.speaker === "boolean" ? dev.features.speaker : null;
    };

    // The bench's drawing of the panel's chassis, keyed by the daemon's MODEL
    // (the vendor app's DeviceTypeEnum), never by the name. Millimetres are
    // presentation only; the diode count is the daemon's.
    const CHASSIS = {
        ditoo:     { w_mm: 90,  h_mm: 114, screen_mm: 64 },
        timoo:     { w_mm: 82.5, h_mm: 90, screen_mm: 60 },
        tivoo_max: { w_mm: 184, h_mm: 163, screen_mm: 110 },
        pixoo:     { w_mm: 200, h_mm: 200, screen_mm: 158 },
        pixoo64:   { w_mm: 261, h_mm: 261, screen_mm: 210 },
        panel:     { w_mm: 120, h_mm: 120, screen_mm: 100 },
    };
    function chassisOf(model) {
        const m = String(model || "");
        if (/^(DITOO|Ditoo)/.test(m)) return "ditoo";
        if (m === "TIMOO") return "timoo";
        if (m === "TivooMax" || m === "TivoomMax32") return "tivoo_max";
        if (/^Pixoo64/.test(m)) return "pixoo64";
        if (m === "Pixoo" || m === "PIXOO_MAX") return "pixoo";
        return "panel";
    }
    window.panelEnclosure = function (dev) {
        const form = chassisOf(dev && dev.model);
        const px = (dev && Number.isInteger(dev.width) && dev.width > 0) ? dev.width : null;
        return Object.assign({ form, name: (dev && dev.model) || "Panel", pixels: px,
                               pw: px || window.PANEL_FALLBACK_PIXELS, ph: px || window.PANEL_FALLBACK_PIXELS },
                             CHASSIS[form]);
    };

    // ── How bright and loud it is ────────────────────────────────────────
    const UNKNOWN = "–";
    const els = () => ({
        b: document.getElementById("global-brightness-slider"),
        bVal: document.getElementById("global-brightness-value"),
        v: document.getElementById("appbar-volume-slider"),
        vVal: document.getElementById("appbar-volume-value"),
        vRow: document.getElementById("deck-volume-container"),
    });
    function updateBrightnessThumb(slider, v) {
        const g = Math.round(255 * (parseInt(v) || 0) / 100);
        slider.style.setProperty("--thumb-color", `rgb(${g},${g},${g})`);
    }
    function paint(levels) {
        const e = els();
        const b = levels && Number.isInteger(levels.brightness) ? levels.brightness : null;
        const v = levels && Number.isInteger(levels.volume) ? levels.volume : null;
        if (e.b) { e.b.dataset.state = b === null ? "unknown" : "known"; if (b !== null) { e.b.value = b; updateBrightnessThumb(e.b, b); } }
        if (e.bVal) e.bVal.textContent = b === null ? UNKNOWN : `${b}%`;
        if (e.v) { e.v.dataset.state = v === null ? "unknown" : "known"; if (v !== null) e.v.value = v; }
        if (e.vVal) e.vVal.textContent = v === null ? UNKNOWN : `${v}/15`;
    }

    let shownMac = null;
    let levelsRequest = 0;   // last-wins: a late reply for a panel you left is dropped
    const selected = () => shownMac;

    window.PanelLevels = {
        // Show `mac`: its speaker row, its last-read values while the fresh
        // read is in flight (unknown if never read), then what the panel says.
        // The bench repaints on every status event; only a CHANGE of panel
        // (or `reread`) goes to the radio, so a repaint is not a BLE read.
        show(mac, reread) {
            const changed = (mac || null) !== shownMac;
            shownMac = mac || null;
            const e = els();
            if (e.vRow) e.vRow.style.display = window.panelHasSpeaker(mac) === false ? "none" : "block";
            const dev = record(mac);
            paint(dev ? dev.levels : null);
            const a = api();
            if (!mac || !a || typeof a.get_panel_levels !== "function" || !(changed || reread)) return;
            const ticket = ++levelsRequest;
            Promise.resolve(a.get_panel_levels(mac)).then(raw => {
                const r = parse(raw);
                if (!r || !r.ok) return;
                const d = record(mac);
                if (d) d.levels = { brightness: r.brightness, volume: r.volume };
                if (ticket === levelsRequest && shownMac === mac) paint(d ? d.levels : r);
            }, () => {});
        },
        // One sender per slider: the panel it is for, once per gesture, only
        // while THAT panel is linked.
        write(kind, value) {
            const mac = selected();
            const a = api();
            if (!mac || !window.panelIsLinked(mac)) {
                window.showToast("That panel is not connected — connect it under Device Settings.", "error");
                return;
            }
            const call = kind === "brightness" ? "set_brightness" : "set_volume";
            if (!a || typeof a[call] !== "function") return;
            Promise.resolve(a[call](value, mac)).then(ok => {
                if (!ok) { window.showToast(`The panel did not take the ${kind}.`, "error"); return; }
                const d = record(mac);
                if (d) d.levels = Object.assign({}, d.levels, { [kind]: value });
                window.showToast(kind === "brightness" ? `Brightness set to ${value}%` : `Volume set to ${value}/15`, "success");
            });
        },
    };

    document.addEventListener("DOMContentLoaded", () => {
        const e = els();
        if (e.b) {
            e.b.addEventListener("input", ev => {
                e.b.dataset.state = "known";   // the user is setting it now
                if (e.bVal) e.bVal.textContent = `${ev.target.value}%`;
                updateBrightnessThumb(e.b, ev.target.value);
            });
            e.b.addEventListener("change", ev => window.PanelLevels.write("brightness", parseInt(ev.target.value)));
        }
        if (e.v) {
            e.v.addEventListener("input", ev => {
                e.v.dataset.state = "known";
                if (e.vVal) e.vVal.textContent = `${ev.target.value}/15`;
            });
            e.v.addEventListener("change", ev => window.PanelLevels.write("volume", parseInt(ev.target.value)));
        }
        const power = document.getElementById("deck-device-power");
        if (power && e.b) {
            power.addEventListener("click", () => {
                const next = parseInt(e.b.value) > 0 && e.b.dataset.state !== "unknown" ? 0 : 85;
                e.b.value = next;
                if (e.bVal) e.bVal.textContent = `${next}%`;
                window.PanelLevels.write("brightness", next);
            });
        }
        window.refreshPanelFacts();
    });
})();
