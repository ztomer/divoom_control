/* gallery_hot.js — device HOT channel update with in-button progress bar.
 * On tab activation the hot manifest is fetched automatically so the user
 * can see what Divoom's curated set contains before clicking the update
 * button. The button only STARTS a run and shows its progress (disabled while
 * it runs, for whichever path started it on this panel); the run's result is
 * the lasting verdict line under it (U.5, hot_verdict.js) -- the daemon's
 * record of the panel's newest run by any path, which a failure replaces and
 * nothing clears after 3 s. Rams: honest, self-explanatory, minimal. */
document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("hot-update-btn");
    if (!btn) return;
    // The panel the hot channel is shown for, and the panel the running
    // update was CLICKED for (P5.7): its completion lands there, wherever the
    // selection is by then.
    const shownMac = () => window.ChannelSettings.selected()?.mac || null;
    let updateMac = null;
    // The panel a run is under way on (from the daemon's progress events,
    // which name it), or null. The button shows progress only for the panel
    // shown; a run on another panel leaves this one's button alone.
    let runningFor = null;

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

        window.pywebview?.api?.hot_update_preview?.(shownMac() || "").then(json => {
            let r;
            try { r = JSON.parse(json); } catch { r = {success: false}; }
            if (!r.success) {
                list.innerHTML = `<div class="hot-preview-empty">${r.error || "Could not load hot manifest"}</div>`;
                return;
            }
            renderHotPreview(r.items);
        });
    }

    // ── U.5: the panel's verdict line ──────────────────────────────────────
    // The daemon writes the record (every path that updates the panel); we
    // READ it for the panel shown, and repaint when it changes.
    function renderVerdict() {
        const el = document.getElementById("hot-verdict");
        if (!el || !window.HotVerdict) return;
        const mac = shownMac();
        if (!mac) { el.textContent = ""; el.removeAttribute("data-kind"); return; }
        if (runningFor === mac) { window.HotVerdict.renderChecking(el); return; }
        window.HotVerdict.render(el, window.HotVerdict.get(mac));
    }

    function loadLastChecked() {
        const mac = shownMac();
        if (!mac || !window.HotVerdict) { renderVerdict(); return; }
        window.HotVerdict.refresh(mac).then(() => { if (shownMac() === mac) renderVerdict(); });
    }
    window.loadLastChecked = loadLastChecked;
    window.addEventListener("divoom:hot-verdict", (e) => {
        if (e.detail && e.detail.mac && e.detail.mac === shownMac()) renderVerdict();
    });
    // Another panel selected: its line, its progress.
    window.addEventListener("divoom:panel-selected", () => { syncButtonToShown(); loadLastChecked(); });
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
                    if (gifUrl) {
                        thumb.src = gifUrl;
                        if (i === 0) {
                            const mac = shownMac();
                            const curAct = window.DivoomState?.deviceActivity?.[mac];
                            if (curAct && (curAct.kind === "cloud" || curAct.kind === "hot") && window.setDeviceActivity) {
                                window.setDeviceActivity(mac, curAct.kind, { src: gifUrl });
                            }
                        }
                    }
                });
            }
        });
    }

    // ── Update button ───────────────────────────────────────────────────

    btn.addEventListener("click", () => {
        if (btn.disabled) return;
        const mac = window.ChannelSettings.mac(true);
        if (!mac) return;
        updateMac = mac;
        enterProgress(mac);

        Promise.resolve(window.pywebview?.api?.hot_channel_update?.(mac)).then(r => {
            let reply = r;
            if (typeof r === "string") { try { reply = JSON.parse(r); } catch (_) { reply = null; } }
            // Refused before it ran (not linked, another run under way): no
            // progress will come. A refusal the daemon recorded is the line.
            if (reply && reply.success === false) {
                if (runningFor === mac) runningFor = null;
                resetButton();
                loadLastChecked();
            }
        });
    });

    function enterProgress(mac) {
        runningFor = mac;
        const label = document.getElementById("hot-update-label");
        const wrap = document.getElementById("hot-progress-wrap");
        if (label) label.style.display = "none";
        if (wrap) wrap.style.display = "flex";
        btn.disabled = true;
        btn.classList.add("progress-active");
        renderVerdict();
    }

    function syncButtonToShown() {
        if (runningFor && runningFor === shownMac()) enterProgress(runningFor);
        else resetButton();
    }

    // Is a progress event for the panel shown? An event that names no panel
    // is the old daemon's; it is taken as the shown panel's.
    function forShown(p) { return !p.mac || p.mac === shownMac(); }

    function applyProgress(p) {
        if (p.phase === "done" || p.phase === "error") return; // finishProgress's
        if (p.mac) runningFor = p.mac;
        if (!forShown(p)) return;
        if (!btn.disabled) enterProgress(p.mac || shownMac());
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

    // The run ended. Its verdict is the daemon's record (written before this
    // event), so the line re-reads it; the button goes back to "Update".
    function finishProgress(p) {
        const mac = p.mac || runningFor || shownMac();
        if (runningFor === mac) runningFor = null;
        if (mac && window.HotVerdict) window.HotVerdict.refresh(mac);
        if (!forShown(p)) return;
        resetButton();
        renderVerdict();
        if (p.phase === "done") {
            // The manifest can rotate while the app sits on this tab, so the grid
            // goes stale (it only re-fetches on tab activation). Re-fetch now so
            // the tiles reflect the set the device was just synced against.
            loadHotPreview();
            const target = updateMac || mac;
            if (target && window.setDeviceActivity) {
                const firstThumb = document.querySelector("#hot-preview-list .hot-preview-thumb");
                const src = (firstThumb && firstThumb.src && !firstThumb.src.includes("pixoo.png")) ? firstThumb.src : null;
                window.setDeviceActivity(target, "cloud", src ? { src } : {});
            }
        }
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

        if (label) label.style.display = "";
        if (wrap) wrap.style.display = "none";
        if (fill) { fill.style.width = "0%"; fill.style.background = ""; }
        btn.disabled = false;
        btn.classList.remove("progress-active", "progress-ok", "progress-fail");
    }
});
