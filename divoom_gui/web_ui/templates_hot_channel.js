/* templates_hot_channel.js — Hot Channel panel template (Divoom's curated set) */
window.DivoomTemplates = window.DivoomTemplates || {};
window.DivoomTemplates.hotChannel = `                <div class="hot-channel-layout">
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
                            </div>
                        </div>
                    </div>
                </div>
    `;
