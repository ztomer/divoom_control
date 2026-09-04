/* templates_pixel_art.js — Pixel Art panel template (Custom Art + Gallery + Hot Channel) */
window.DivoomTemplates = window.DivoomTemplates || {};
window.DivoomTemplates.pixelArt = `                <div class="tabs-section" style="width:100%; box-sizing:border-box;">
                <div class="tabs-row" role="tablist" aria-label="Pixel Art">
                    <button class="tab-btn active" data-pixel-tab="pixel-custom-art" role="tab" aria-selected="true">
                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M2,4 C2,2 5,1 8,1 C12,1 15,3 15,7 C15,11 11,14 7,14 C5.5,14 4.5,13.5 3.5,13.5 C2.5,13.5 1,15 1,13 C1,11.5 1,9.5 2,7 C2,5.5 2,5 2,4 Z" fill="none" stroke="currentColor" stroke-width="2"/>
                            <circle cx="5" cy="4" r="1"/>
                            <circle cx="9" cy="4" r="1"/>
                            <circle cx="11" cy="7" r="1"/>
                            <circle cx="8" cy="10" r="1"/>
                        </svg>
                        <span>Custom Art</span>
                    </button>
                    <button class="tab-btn" data-pixel-tab="pixel-gallery" role="tab" aria-selected="false">
                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                            <rect x="1" y="1" width="6" height="6" rx="1"/>
                            <rect x="9" y="1" width="6" height="6" rx="1"/>
                            <rect x="1" y="9" width="6" height="6" rx="1"/>
                            <rect x="9" y="9" width="6" height="6" rx="1"/>
                        </svg>
                        <span>Gallery</span>
                    </button>
                    <button class="tab-btn" data-pixel-tab="pixel-hot-channel" role="tab" aria-selected="false">
                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M8,1 C8,1 11,4 11,7 C11,10 8,15 8,15 C8,15 5,10 5,7 C5,4 8,1 8,1 Z"/>
                            <path d="M8,4 C8,4 9.5,6 9.5,7.5 C9.5,9.5 8,12 8,12 C8,12 6.5,9.5 6.5,7.5 C6.5,6 8,4 8,4 Z" fill="var(--bg-base)"/>
                        </svg>
                        <span>Hot Channel</span>
                    </button>
                    <button class="tab-btn" data-pixel-tab="pixel-playlists" role="tab" aria-selected="false">
                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                            <rect x="1" y="2" width="9" height="2"/>
                            <rect x="1" y="7" width="9" height="2"/>
                            <rect x="1" y="12" width="6" height="2"/>
                            <circle cx="13" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="1.5"/>
                            <path d="M14,12 L14,3 L15,3.5" fill="none" stroke="currentColor" stroke-width="1.5"/>
                        </svg>
                        <span>Playlists</span>
                    </button>
                    <button class="tab-btn" data-pixel-tab="pixel-photo-albums" role="tab" aria-selected="false">
                        <svg class="kare-icon tab-icon" viewBox="0 0 16 16" aria-hidden="true">
                            <rect x="1" y="2" width="14" height="11" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/>
                            <circle cx="5" cy="6" r="1.5"/>
                            <path d="M2,12 L6,8 L9,11 L12,7 L15,10 L15,12 Z"/>
                        </svg>
                        <span>Photo Albums</span>
                    </button>
                </div>
                </div>

                <!-- CUSTOM ART sub-tab -->
                <div class="pixel-subtab-content active" id="pixel-custom-art">
                    <div class="custom-art-layout">
                        <div class="card glass-card" style="flex:1; min-height:0; display:flex; flex-direction:column;">
                            <div class="card-body" style="flex:1; min-height:0; display:flex; flex-direction:column; overflow:hidden;">
                                <div class="channel-panel active" id="panel-design">
                                    <div class="custom-art-fixed">
                                        <div id="custom-art-page-tabs" class="custom-art-tabs">
                                            <button class="page-tab glow-btn compact" data-page="0">Page 1</button>
                                            <button class="page-tab glow-btn compact" data-page="1">Page 2</button>
                                            <button class="page-tab glow-btn compact" data-page="2">Page 3</button>
                                        </div>
                                        <div id="custom-art-slot-grid" class="custom-art-slots"></div>
                                        <p class="panel-hint custom-art-hint">Click or drag art into a slot. Drag slots to reorder; hover a filled slot and click &times; to clear it.</p>
                                    </div>
                                    <div class="gallery-cache-selector custom-art-library">
                                        <input type="text" id="custom-art-search" placeholder="Search cached art…" class="text-input">
                                        <div class="selector-grid" id="custom-art-cache-grid">
                                            <div class="empty-list" style="grid-column: 1/-1;">No cached gallery files.</div>
                                        </div>
                                    </div>
                                    <button id="push-custom-art-btn" class="glow-btn">Push Page 1 to Device</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- GALLERY sub-tab -->
                <div class="pixel-subtab-content" id="pixel-gallery">
                    <div class="gallery-full-layout">
                        <div class="card glass-card gallery-split-card" style="height: 100%;">
                            <div class="gallery-split-layout">
                                <div class="gallery-sidebar">
                                    <div class="gallery-sidebar-title">Categories</div>
                                    <div class="gallery-category-list" id="gallery-classify-tabs" role="tablist">
                                        <button class="cat-btn active" data-style="18">Recommend</button>
                                        <button class="cat-btn" data-style="0">New</button>
                                        <button class="cat-btn" data-style="3">Cartoon</button>
                                        <button class="cat-btn" data-style="17">Holiday</button>
                                        <button class="cat-btn" data-style="4">Emoji</button>
                                        <button class="cat-btn" data-style="8">Pattern</button>
                                        <button class="cat-btn" data-style="9">Creative</button>
                                        <button class="cat-btn" data-style="6">Nature</button>
                                        <button class="cat-btn" data-style="5">Everyday</button>
                                        <button class="cat-btn" data-style="15">Dawu</button>
                                        <button class="cat-btn" data-style="7">Symbol</button>
                                        <button class="cat-btn" data-style="16">Business</button>
                                        <button class="cat-btn" data-style="1">Default</button>
                                        <button class="cat-btn" data-style="40">AI</button>
                                        <button class="cat-btn" data-style="12">Photo</button>
                                        <button class="cat-btn" data-style="19">Planet</button>
                                    </div>
                                </div>
                                <div class="gallery-main">
                                    <div class="gallery-controls-row" style="display:flex; gap:10px; align-items:center; flex-shrink:0; justify-content:flex-end;">
                                        <div class="tabs-row" role="tablist" id="gallery-sort-tabs" style="margin:0;">
                                            <button class="tab-btn active" data-sort="1">Popular</button>
                                            <button class="tab-btn" data-sort="0">Latest</button>
                                        </div>
                                        <select id="gallery-size-select" class="custom-select small" style="width:auto; flex-shrink:0;">
                                            <option value="0">Auto</option>
                                            <option value="1">16×16</option>
                                            <option value="2">32×32</option>
                                            <option value="4">64×64</option>
                                            <option value="16">128×128</option>
                                            <option value="32">256×256</option>
                                            <option value="127">All</option>
                                        </select>
                                    </div>
                                    <div class="gallery-grid" id="gallery-container" style="flex:1; overflow-y:auto; min-height:0;">
                                        <div class="empty-list">Loading community gallery...</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- HOT CHANNEL sub-tab -->
                <div class="pixel-subtab-content" id="pixel-hot-channel">
                    <div class="hot-channel-layout">
                        <div class="card glass-card" style="height: 100%;">
                            <div class="card-body">
                                <div id="hot-preview-area" class="hot-preview-area" style="margin-bottom:12px;">
                                    <div id="hot-preview-list" class="hot-preview-list">
                                        <div class="hot-preview-empty">Loading hot channel manifest...</div>
                                    </div>
                                </div>
                                <div class="gallery-actions flex gap-10" style="margin-top:auto; flex-direction:column;">
                                    <button id="hot-update-btn" class="glow-btn hot-progress-btn"
                                            title="Store Divoom's curated hot files into the device's Hot channel rotation"
                                            style="width:100%; flex-shrink:0;">
                                        <span id="hot-update-label">Update Hot Channel</span>
                                        <div id="hot-progress-wrap" class="hot-progress-wrap" style="display:none;">
                                            <div id="hot-progress-fill" class="hot-progress-fill"></div>
                                            <span id="hot-progress-text" class="hot-progress-text"></span>
                                        </div>
                                    </button>
                                    <!-- R53: per-device last-checked stamp so the
                                         "up to date" verdict is dated, not blind. -->
                                    <div id="hot-last-checked" class="hot-last-checked"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PLAYLISTS sub-tab -->
                <div class="pixel-subtab-content" id="pixel-playlists">
                    <div class="hot-channel-layout">
                        <div class="card glass-card" style="height: 100%;">
                            <div class="card-body">
                                <p class="panel-hint">Cloud-hosted playlists from your Divoom account. Push one to replace the device's local slideshow.</p>
                                <div id="cloud-playlist-list" class="cloud-clock-list"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PHOTO ALBUMS sub-tab -->
                <div class="pixel-subtab-content" id="pixel-photo-albums">
                    <div class="hot-channel-layout">
                        <div class="card glass-card" style="height: 100%;">
                            <div class="card-body">
                                <p class="panel-hint">Photo albums configured for this device. Play one to start its slideshow.</p>
                                <div id="cloud-photo-album-list" class="cloud-clock-list"></div>
                            </div>
                        </div>
                    </div>
                </div>
    `;
