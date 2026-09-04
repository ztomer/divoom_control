/* templates_gallery.js — Community Gallery panel template */
window.DivoomTemplates = window.DivoomTemplates || {};
window.DivoomTemplates.gallery = `                <div class="gallery-full-layout">
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
                                <!-- View controls live on the right edge: categories (left
                                     sidebar) say WHAT to browse, these say HOW it's shown.
                                     Rams: secondary controls stay quiet; Kare: one consistent
                                     corner to find them. -->
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
    `;
