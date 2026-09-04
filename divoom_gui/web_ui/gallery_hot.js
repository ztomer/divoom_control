/* gallery_hot.js — device HOT channel update with in-button progress bar.
 * On tab activation the hot manifest is fetched automatically so the user
 * can see what Divoom's curated set contains before clicking the update
 * button. The button transforms into a progress bar during upload:
 *   - smooth animated fill with a readable status label
 *   - disabled + non-interactive while running
 *   - auto-resets after 3s on completion or failure
 * Rams: honest, self-explanatory, minimal. Kare: clear at a glance. */
document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("hot-update-btn");
    if (!btn) return;

    // ── Auto-fetch hot channel manifest on tab activation ──────────────
    window.addEventListener("tab-changed", (e) => {
        if (e.detail.tab === "hot-channel" || e.detail.tab === "pixel-art") {
            if (e.detail.tab === "pixel-art") {
                const activeTab = document.querySelector(".tab-btn[data-pixel-tab].active");
                if (!activeTab || activeTab.getAttribute("data-pixel-tab") !== "pixel-hot-channel") return;
            }
            loadHotPreview();
        }
    });

    function loadHotPreview() {
        const list = document.getElementById("hot-preview-list");
        if (!list) return;
        list.innerHTML = '<div class="hot-preview-empty">Loading hot channel manifest...</div>';
        loadLastChecked();  // R53: show when this device was last checked

        window.pywebview?.api?.hot_update_preview?.().then(json => {
            let r;
            try { r = JSON.parse(json); } catch { r = {success: false}; }
            if (!r.success) {
                list.innerHTML = `<div class="hot-preview-empty">${r.error || "Could not load hot manifest"}</div>`;
                return;
            }
            renderHotPreview(r.items);
        });
    }

    // ── R53: per-device "last checked" stamp ──────────────────────────────
    // The daemon writes the stamp (it owns the update); we only READ it, keyed
    // by the active device — the backend resolves that key, matching what
    // hot_channel_update passed for the write.
    function formatChecked(seconds) {
        const then = seconds * 1000;
        const diff = Date.now() - then;
        const day = 86400000;
        if (diff < 60000) return "just now";
        if (diff < 3600000) { const m = Math.round(diff / 60000); return `${m} min${m > 1 ? "s" : ""} ago`; }
        if (diff < day) { const h = Math.round(diff / 3600000); return `${h} hour${h > 1 ? "s" : ""} ago`; }
        if (diff < 30 * day) { const d = Math.round(diff / day); return `${d} day${d > 1 ? "s" : ""} ago`; }
        return new Date(then).toLocaleDateString();
    }

    function renderLastChecked(entry) {
        const el = document.getElementById("hot-last-checked");
        if (!el) return;
        if (!entry || !entry.checked_at) { el.textContent = ""; el.title = ""; el.classList.remove("stale"); return; }
        el.textContent = `Last checked ${formatChecked(entry.checked_at)}`;
        // >2 weeks old → flag it, so an undated "up to date" can't mislead.
        const stale = (Date.now() - entry.checked_at * 1000) > 14 * 86400000;
        el.classList.toggle("stale", stale);
        el.title = new Date(entry.checked_at * 1000).toLocaleString()
            + ` — manifest ${entry.manifest}, downloaded ${entry.downloaded}, pushed ${entry.served}`;
    }

    function loadLastChecked() {
        if (!window.pywebview?.api?.hot_get_check) { renderLastChecked(null); return; }
        // No address arg — the backend resolves the active device (same key the
        // write used), so read and write can't drift.
        window.pywebview.api.hot_get_check().then(json => {
            let e; try { e = JSON.parse(json); } catch { e = null; }
            renderLastChecked(e);
        });
    }
    window.loadLastChecked = loadLastChecked;
    // R42 §4: the pixel-art sub-tab handler (settings_features.js) calls
    // window.loadHotPreview — without this exposure the hot panel stayed on
    // "Loading hot channel manifest..." forever when the sub-tab was clicked.
    window.loadHotPreview = loadHotPreview;

    function renderHotPreview(items) {
        const list = document.getElementById("hot-preview-list");
        if (!list) return;

        if (!items || items.length === 0) {
            list.innerHTML = '<div class="hot-preview-empty">No hot files available for this device.</div>';
            return;
        }

        // Tiles are image-only — the name/version live in the tooltip, so the
        // grid packs more art per row (Rams: omit the inessential).
        list.innerHTML = items.map((item, i) => {
            const name = item.name || item.file_id;
            return `<div class="hot-preview-item" title="${name} (v${item.version})">
                <img class="hot-preview-thumb" src="${item.preview_url || 'assets/pixoo.png'}"
                     alt="${name}" loading="lazy"
                     onerror="this.src='assets/pixoo.png'">
            </div>`;
        }).join("");

        // Lazy-load animated GIF previews for all hot channel items
        // (get_animated_preview handles download + decode from CDN on first access)
        items.forEach((item, i) => {
            if (item.file_id && window.pywebview?.api?.get_animated_preview) {
                const thumb = list.querySelectorAll(".hot-preview-thumb")[i];
                if (!thumb) return;
                window.pywebview.api.get_animated_preview(item.file_id).then(gifUrl => {
                    if (gifUrl) thumb.src = gifUrl;
                });
            }
        });
    }

    // ── Update button ───────────────────────────────────────────────────
    btn.addEventListener("click", () => {
        if (btn.disabled) return;
        if (window.requireDevice && !window.requireDevice()) return;

        const label = document.getElementById("hot-update-label");
        const wrap = document.getElementById("hot-progress-wrap");
        label.style.display = "none";
        wrap.style.display = "flex";
        btn.disabled = true;
        btn.classList.add("progress-active");

        window.pywebview?.api?.hot_channel_update?.().then(r => {
            // R59/event-driven: the daemon broadcasts `hot_progress` (starting/
            // done/error) for every phase, so the 600ms poll is gone — progress
            // is pushed live via window.Divoom.onHotProgress.
            if (window.Divoom && window.Divoom.onHotProgress) {
                window.Divoom.onHotProgress({ type: "hot_progress", progress: 0, phase: "starting" });
            }
        });
    });

    function applyProgress(p) {
        const fill = document.getElementById("hot-progress-fill");
        const text = document.getElementById("hot-progress-text");
        if (!fill || !text) return;

        let pct = 0;
        let msg = "Starting\u2026";

        // Two phases, made explicit so the step is legible: first we pull the
        // curated files FROM Divoom's cloud, then we stream them TO the device.
        switch (p.phase) {
            case "starting":
                pct = 0;
                msg = "Preparing\u2026";
                break;
            case "fetching_manifest":
                pct = 2;
                msg = "1/2 Fetching hot list\u2026";
                break;
            case "downloading":
                pct = 5 + (p.current / p.total) * 45;
                // Cached: bodies were already downloaded for this device size, so
                // we skip straight to the upload \u2014 say so rather than flashing a
                // misleading "downloading".
                msg = p.cached
                    ? "1/2 Using cached files"
                    : `1/2 Downloading from Divoom ${p.current}/${p.total}`;
                break;
            case "uploading":
                pct = 50 + (p.current / p.total) * 48;
                msg = `2/2 Uploading to device ${p.current}/${p.total}`;
                break;
        }

        fill.style.width = `${Math.round(pct)}%`;
        text.textContent = msg;
    }

    function finishProgress(p) {
        const fill = document.getElementById("hot-progress-fill");
        const text = document.getElementById("hot-progress-text");

        if (p.phase === "done") {
            fill.style.width = "100%";
            const result = p.result || {};
            const served = (result.served || []).length;
            const manifest = result.manifest || 0;
            // downloaded may be absent on older daemons — assume complete then.
            const downloaded = (result.downloaded != null) ? result.downloaded : manifest;
            // Some curated files couldn't be fetched from the CDN, so the device
            // was never offered them. Reporting "Up to date" here is the false
            // positive the user hit — be honest instead.
            const incomplete = manifest > 0 && downloaded < manifest;

            btn.classList.remove("progress-active");
            if (served) {
                text.textContent = `${served} file${served > 1 ? "s" : ""} updated`;
                fill.style.background = "linear-gradient(90deg, #166534, #22c55e)";
                btn.classList.add("progress-ok");
                window.showToast(
                    `Hot channel updated (${served} file${served > 1 ? "s" : ""})`,
                    "success", " BLE");
            } else if (incomplete) {
                const missing = manifest - downloaded;
                text.textContent = `Checked ${downloaded}/${manifest}`;
                fill.style.background = "linear-gradient(90deg, #78350f, #f59e0b)";
                btn.classList.add("progress-ok");
                window.showToast(
                    `Hot channel: ${missing} file${missing > 1 ? "s" : ""} couldn't be fetched — not fully checked`,
                    "error");
            } else {
                text.textContent = "Up to date";
                fill.style.background = "linear-gradient(90deg, #166534, #22c55e)";
                btn.classList.add("progress-ok");
                window.showToast("Hot channel already up to date", "success", " BLE");
            }
            // R53: the DAEMON stamped the last-checked state on completion; just
            // re-read it so the label reflects the daemon-owned source of truth.
            loadLastChecked();
            // The manifest can rotate while the app sits on this tab, so the grid
            // goes stale (it only re-fetches on tab activation). Re-fetch now so
            // the tiles reflect the set the device was just synced against — the
            // newest file was missing from the preview until this refresh.
            loadHotPreview();
        } else {
            fill.style.width = "100%";
            text.textContent = p.error ? `Failed: ${p.error}` : "Update failed";
            fill.style.background = "linear-gradient(90deg, #7f1d1d, #ef4444)";
            btn.classList.remove("progress-active");
            btn.classList.add("progress-fail");
            window.showToast(`Hot update failed: ${p.error || "unknown"}`, "error");
        }

        setTimeout(resetButton, 3000);
    }
    // connection_events.js's window.Divoom.onHotProgress calls these by name
    // on window — without this exposure they're closure-local and the calls
    // silently no-op, so resetButton() (called from finishProgress) never
    // runs and the button stays disabled after the first click.
    window.applyProgress = applyProgress;
    window.finishProgress = finishProgress;

    function resetButton() {
        const label = document.getElementById("hot-update-label");
        const wrap = document.getElementById("hot-progress-wrap");
        const fill = document.getElementById("hot-progress-fill");

        label.style.display = "";
        wrap.style.display = "none";
        if (fill) fill.style.width = "0%";
        btn.disabled = false;
        btn.classList.remove("progress-active", "progress-ok", "progress-fail");
    }
});
