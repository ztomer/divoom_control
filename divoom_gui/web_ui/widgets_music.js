/* widgets_music.js — the live cover-art card (split from widgets.js for the
   500-line rule).

   R67/C2: this card used to be fed by Python code that ran osascript inside the
   GUI process and then guessed a cover-art URL from the iTunes Search API. It
   now renders whatever the DAEMON reports, from the same artwork bytes the
   device is pushed, as a data: URL — the web UI is loaded from a file:// origin
   where WKWebView blocks remote subresources, which is why the old remote
   artwork_url showed as a broken image.

   Exposes window.startTrackPolling / window.stopTrackPolling; widgets.js owns
   which card is selected and answers window.selectedWidgetIs(). */
document.addEventListener("DOMContentLoaded", () => {
    let trackTimer = null;


    function pollTrackInfo() {
        const api = window.pywebview && window.pywebview.api;
        if (!api || !api.get_current_track_info) return;
        api.get_current_track_info().then(infoJson => {
            if (!infoJson) return;
            let info;
            try { info = JSON.parse(infoJson); } catch { return; }
            if (!info) return;

            const nameEl = document.getElementById("music-track-name");
            const artistEl = document.getElementById("music-artist-name");
            const coverEl = document.getElementById("music-cover-img");
            const devPrev = document.getElementById("music-device-preview");

            // R67/C2: an unavailable source must SAY SO. Rendering it as "no
            // track" made a broken feature look like a quiet one, which is how
            // this went unnoticed for so long.
            if (info.available === false) {
                if (nameEl) nameEl.textContent = "Now Playing unavailable";
                if (artistEl) artistEl.textContent = info.reason || "";
                if (coverEl) coverEl.src = "assets/pixoo.png";
                if (devPrev) devPrev.style.display = "none";
                return;
            }
            if (info.playing === false || !info.track) {
                if (nameEl) nameEl.textContent = "Nothing playing";
                if (artistEl) artistEl.textContent = "";
                if (coverEl) coverEl.src = "assets/pixoo.png";
                if (devPrev) devPrev.style.display = "none";
                return;
            }

            if (nameEl) nameEl.textContent = info.track;
            if (artistEl) {
                const artist = info.artist || "Unknown artist";
                artistEl.textContent = info.source ? `${artist} (${info.source})` : artist;
            }
            // R67/C2: the cover used to be pointed at a REMOTE artwork_url. The
            // web UI is loaded from a file:// origin, where WKWebView blocks
            // remote subresources — that is why album art rendered broken. The
            // daemon now supplies the bytes and the backend hands us a data:
            // URL, which is what every other image in this app already uses.
            if (info.preview) {
                if (coverEl) coverEl.src = info.preview;
                if (devPrev) {
                    devPrev.src = info.preview;
                    devPrev.style.display = "inline-block";
                    // R46 #2: cover art is the device's last-active element.
                    if (window.selectedWidgetIs?.("music")) window.markActiveDeviceFrame?.(info.preview);
                }
            } else if (coverEl) {
                // Metadata but no cover (podcasts, streams). An honest
                // placeholder, not the previous track's art left in place.
                coverEl.src = "assets/pixoo.png";
                if (devPrev) devPrev.style.display = "none";
            }
        });
    }

    function startTrackPolling() {
        if (trackTimer) return;
        pollTrackInfo();
        trackTimer = setInterval(pollTrackInfo, 3000);
    }

    function stopTrackPolling() {
        if (trackTimer) {
            clearInterval(trackTimer);
            trackTimer = null;
        }
    }

    // R11: the manual "Push Cover Art" button is obsolete — cover art is pushed
    // automatically when sync is on and the track changes (and immediately on
    // enable). The button + its handler were removed.


    window.startTrackPolling = startTrackPolling;
    window.stopTrackPolling = stopTrackPolling;
});
