/* gallery.js — Divoom Cloud community gallery fetcher + progressive item loader */

document.addEventListener("DOMContentLoaded", () => {
    const galleryContainer = document.getElementById("gallery-container");

    function removeTile(item) {
        // A genuinely broken image (decode failed, or a corrupt cached
        // preview that wouldn't load) gets removed from the gallery rather
        // than left as a black/unavailable tile (R64).
        if (!item || !item.parentNode) return;
        item.style.transition = "opacity .18s ease";
        item.style.opacity = "0";
        setTimeout(() => item.remove(), 180);
    }

    function lazyLoadAnimatedPreview(item, fileId, index) {
        if (fileId && window.pywebview && window.pywebview.api && window.pywebview.api.get_animated_preview) {
            setTimeout(() => {
                window.pywebview.api.get_animated_preview(fileId).then(gifUrl => {
                    const img = item.querySelector(".gallery-item-preview");
                    if (!img) return;
                    if (gifUrl) {
                        img.src = gifUrl;
                        img.classList.remove("is-loading", "is-unavailable");
                    } else if (img.classList.contains("is-loading")) {
                        // No cached preview at all AND the live decode also
                        // missed — this is a broken asset, not "still loading".
                        // Remove the tile rather than leave a dead skeleton.
                        removeTile(item);
                    }
                }).catch(() => {
                    const img = item.querySelector(".gallery-item-preview");
                    if (img && img.classList.contains("is-loading")) {
                        // Live fetch threw — broken asset, drop the tile.
                        removeTile(item);
                    }
                });
            }, 50 * index);
        }
    }

    // ── 1. CLOUD GALLERY FETCH ──
    function readTargetSize() {
        // `banner-device-res` was moved to Settings → Devices, so reading it here
        // ALWAYS hit the "16x16" fallback — the gallery fetched 16px art for every
        // device, even a 64px Pixoo. Derive the panel size from the active device
        // name instead (the same heuristic connectDevice uses for the preview).
        const name = (document.getElementById("banner-device-name")?.textContent || "").trim();
        const size = (window.getDeviceDimensions && name && name !== "None")
            ? (window.getDeviceDimensions(name).size || 16) : 16;
        return size === 64 ? 64 : (size === 32 ? 32 : 16);
    }
    window.readGalleryTargetSize = readTargetSize;   // exposed for the e2e test

    function loadGallery() {
        const classifyTabs = document.getElementById("gallery-classify-tabs");
        const classify = parseInt(classifyTabs?.querySelector(".cat-btn.active")?.getAttribute("data-style")) || 18;
        const fileSort = readGallerySort();
        const fileSize = readGalleryFileSize();
        if (galleryContainer) galleryContainer.innerHTML = `<div class="empty-list">Fetching public community gallery...</div>`;
        window.DivoomState.loadedArtworks = [];
        window.DivoomState.selectedArtworkIndex = null;
        const targetSize = readTargetSize();
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.fetch_gallery(classify, targetSize, fileSort, fileSize)
                .then(artworksJson => {
                    const artworks = JSON.parse(artworksJson);
                    if (artworks.error) {
                        window.showToast(artworks.error, "error");
                        if (galleryContainer) {
                            galleryContainer.innerHTML = `<div class="empty-list" style="color:#ef4444; padding:20px; font-weight:600; text-align:center;"> ${artworks.error}</div>`;
                        }
                        return;
                    }
                    window.DivoomState.loadedArtworks = artworks;
                    window.DivoomState.selectedArtworkIndex = null;
                    renderGallery(artworks);
                    window.showToast("Gallery loaded from cache", "success", " Cloud");
                });
        }
    }

    window.loadGallery = loadGallery;

    function activeDeviceAddr() {
        return (document.getElementById("banner-device-mac")?.textContent || "").trim();
    }
    window.persistGalleryStyle = function(classify) {
        if (window.pywebview?.api?.set_gallery_style) {
            window.pywebview.api.set_gallery_style(activeDeviceAddr(), parseInt(classify) || 18);
        }
    };
    window.loadPreferredGalleryStyle = function() {
        if (window.pywebview?.api?.get_gallery_style) {
            return window.pywebview.api.get_gallery_style(activeDeviceAddr()).then(style => {
                if (style !== null && style !== undefined) {
                    const tabs = document.getElementById("gallery-classify-tabs");
                    if (tabs) {
                        tabs.querySelectorAll(".cat-btn").forEach(b => {
                            b.classList.toggle("active", b.getAttribute("data-style") === String(style));
                        });
                    }
                }
                return style;
            });
        }
        return Promise.resolve(18);
    };

    function readGallerySort() {
        const tabs = document.getElementById("gallery-sort-tabs");
        return parseInt(tabs?.querySelector(".tab-btn.active")?.getAttribute("data-sort")) || 1;
    }

    function readGalleryFileSize() {
        const sel = document.getElementById("gallery-size-select");
        return parseInt(sel?.value) || 0;
    }

    function persistGalleryFilter() {
        const sort = readGallerySort();
        const fileSize = readGalleryFileSize();
        if (window.pywebview?.api?.set_gallery_filter) {
            window.pywebview.api.set_gallery_filter(sort, fileSize);
        }
    }

    function loadGalleryFilter() {
        if (window.pywebview?.api?.get_gallery_filter) {
            window.pywebview.api.get_gallery_filter().then(json => {
                try {
                    const f = JSON.parse(json);
                    const sortTabs = document.getElementById("gallery-sort-tabs");
                    if (sortTabs) {
                        sortTabs.querySelectorAll(".tab-btn").forEach(b => {
                            b.classList.toggle("active", b.getAttribute("data-sort") === String(f.sort));
                        });
                    }
                    const sizeSel = document.getElementById("gallery-size-select");
                    if (sizeSel && f.file_size != null) sizeSel.value = String(f.file_size);
                } catch (e) { /* ignore */ }
            });
        }
    }

    document.addEventListener("click", (e) => {
        const btn = e.target.closest("#gallery-classify-tabs .cat-btn");
        if (!btn) return;
        document.querySelectorAll("#gallery-classify-tabs .cat-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        loadGallery();
        if (window.persistGalleryStyle) window.persistGalleryStyle(btn.getAttribute("data-style"));
    });

    document.addEventListener("click", (e) => {
        const btn = e.target.closest("#gallery-sort-tabs .tab-btn");
        if (!btn) return;
        document.querySelectorAll("#gallery-sort-tabs .tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        persistGalleryFilter();
        loadGallery();
    });

    document.addEventListener("change", (e) => {
        if (e.target.id === "gallery-size-select") {
            persistGalleryFilter();
            loadGallery();
        }
    });

    function buildGalleryItem(art, idx) {
        const item = document.createElement("div");
        item.className = "gallery-item";
        const isLoading = !art.preview_url;
        const previewSrc = art.preview_url ? art.preview_url : "assets/pixoo.png";
        item.innerHTML = `
                <div class="gallery-item-preview-box">
                    <img src="${previewSrc}" class="gallery-item-preview${isLoading ? " is-loading" : ""}" alt="${art.name}">
                </div>
                <div class="gallery-item-info">
                    <h5>${art.name}</h5>
                    <span> ${art.likes}</span>
                </div>
            `;
        item.dataset.idx = String(idx);
        const img = item.querySelector(".gallery-item-preview");
        if (img) {
            // A cached preview file that is corrupt/unreadable will fail to
            // load — drop the tile instead of showing a broken image.
            img.addEventListener("error", () => removeTile(item));
        }
        return item;
    }

    function renderGallery(artworks) {
        if (galleryContainer) galleryContainer.innerHTML = "";

        if (!artworks || artworks.length === 0) {
            if (galleryContainer) galleryContainer.innerHTML = `<div class="empty-list">No gallery items found for classification.</div>`;
            return;
        }

        artworks.forEach((art, idx) => {
            const item = buildGalleryItem(art, idx);
            if (galleryContainer) {
                galleryContainer.appendChild(item);
                lazyLoadAnimatedPreview(item, art.file_id, idx);
            }
        });
    }

    // ── 2. ROUTINE SYNC TARGETS (Routines → Schedule device list) ──
    window.renderSyncTargets = function(candidates) {
        const el = document.getElementById("sync-targets-list");
        if (!el) return;
        if (!Array.isArray(candidates) || candidates.length === 0) {
            el.innerHTML = `<span class="empty-list">No devices — scan under Settings, or add a Wi-Fi screen.</span>`;
            return;
        }
        el.innerHTML = "";
        candidates.forEach(c => {
            const row = document.createElement("div");
            row.className = "sync-device-row";
            row.style.cssText = "display:flex; flex-wrap:nowrap; align-items:center; gap:8px; padding:9px 0;";

            const color = window.deviceColor(c.address);
            const accent = document.createElement("span");
            accent.className = "device-accent-dot";
            accent.style.background = color;
            accent.style.boxShadow = `0 0 6px ${color}`;
            accent.style.marginRight = "4px";
            accent.style.flexShrink = "0";

            const name = document.createElement("span");
            name.className = "target-name";
            name.textContent = c.name;
            name.title = c.name;
            name.style.cssText =
                "flex:0 1 auto; min-width:0; max-width:240px; overflow:hidden; "
                + "text-overflow:ellipsis; white-space:nowrap;";

            const status = document.createElement("span");
            status.className = "sync-now-row-status";
            status.dataset.addr = c.address;
            status.style.cssText = "font-size:11px; color:var(--text-muted); margin-left:auto; white-space:nowrap;";

            const toggle = document.createElement("label");
            toggle.className = "switch";
            toggle.style.margin = "0";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = c.address;
            cb.checked = !!c.selected;
            cb.addEventListener("change", persistSyncTargets);
            const slider = document.createElement("span");
            slider.className = "slider-round";
            toggle.append(cb, slider);

            row.append(accent, name, status, toggle);
            el.appendChild(row);
        });
    }

    function persistSyncTargets() {
        const checked = Array.from(document.querySelectorAll("#sync-targets-list input:checked")).map(i => i.value);
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_sync_targets) {
            window.pywebview.api.set_sync_targets(JSON.stringify(checked));
        }
    }

    window.updateSyncTargetList = function() {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.get_sync_candidates) {
            window.pywebview.api.get_sync_candidates().then(json => {
                try { window.renderSyncTargets(JSON.parse(json)); } catch (e) { /* ignore */ }
            });
        }
    }

    window.onGalleryItemLoaded = function(classify, targetSize, index, total, itemB64, fileSort, fileSize) {
        try {
            const classifyTabs = document.getElementById("gallery-classify-tabs");
            const currentClassify = parseInt(classifyTabs?.querySelector(".cat-btn.active")?.getAttribute("data-style")) || 18;
            const currentTargetSize = readTargetSize();
            const currentSort = readGallerySort();
            const currentFileSize = readGalleryFileSize();
            if (currentClassify !== classify || currentTargetSize !== targetSize
                || currentSort !== (fileSort ?? 1) || currentFileSize !== (fileSize ?? 0)) return;

            const rawJson = atob(itemB64);
            const art = JSON.parse(rawJson);

            // Clear "Fetching..." placeholder on first item when no cached items exist
            if (index === 0 && galleryContainer) {
                const existingItems = galleryContainer.querySelectorAll(".gallery-item");
                if (existingItems.length === 0) {
                    galleryContainer.innerHTML = "";
                    window.DivoomState.loadedArtworks = [];
                }
            }

            // Replace existing item at index, or append beyond current length
            if (index < (window.DivoomState.loadedArtworks?.length || 0)) {
                window.DivoomState.loadedArtworks[index] = art;
                const existingItem = galleryContainer?.querySelector(`.gallery-item[data-idx="${index}"]`);
                if (existingItem) {
                    const newItem = buildGalleryItem(art, index);
                    galleryContainer?.replaceChild(newItem, existingItem);
                    lazyLoadAnimatedPreview(newItem, art.file_id, index);
                    return;
                }
            } else {
                window.DivoomState.loadedArtworks.push(art);
            }

            const currentIdx = window.DivoomState.loadedArtworks.length - 1;
            const item = buildGalleryItem(art, currentIdx);
            if (galleryContainer) {
                galleryContainer.appendChild(item);
                lazyLoadAnimatedPreview(item, art.file_id, currentIdx);
            }
        } catch (e) {
            console.error("Failed to render progressive gallery item:", e);
        }
    };

    window.onGalleryBackgroundFetched = function(classify, targetSize, b64Data, fileSort, fileSize) {
        try {
            const rawJson = atob(b64Data);
            const artworks = JSON.parse(rawJson);
            const classifyTabs = document.getElementById("gallery-classify-tabs");
            const currentClassify = parseInt(classifyTabs?.querySelector(".cat-btn.active")?.getAttribute("data-style")) || 18;
            const currentTargetSize = readTargetSize();
            const currentSort = readGallerySort();
            const currentFileSize = readGalleryFileSize();
            if (currentClassify === classify && currentTargetSize === targetSize
                && currentSort === (fileSort ?? 1) && currentFileSize === (fileSize ?? 0)) {
                // Only re-render if the number of items changed significantly,
                // otherwise progressive items already filled the gallery.
                const currentCount = window.DivoomState.loadedArtworks?.length || 0;
                if (Math.abs(currentCount - artworks.length) > 2) {
                    window.DivoomState.loadedArtworks = artworks;
                    window.DivoomState.selectedArtworkIndex = null;
                    renderGallery(artworks);
                    window.showToast("Gallery updated", "success", " Cloud");
                }
            }
        } catch (e) {
            console.error("Failed to process background gallery fetch:", e);
        }
    };

    window.onGalleryFetchError = function(classify, targetSize, isExpired, errMsg) {
        try {
            const classifyTabs = document.getElementById("gallery-classify-tabs");
            const currentClassify = parseInt(classifyTabs?.querySelector(".cat-btn.active")?.getAttribute("data-style")) || 18;
            const currentTargetSize = readTargetSize();
            if (currentClassify !== classify || currentTargetSize !== targetSize) return;

            if (isExpired) {
                window.showToast("Credentials expired. Reconnect in Settings -> Divoom.", "error");
                if (galleryContainer) {
                    galleryContainer.innerHTML = `<div class="empty-list" style="color:#ef4444; padding:20px; font-weight:600; text-align:center;">Credentials expired. Please reconnect under Settings.</div>`;
                }
            } else {
                window.showToast(`Fetch failed: ${errMsg}`, "error");
                if (galleryContainer) {
                    galleryContainer.innerHTML = `<div class="empty-list" style="color:#ef4444; padding:20px; font-weight:600; text-align:center;">Fetch failed: ${errMsg}</div>`;
                }
            }
        } catch (e) {
            console.error("Failed to process gallery fetch error:", e);
        }
    };

    window.addEventListener("tab-changed", (e) => {
        if (e.detail.tab === "gallery" || e.detail.tab === "pixel-art") {
            // For pixel-art, only load if the gallery sub-tab is active
            if (e.detail.tab === "pixel-art") {
                const activeTab = document.querySelector(".tab-btn[data-pixel-tab].active");
                if (!activeTab || activeTab.getAttribute("data-pixel-tab") !== "pixel-gallery") return;
            }
            loadGallery();
        }
    });

    setTimeout(() => {
        window.updateSyncTargetList();
        loadGalleryFilter();  // local fn in this closure (not exposed on window)
        window.loadPreferredGalleryStyle();
    }, 1500);
});
