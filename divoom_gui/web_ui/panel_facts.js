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
   panel that is not linked.

   With the wall chosen as the display the sliders are the WALL's (P6.6): one
   gesture is one `set_brightness` / `set_volume` naming `MatrixWall`, which
   the daemon sends to every slot, and the toast names each slot that did not
   take it (`web_ui/display_write.js`). The deck showed the bench's panel
   instead, so a wall gesture changed one panel of it. Volume is offered only
   when every slot's panel has a speaker, as the daemon reports it. */
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
            // Which product it is and how big (P3.4): the daemon's table, not
            // a second one here.
            dev.chassis = p.chassis || null;
            dev.screens = Array.isArray(p.screens) ? p.screens : null;
            // Why the daemon will not make it a wall slot, or null (P6.1).
            dev.wallRefusal = typeof p.wall_refusal === "string" ? p.wall_refusal : null;
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
            // The channel cards follow the panel's abilities (P3.4), and the
            // abilities arrive with the facts -- so the cards are told again
            // when they do, not only when a panel connects.
            if (window.updateChannelButtonsVisibility) {
                const mac = (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null;
                window.updateChannelButtonsVisibility(mac);
            }
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
        return window.panelHasFeature(mac, "speaker");
    };

    // The same, for any feature the daemon reports: the vendor app's own
    // per-model switch. null means the daemon has not described the panel.
    window.panelHasFeature = function (mac, key) {
        const dev = record(mac);
        return dev && dev.features && typeof dev.features[key] === "boolean" ? dev.features[key] : null;
    };

    // The screens the app offers this panel (P3.4): the vendor app's own home
    // list for its model. null when the daemon has not described the panel.
    window.panelHasScreen = function (mac, screen) {
        const dev = record(mac);
        return dev && Array.isArray(dev.screens) ? dev.screens.includes(screen) : null;
    };

    // ── The wall ─────────────────────────────────────────────────────────
    const WALL = "MatrixWall";
    const wallSlots = () => (window.DivoomState && window.DivoomState.assignedSlots) || {};

    // true only when every slot's panel has a speaker by the daemon's word
    // (`features.speaker`); a slot it has not described is not assumed to.
    window.wallHasSpeaker = function () {
        const macs = Object.keys(wallSlots());
        return macs.length > 0 && macs.every(m => window.panelHasSpeaker(m) === true);
    };

    // The wall's level of `kind`: the value every slot last reported or took,
    // when they all agree; null (shown as unknown) when they do not or one
    // has never said. No read is sent: the wall has no level of its own.
    function wallLevel(kind) {
        const vals = Object.keys(wallSlots()).map(m => {
            const d = record(m);
            return d && d.levels ? d.levels[kind] : null;
        });
        return vals.length > 0 && vals.every(v => Number.isInteger(v) && v === vals[0]) ? vals[0] : null;
    }
    const wallLevels = () => ({ brightness: wallLevel("brightness"), volume: wallLevel("volume") });

    // The bench's drawing of the panel's chassis: the daemon's table (P3.4),
    // which says which product the panel is and how big it is. This file used
    // to keep its own table and decide the family from the model with its own
    // regexes, so the bench drew the GUI's idea of a panel while the daemon
    // said something else about the same panel.
    //
    // The generic chassis is the fallback for a panel the daemon has not
    // described -- the same row the daemon's table starts with
    // (divoomd/src/panel_model.rs, FAMILIES). It is the only number kept
    // here, and `tests/test_panel_model_parity.py` holds it to the daemon's.
    const GENERIC_CHASSIS = { w_mm: 120, h_mm: 120, screen_mm: 100 };
    window.panelEnclosure = function (dev) {
        const c = (dev && dev.chassis) || null;
        const px = (dev && Number.isInteger(dev.width) && dev.width > 0) ? dev.width : null;
        return Object.assign({ form: (c && c.family) || "panel", name: (dev && dev.model) || "Panel", pixels: px,
                               pw: px || window.PANEL_FALLBACK_PIXELS, ph: px || window.PANEL_FALLBACK_PIXELS },
                              c ? { w_mm: c.w_mm, h_mm: c.h_mm, screen_mm: c.screen_mm } : GENERIC_CHASSIS);
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
    // A slider the pointer is holding is the user's: a repaint (the bench
    // refreshes on every scan result) must not move it under their finger.
    const held = (el) => { try { return el.matches(":active"); } catch (_) { return false; } };
    function paint(levels) {
        const e = els();
        const b = levels && Number.isInteger(levels.brightness) ? levels.brightness : null;
        const v = levels && Number.isInteger(levels.volume) ? levels.volume : null;
        if (!(e.b && held(e.b))) {
            if (e.b) { e.b.dataset.state = b === null ? "unknown" : "known"; if (b !== null) { e.b.value = b; updateBrightnessThumb(e.b, b); } }
            if (e.bVal) e.bVal.textContent = b === null ? UNKNOWN : `${b}%`;
        }
        if (e.v && held(e.v)) return;
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
            if (mac === WALL) {
                if (e.vRow) e.vRow.style.display = window.wallHasSpeaker() ? "block" : "none";
                paint(wallLevels());
                return;
            }
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
            if (mac === WALL) { writeWall(kind, value); return; }
            const a = api();
            if (!mac || !window.panelIsLinked(mac)) {
                window.showToast("That panel is not connected — connect it under Device Settings.", "error");
                return;
            }
            const call = kind === "brightness" ? "set_brightness" : "set_volume";
            if (!a || typeof a[call] !== "function") return;
            Promise.resolve(a[call](mac, value)).then(res => {
                const done = kind === "brightness" ? `Brightness set to ${value}%` : `Volume set to ${value}/15`;
                if (!window.DisplayWrite.report(res, { done, failed: `The panel did not take the ${kind}`, transport: null })) return;
                const d = record(mac);
                if (d) d.levels = Object.assign({}, d.levels, { [kind]: value });
            });
        },
    };

    // One wall level write: every slot through the daemon's wall, the toast
    // naming each slot that did not take it. A slot that took it now has
    // that level; the deck then shows the wall's, unknown if they disagree.
    function writeWall(kind, value) {
        const slots = wallSlots();
        if (!window.isKnownTarget(WALL)) {
            window.showToast("No wall is placed — put panels on the wall first.", "error");
            return;
        }
        if (kind === "volume" && !window.wallHasSpeaker()) {
            window.showToast("Not every panel on the wall has a speaker.", "error");
            return;
        }
        const a = api();
        const call = kind === "brightness" ? "set_brightness" : "set_volume";
        if (!a || typeof a[call] !== "function") return;
        Promise.resolve(a[call](WALL, value)).then(res => {
            const done = kind === "brightness" ? `Wall brightness set to ${value}%` : `Wall volume set to ${value}/15`;
            const ok = window.DisplayWrite.report(res, {
                done, failed: `The wall did not take the ${kind}`, what: `the ${kind}`, slots, transport: " Wall" });
            const r = (res && typeof res === "object") ? res : {};
            const missed = Object.keys(r.failed || {}).concat(r.degraded || []).map(m => String(m).toLowerCase());
            // A failure that names no slot (no wall, no daemon) reached none.
            const took = ok || missed.length > 0
                ? Object.keys(slots).filter(m => !missed.includes(m.toLowerCase())) : [];
            took.forEach(m => {
                const d = record(m);
                if (d) d.levels = Object.assign({}, d.levels, { [kind]: value });
            });
            if (shownMac === WALL) paint(wallLevels());
        });
    }

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
