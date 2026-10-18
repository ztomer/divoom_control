/* widgets_weather.js — the Weather card (split from widgets.js for the
   500-line rule, P5.4).

   The picture is the frame the PANEL shows: get_weather_preview returns the
   PNG of render_widget {kind:"weather"} -- the call the weather live job's
   frame comes from -- plus the reading it was drawn from, in one reply. This
   file only displays them. It used to draw its own SVG icon and temperature
   from get_weather, a second renderer for one widget (the class R70 removed
   for sysmon, stocks and album art).

   Exposes window.refreshWeatherPreview; widgets.js owns which card is selected
   and drives the Live (15m) timer, and weather_city.js re-reads through it
   after the city changes, so what the card shows is what the BACKEND resolved
   (a save that silently failed leaves the old city on screen). */
document.addEventListener("DOMContentLoaded", () => {

    // No drawing to fall back on: until a frame arrives, or when it cannot,
    // the box says why (loading and failed differ in text AND border shape).
    let weatherRequest = 0;  // last-wins: a slow reply never overwrites a newer one

    function setWeatherCard(state, note, frame, tempText) {
        const wrap = document.getElementById("weather-device-preview");
        const img = document.getElementById("weather-frame");
        const noteEl = document.getElementById("weather-frame-note");
        const tempEl = document.getElementById("weather-reading-temp");
        if (wrap) wrap.dataset.state = state;
        if (img) {
            if (frame) { img.src = frame; img.style.display = "block"; }
            else { img.style.display = "none"; img.removeAttribute("src"); }
        }
        if (noteEl) noteEl.textContent = note;
        // A placeholder never keeps the last number dressed as current.
        if (tempEl) tempEl.textContent = tempText || "–";
    }

    function renderWeatherReply(r) {
        if (!r || !r.ok || !r.preview) {
            const why = (r && r.error) || "no frame came back from the background service";
            setWeatherCard("failed", `⚠ Weather unavailable — ${why}`, null, null);
            return;
        }
        setWeatherCard("ok", "", r.preview, `${r.temperature_c}°C`);
        const locEl = document.getElementById("weather-preview-location");
        if (locEl) {
            const loc = r.location || "unknown";
            locEl.textContent = loc.length > 28 ? `${loc.slice(0, 25)}…` : loc;
        }
        // The panel shows this frame while weather is its widget; mirror it
        // onto the displays bound to the weather job, as sysmon and stocks do.
        if (window.selectedWidgetIs?.("weather")) window.markActiveDeviceFrame?.(r.preview, null, "weather");
    }

    function refreshWeatherPreview() {
        if (!window.pywebview || !window.pywebview.api) return;
        const api = window.pywebview.api;
        if (typeof api.get_weather_preview !== "function") return;
        const ticket = ++weatherRequest;
        const wrap = document.getElementById("weather-device-preview");
        if (wrap && wrap.dataset.state !== "ok") {
            setWeatherCard("loading", "Loading the panel's weather frame…", null, null);
        }
        Promise.resolve(api.get_weather_preview(window.ChannelSettings.selected()?.mac || "", 0)).then(json => {
            if (ticket !== weatherRequest) return;
            let r = json;
            if (typeof json === "string") {
                try { r = JSON.parse(json); } catch (e) { r = {ok: false, error: "the reply was not readable"}; }
            }
            renderWeatherReply(r);
        }, err => {
            if (ticket !== weatherRequest) return;
            renderWeatherReply({ok: false, error: String(err && err.message || err)});
        });
    }

    window.refreshWeatherPreview = refreshWeatherPreview;

    // R18 item 1: populate the card on load, no click required. Here rather
    // than in widgets.js, whose load handler runs before this file defines
    // the function. (Preview only; the panel is pushed when weather is the
    // selected widget, per the one-active-widget model.)
    refreshWeatherPreview();
});
