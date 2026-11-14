/*
 * theme_boot.js -- the theme the page draws, from the owner's choice (DV.WEBUILIGHT).
 *
 * The choice is dark, light or system; the page only ever draws dark or light. `body` carries
 * `theme-dark` or `theme-light` (what is drawn) and `data-theme-choice` (what was chosen), so the
 * stylesheets keep ONE light rule set, `body.theme-light`, and "system" is resolved here from
 * prefers-color-scheme (which WKWebView takes from the app's appearance) and followed live.
 * Before this file a `body.theme-system` copy of every light rule sat in a media query beside the
 * `theme-light` one, the copies drifted (tabs.css drew its light tints in the dark system theme),
 * and the boot wrote its "dark" default back on every launch, so an installed app stayed dark in
 * the light appearance with nobody having chosen dark.
 *
 * Loaded first in <body>, synchronously, so the first paint is already in the right theme.
 * settings_hardware.js wires the Appearance buttons to window.DivoomTheme.choose().
 *
 * DV.WINBG: the native window draws before this page does, so it must know the choice too.
 * The app keeps it in config.ini and hands it to the page as `?theme=`; that wins over
 * localStorage, and every choice (and a boot without `?theme=`, from before the app kept
 * it) is reported back through pywebview's `set_theme_choice`.
 */
(function () {
    "use strict";
    var KEY = "divoom-theme";
    // Written on EVERY boot until 0.45.10 (the default saved back), so it never recorded a choice.
    var LEGACY = "aesthetic-theme";
    var CHOICES = ["dark", "light", "system"];
    var query = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

    function fromUrl() {
        try {
            var v = new URLSearchParams(window.location.search).get("theme");
            return CHOICES.indexOf(v) >= 0 ? v : null;
        } catch (_) {
            return null;
        }
    }

    function stored() {
        try {
            var v = window.localStorage.getItem(KEY);
            return CHOICES.indexOf(v) >= 0 ? v : "system";
        } catch (_) {
            return "system";
        }
    }

    function drawn(choice) {
        if (choice !== "system") return choice;
        return query && query.matches ? "light" : "dark";
    }

    var given = fromUrl();
    var current = given || stored();

    function keep(choice) {
        try {
            window.localStorage.setItem(KEY, choice);
        } catch (_) { /* not kept across launches; still drawn now */ }
    }

    // The window's own background and appearance follow the choice (DV.WINBG).
    function tellApp(choice) {
        var send = function () {
            var api = window.pywebview && window.pywebview.api;
            if (api && api.set_theme_choice) api.set_theme_choice(choice);
        };
        if (window.pywebview && window.pywebview.api) send();
        else window.addEventListener("pywebviewready", send, { once: true });
    }

    function paint() {
        var body = document.body;
        var theme = drawn(current);
        body.classList.remove("theme-dark", "theme-light", "theme-system");
        body.classList.add("theme-" + theme);
        body.setAttribute("data-theme-choice", current);
        document.dispatchEvent(new CustomEvent("divoom:theme", { detail: { choice: current, theme: theme } }));
    }

    try {
        window.localStorage.removeItem(LEGACY);
    } catch (_) { /* storage unavailable: the choice is simply not kept */ }
    paint();
    if (given) keep(given);
    else tellApp(current);

    if (query) {
        var follow = function () {
            if (current === "system") paint();
        };
        if (query.addEventListener) query.addEventListener("change", follow);
        else if (query.addListener) query.addListener(follow);
    }

    window.DivoomTheme = {
        choice: function () {
            return current;
        },
        drawn: function () {
            return drawn(current);
        },
        choose: function (choice) {
            if (CHOICES.indexOf(choice) < 0) return;
            current = choice;
            keep(choice);
            tellApp(choice);
            paint();
        },
    };
})();
