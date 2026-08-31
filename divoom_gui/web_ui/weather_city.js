/* weather_city.js — set the weather location by searching for a city
   (Weather/SearchCity), or clear it and go back to IP geolocation.

   The location line in the Weather card IS the control: clicking it opens the
   search, so the card gains no chrome until the user needs it. Weather
   geolocates by the caller's IP, which is right almost always and wrong exactly
   where people notice — a VPN, a datacentre egress, living near a border.

   What gets SAVED is coordinates, never the city name. Weather/SearchCity is a
   Divoom endpoint (CityId/CityName/Country/Lat/Lon); the service that actually
   fetches weather is wttr.in, which has never heard of a Divoom CityId. Lat/lon
   is the one field pair the two namespaces agree on. See
   divoom_gui/weather_city.py. */

document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("weather-location-btn");
    const panel = document.getElementById("weather-city-search");
    const input = document.getElementById("weather-city-input");
    const results = document.getElementById("weather-city-results");
    const autoBtn = document.getElementById("weather-city-auto");
    if (!btn || !panel || !input || !results || !autoBtn) return;

    let searchSeq = 0;   // last-wins: a slow search must never overwrite a newer one
    let debounce = null;

    function api() {
        return (window.pywebview && window.pywebview.api) || null;
    }

    function setStatus(msg) {
        results.innerHTML = `<div class="empty-list">${msg}</div>`;
    }

    function renderResults(cities) {
        if (!cities || cities.length === 0) {
            setStatus("No cities found.");
            return;
        }
        results.innerHTML = cities.map(c => {
            // Country is often absent; don't render a bare separator for it.
            const label = [c.CityName, c.Country].filter(Boolean).join(", ");
            return `<button type="button" class="weather-city-row"
                        data-lat="${c.Lat}" data-lon="${c.Lon}"
                        data-name="${label}">${label}</button>`;
        }).join("");
    }

    function search(keyword) {
        const a = api();
        if (!a || typeof a.search_weather_city !== "function") return;
        const seq = ++searchSeq;
        setStatus("Searching…");
        Promise.resolve(a.search_weather_city(keyword)).then(reply => {
            // A reply from a superseded keystroke would otherwise replace the
            // results for the text now in the box.
            if (seq !== searchSeq) return;
            if (Array.isArray(reply)) { renderResults(reply); return; }
            if (!reply || !reply.ok) {
                // The daemon's own words, not "no results" — a search that
                // could not run is not a search that found nothing.
                setStatus((reply && reply.error) || "Search failed.");
                return;
            }
            renderResults(reply.items || []);
        }).catch(() => {
            if (seq !== searchSeq) return;
            setStatus("Search failed.");
        });
    }

    function refreshWeatherCard() {
        // Re-read through the normal path so the card shows what the BACKEND
        // resolved, not what we just typed. If the save silently failed, the
        // card must keep showing the old city rather than an optimistic lie.
        if (typeof window.refreshWeatherPreview === "function") {
            window.refreshWeatherPreview();
        }
    }

    function save(lat, lon, name) {
        const a = api();
        if (!a || typeof a.set_weather_city !== "function") return;
        Promise.resolve(a.set_weather_city(lat, lon, name)).then(ok => {
            if (!ok) {
                setStatus("Could not save that city.");
                return;
            }
            panel.hidden = true;
            refreshWeatherCard();
        }).catch(() => setStatus("Could not save that city."));
    }

    btn.addEventListener("click", () => {
        panel.hidden = !panel.hidden;
        if (!panel.hidden) {
            input.focus();
            // Show what is currently saved, so "change it" and "clear it" are
            // both obviously available rather than guessable.
            const a = api();
            if (a && typeof a.get_weather_city === "function") {
                Promise.resolve(a.get_weather_city()).then(cur => {
                    if (cur && cur.name) {
                        setStatus(`Currently: ${cur.name}`);
                    } else {
                        setStatus("Currently using IP geolocation.");
                    }
                }).catch(() => {});
            }
        }
    });

    input.addEventListener("input", () => {
        const keyword = input.value.trim();
        if (debounce) clearTimeout(debounce);
        if (!keyword) {
            searchSeq++;  // cancel any in-flight reply
            setStatus("Type a city name.");
            return;
        }
        debounce = setTimeout(() => search(keyword), 250);
    });

    results.addEventListener("click", (ev) => {
        const row = ev.target.closest(".weather-city-row");
        if (!row) return;
        save(row.dataset.lat, row.dataset.lon, row.dataset.name);
    });

    autoBtn.addEventListener("click", () => {
        // Empty coordinates clear the override. Getting BACK to IP geolocation
        // has to be a button, not a config-file edit.
        save("", "", "");
    });
});
