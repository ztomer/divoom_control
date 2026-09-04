/* photo_albums.js — browse the photo albums configured for the active
   device (Photo/GetAlbumList) and play one (Photo/PlayAlbum, LAN-only —
   no cloud round-trip). No thumbnails from this API — a plain text list,
   like playlists.js's browser. */

document.addEventListener("DOMContentLoaded", () => {
    const listEl = document.getElementById("cloud-photo-album-list");
    if (!listEl) return;

    function renderAlbumList(albums) {
        if (!albums || albums.length === 0) {
            listEl.innerHTML = `<div class="empty-list">No photo albums configured for this device.</div>`;
            return;
        }
        listEl.innerHTML = albums.map(a => `
            <div class="cloud-clock-row" data-album-id="${a.ClockId}">
                <span class="cloud-clock-name">${a.ClockName}</span>
                <button type="button" class="cloud-clock-apply-btn">Play</button>
            </div>
        `).join("");
    }

    function loadPhotoAlbums() {
        if (!window.pywebview?.api?.get_photo_albums) return;
        listEl.innerHTML = `<div class="empty-list">Loading…</div>`;
        window.pywebview.api.get_photo_albums().then(reply => {
            const albums = window.DivoomCloud.unwrap(reply, listEl, "No photo albums.");
            if (albums === null) return;
            renderAlbumList(albums);
        }).catch(() => {
            listEl.innerHTML = `<div class="empty-list">Failed to load photo albums.</div>`;
        });
    }
    window.loadPhotoAlbums = loadPhotoAlbums;

    listEl.addEventListener("click", (e) => {
        const btn = e.target.closest(".cloud-clock-apply-btn");
        if (!btn) return;
        if (!window.requireDevice || !window.requireDevice()) return;
        const row = btn.closest(".cloud-clock-row");
        const albumId = parseInt(row?.getAttribute("data-album-id"));
        if (!albumId || !window.pywebview?.api?.play_album) return;
        btn.disabled = true;
        window.pywebview.api.play_album(albumId).then(res => {
            btn.disabled = false;
            /* R71 P3.4: {ok, error, cause}, not a bool — a Bluetooth-only
               device now says so instead of "Failed to play album". */
            const ok = res && res.ok;
            window.showToast(
                ok ? "Album playing on device"
                   : window.DivoomCloud.problemText(res, "Failed to play album"),
                ok ? "success" : "error", " LAN");
            if (ok && window.setDeviceActivity) {
                window.setDeviceActivity(window._activeDeviceMac(), "photo_album", { albumId });
            }
        }).catch(() => {
            btn.disabled = false;
            window.showToast("Failed to play album", "error");
        });
    });
});
