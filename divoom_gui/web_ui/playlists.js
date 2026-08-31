/* playlists.js — browse the user's cloud-hosted playlists (Playlist/GetMyList)
   and push one to the device (Playlist/SendDevice, LAN-only). No thumbnails
   from this API — a plain text list with name + item count, like
   cloud_clock_faces.js's clock-face browser. */

document.addEventListener("DOMContentLoaded", () => {
    const listEl = document.getElementById("cloud-playlist-list");
    if (!listEl) return;

    function renderPlaylistList(playlists) {
        if (!playlists || playlists.length === 0) {
            listEl.innerHTML = `<div class="empty-list">No playlists in your Divoom account.</div>`;
            return;
        }
        listEl.innerHTML = playlists.map(p => `
            <div class="cloud-clock-row" data-play-id="${p.PlayId}">
                <span class="cloud-clock-name">${p.Name} <span style="color:var(--text-muted);">(${p.Count ?? 0} items)</span></span>
                <button type="button" class="cloud-clock-apply-btn">Push</button>
            </div>
        `).join("");
    }

    function loadPlaylists() {
        if (!window.pywebview?.api?.get_my_playlists) return;
        listEl.innerHTML = `<div class="empty-list">Loading…</div>`;
        window.pywebview.api.get_my_playlists().then(reply => {
            const playlists = window.DivoomCloud.unwrap(reply, listEl, "No playlists.");
            if (playlists === null) return;
            renderPlaylistList(playlists);
        }).catch(() => {
            listEl.innerHTML = `<div class="empty-list">Failed to load playlists.</div>`;
        });
    }
    window.loadPlaylists = loadPlaylists;

    if (document.getElementById("pixel-playlists")?.classList.contains("active")) {
        loadPlaylists();
    }

    listEl.addEventListener("click", (e) => {
        const btn = e.target.closest(".cloud-clock-apply-btn");
        if (!btn) return;
        if (!window.requireDevice || !window.requireDevice()) return;
        const row = btn.closest(".cloud-clock-row");
        const playId = parseInt(row?.getAttribute("data-play-id"));
        if (!playId || !window.pywebview?.api?.push_playlist) return;
        btn.disabled = true;
        window.pywebview.api.push_playlist(playId).then(res => {
            btn.disabled = false;
            window.showToast(res ? "Playlist pushed to device" : "Failed to push playlist", res ? "success" : "error", " BLE");
            if (res && window.setDeviceActivity) {
                window.setDeviceActivity(window._activeDeviceMac(), "playlist", { playId });
            }
        }).catch(() => {
            btn.disabled = false;
            window.showToast("Failed to push playlist", "error");
        });
    });
});
