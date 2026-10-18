/* channel_settings.js — each display's value for every channel control (P5.2).
 *
 * The READ side was per display (syncChannelControlsToDisplay) while the WRITE
 * side read app-wide globals: a clock style on DivoomState, a module-level
 * ambient mode, the colour inputs' DOM values, and _activeDeviceMac()
 * asked again when the panel's reply came back. A colour input therefore kept
 * the previous panel's value when the new panel was on another channel, and
 * the next clock write sent it; a slow reply was recorded on whichever panel
 * was selected by then.
 *
 * This module is the write side's one funnel:
 *   compose(channel, patch) resolves the selected display NOW, at the gesture,
 *     through DisplayPreviewRegistry.getActive(), and returns that display's
 *     settings for the channel with the patch applied;
 *   commit(w) records them as THAT display's state once the panel took them;
 *   revert(w) puts the controls back to the display's state when it did not.
 *
 * Settings are kept per channel, so a display showing Ambient still has its
 * own clock colour, and a channel switch never carries one channel's colour
 * into another. Loaded BEFORE preview_controller.js: a DisplayPreview reads
 * its saved settings when it is built.
 */
(function () {
    "use strict";

    const KEY = "divoom_channel_settings";

    // Every key a channel's controls write, with the value a display that has
    // never been set shows. A key not listed here is not a setting.
    const DEFAULTS = {
        clock: { style: 0, color: "#ffffff", humidity: false, weather: false, date: false, twentyfour: true },
        ambient: { mode: 0, color: "#00ffcc" },
        vj: { vj: null },
        visualizer: { eq: null },
        scoreboard: { red: 0, blue: 0 },
    };

    function readAll() {
        try {
            const all = JSON.parse(localStorage.getItem(KEY) || "{}");
            return (all && typeof all === "object") ? all : {};
        } catch (_) { return {}; }
    }

    window.ChannelSettings = {
        DEFAULTS,

        // What was saved for `mac`, by channel.
        stored(mac) {
            const s = readAll()[mac];
            return (s && typeof s === "object") ? s : {};
        },

        // `display`'s settings for one channel, defaults filled in.
        of(display, channel) {
            const own = (display && display.settings && display.settings[channel]) || {};
            return Object.assign({}, DEFAULTS[channel] || {}, own);
        },

        // Fold what a display now shows into its settings -- only the keys the
        // channel defines. DisplayPreview.setActivity calls this, so a daemon
        // or menubar change lands here exactly like one made in this window.
        fold(display, channel, opts) {
            const keys = Object.keys(DEFAULTS[channel] || {});
            if (!display || !opts || keys.length === 0) return;
            const picked = {};
            keys.forEach(k => { if (opts[k] !== undefined) picked[k] = opts[k]; });
            if (Object.keys(picked).length === 0) return;
            display.settings = display.settings || {};
            display.settings[channel] = Object.assign({}, display.settings[channel] || {}, picked);
            if (!display.mac || display.mac === "default") return;
            try {
                const all = readAll();
                all[display.mac] = display.settings;
                localStorage.setItem(KEY, JSON.stringify(all));
            } catch (_) { /* quota -- the in-memory settings still hold */ }
        },

        // The selected display: the ONE place a channel write asks "which panel".
        selected() {
            return window.DisplayPreviewRegistry ? window.DisplayPreviewRegistry.getActive() : null;
        },

        // A write for the selected display, resolved at the gesture. null when
        // there is no panel to write to (said once, here), and the controls
        // go back to what the display has.
        compose(channel, patch) {
            const display = this.selected();
            if (!display) {
                window.showToast(window.NO_DEVICE_HINT, "error");
                return null;
            }
            if (!window.requireDevice()) {
                this.revert({ display, mac: display.mac });
                return null;
            }
            return { display, mac: display.mac, channel, settings: Object.assign(this.of(display, channel), patch || {}) };
        },

        // The panel took it: it is that display's state now, wherever the
        // selection has moved since.
        commit(w, extra) {
            if (w && window.setDeviceActivity) window.setDeviceActivity(w.mac, w.channel, Object.assign({}, w.settings, extra || {}));
        },

        // It did not: the controls show what the display has, if it is still
        // the one shown. The values only -- the tab stays where the user is.
        revert(w) {
            if (w && this.selected() === w.display && typeof window.paintChannelControls === "function") {
                window.paintChannelControls(w.mac);
            }
        },

        isShown(w) { return !!w && this.selected() === w.display; },
    };
})();
