// spatial_stage.js — Dieter Rams & Susan Kare Spatial Hardware Workbench
// Persistent top-stage controller for multi-device fleet (16x16 & 64x64),
// freeform 2D positioning, live pixel mirrors, and contextual inspector.

(function() {
    'use strict';

    let stageMounted = false;
    let activeDrag = null;
    let selectedMac = null;
    let isWallMode = false;
    let tick = 0;
    const devicePositions = {};
    const deviceRooms = {};
    const deviceBrightness = {};
    let activeRoomFilter = 'all';

    function initSpatialStage() {
        if (stageMounted) return;
        const mount = document.getElementById('spatial-stage-mount');
        if (!mount) return;

        // Load saved collapsed state (defaults to true for compact appbar ribbon)
        let isCollapsed = localStorage.getItem('spatial_stage_collapsed') !== 'false';

        function updateStageCollapseState() {
            const ribbonView = document.getElementById('appbar-ribbon-view');
            const benchView = document.getElementById('appbar-bench-view');
            const centerBtn = document.getElementById('stage-center-btn');
            const snapBtn = document.getElementById('stage-snap-btn');
            const toggleText = document.getElementById('stage-toggle-text');

            if (isCollapsed) {
                mount.style.display = 'none';
                if (ribbonView) ribbonView.style.display = 'flex';
                if (benchView) benchView.style.display = 'none';
                if (centerBtn) centerBtn.style.display = 'none';
                if (snapBtn) snapBtn.style.display = 'none';
                if (toggleText) toggleText.textContent = 'Bench';
            } else {
                mount.style.display = 'block';
                if (ribbonView) ribbonView.style.display = 'none';
                if (benchView) benchView.style.display = 'flex';
                if (centerBtn) centerBtn.style.display = 'inline-flex';
                if (snapBtn) snapBtn.style.display = 'inline-flex';
                if (toggleText) toggleText.textContent = 'Ribbon';
                refreshBenchNodes();
            }
        }

        stageMounted = true;
        updateStageCollapseState();

        // Wire stage toggle (Bench <-> Ribbon)
        const toggleBtn = document.getElementById('stage-toggle-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                isCollapsed = !isCollapsed;
                localStorage.setItem('spatial_stage_collapsed', isCollapsed ? 'true' : 'false');
                updateStageCollapseState();
            });
        }

        // Wire center alignment
        const centerBtn = document.getElementById('stage-center-btn');
        if (centerBtn) {
            centerBtn.addEventListener('click', centerDevices);
        }

        // Wire baseline alignment
        const snapBtn = document.getElementById('stage-snap-btn');
        if (snapBtn) {
            snapBtn.addEventListener('click', snapToDesk);
        }

        // Sidebar deck room select
        const roomSelect = document.getElementById('deck-room-select');
        if (roomSelect) {
            roomSelect.addEventListener('change', (e) => {
                if (e.target.value === '__add_new__') {
                    const name = prompt('Enter new room name:');
                    if (name && window.SpatialRooms) {
                        const added = window.SpatialRooms.addRoom(name);
                        if (added && selectedMac) {
                            deviceRooms[selectedMac] = added;
                            window.SpatialRooms.saveDeviceRooms(deviceRooms);
                            window.SpatialRooms.syncTopology(null, devicePositions, deviceRooms);
                        }
                    }
                    if (selectedMac) updateInspector(getSelectedDevice());
                    updateRoomFilterTabs();
                    refreshBenchNodes();
                    return;
                }
                if (!selectedMac) return;
                const newRoom = e.target.value;
                if (newRoom) deviceRooms[selectedMac] = newRoom;
                else delete deviceRooms[selectedMac];
                if (window.SpatialRooms) {
                    window.SpatialRooms.saveDeviceRooms(deviceRooms);
                    window.SpatialRooms.syncTopology(null, devicePositions, deviceRooms);
                } else {
                    try { localStorage.setItem('divoom_stage_rooms', JSON.stringify(deviceRooms)); } catch (_) {}
                }
                updateRoomFilterTabs();
                refreshBenchNodes();
            });
        }

        window.addEventListener('divoom:rooms-updated', () => {
            if (window.SpatialRooms) Object.assign(deviceRooms, window.SpatialRooms.getDeviceRooms());
            updateRoomFilterTabs();
            if (selectedMac) { const dev = getSelectedDevice(); if (dev) updateInspector(dev); }
            refreshBenchNodes();
        });

        // Sidebar deck controls (brightness, volume, power)
        const bSlider = document.getElementById('global-brightness-slider'), bVal = document.getElementById('global-brightness-value');
        if (bSlider) {
            bSlider.addEventListener('input', (e) => {
                const val = parseInt(e.target.value);
                if (bVal) bVal.textContent = val + '%';
                if (selectedMac) { deviceBrightness[selectedMac] = val; try { localStorage.setItem('divoom_stage_brightness', JSON.stringify(deviceBrightness)); } catch (_) {} }
                if (window.pywebview?.api?.set_brightness) window.pywebview.api.set_brightness(val);
            });
        }
        const vSlider = document.getElementById('appbar-volume-slider'), vVal = document.getElementById('appbar-volume-value');
        if (vSlider) {
            vSlider.addEventListener('input', (e) => { if (vVal) vVal.textContent = e.target.value + '/15'; });
            vSlider.addEventListener('change', (e) => { if (window.pywebview?.api?.set_volume) window.pywebview.api.set_volume(parseInt(e.target.value)); });
        }
        const powerBtn = document.getElementById('deck-device-power');
        if (powerBtn) {
            powerBtn.addEventListener('click', () => {
                if (!bSlider) return;
                const next = parseInt(bSlider.value) > 0 ? 0 : 85;
                bSlider.value = next;
                if (bVal) bVal.textContent = next + '%';
                if (selectedMac) { deviceBrightness[selectedMac] = next; try { localStorage.setItem('divoom_stage_brightness', JSON.stringify(deviceBrightness)); } catch (_) {} }
                if (window.pywebview?.api?.set_brightness) window.pywebview.api.set_brightness(next);
            });
        }

        // Load topology, rooms, and brightness from cache & daemon
        if (window.SpatialRooms) {
            Object.assign(devicePositions, window.SpatialRooms.getSavedPositions());
            Object.assign(deviceRooms, window.SpatialRooms.getDeviceRooms());
            window.SpatialRooms.loadTopology();
        } else {
            try {
                const saved = localStorage.getItem('divoom_stage_positions'), r = localStorage.getItem('divoom_stage_rooms');
                if (saved) Object.assign(devicePositions, JSON.parse(saved));
                if (r) Object.assign(deviceRooms, JSON.parse(r));
            } catch (_) {}
        }
        try { const b = localStorage.getItem('divoom_stage_brightness'); if (b) Object.assign(deviceBrightness, JSON.parse(b)); } catch (_) {}

        window.addEventListener('divoom:topology-loaded', (e) => {
            const top = e.detail || {};
            if (top.devices) {
                Object.keys(top.devices).forEach(a => {
                    const d = top.devices[a];
                    if (d && typeof d.x === 'number' && typeof d.y === 'number') devicePositions[a] = { x: d.x, y: d.y };
                    if (d && d.room) deviceRooms[a] = d.room;
                });
            }
            updateRoomFilterTabs();
            refreshBenchNodes();
        });

        refreshBenchNodes();
        startAnimationLoop();
    }

    function getDeviceList() {
        const list = (window.DivoomState && window.DivoomState.discoveredDevices) || [];
        if (list.length > 0) return list;

        // Fallback placeholder fleet for UI preview if no devices scanned yet
        return [
            { address: '11:22:33:44:55:01', name: 'Ditoo-L', model: 'Ditoo', size: 16, room: 'Desk', activityKind: 'clock' },
            { address: '11:22:33:44:55:02', name: 'Timoo-M', model: 'Timoo', size: 16, room: 'Desk', activityKind: 'sysmon' },
            { address: '11:22:33:44:55:03', name: 'Ditoo-R', model: 'Ditoo', size: 16, room: 'Desk', activityKind: 'visualizer' },
            { address: '11:22:33:44:55:04', name: 'Pixoo-64', model: 'Pixoo-64', size: 64, room: 'Wall', activityKind: 'weather' }
        ];
    }

    // Accurate physical dimensions database (mm) & pixel resolution
    const SCALE = 0.65;
    const DIVOOM_SPECS = {
        timoo:     { name: 'Timoo',     w_mm: 82.5, h_mm: 90,  screen_mm: 60,  pw: 16, ph: 16, form: 'timoo' },
        ditoo:     { name: 'Ditoo',     w_mm: 90,   h_mm: 114, screen_mm: 64,  pw: 16, ph: 16, form: 'ditoo' },
        tivoo_max: { name: 'Tivoo-Max', w_mm: 184,  h_mm: 163, screen_mm: 110, pw: 16, ph: 16, form: 'tivoo_max' },
        pixoo:     { name: 'Pixoo',     w_mm: 200,  h_mm: 200, screen_mm: 158, pw: 16, ph: 16, form: 'pixoo' },
        pixoo64:   { name: 'Pixoo-64',  w_mm: 261,  h_mm: 261, screen_mm: 210, pw: 64, ph: 64, form: 'pixoo' }
    };

    function resolveDeviceSpec(dev) {
        const name = (dev.name || '').toLowerCase();
        if (name.includes('64') || dev.size === 64) return DIVOOM_SPECS.pixoo64;
        if (name.includes('max') || name.includes('tivoo-max')) return DIVOOM_SPECS.tivoo_max;
        if (name.includes('timoo')) return DIVOOM_SPECS.timoo;
        if (name.includes('pixoo')) return DIVOOM_SPECS.pixoo;
        return DIVOOM_SPECS.ditoo;
    }

    function getSelectedDevice() {
        const list = getDeviceList();
        return list.find(d => d.address === selectedMac) || list[0];
    }

    function updateRoomFilterTabs() {
        const container = document.getElementById('stage-room-filters');
        if (!container) return;
        if (window.SpatialRooms && typeof window.SpatialRooms.renderFilterPills === 'function') {
            window.SpatialRooms.renderFilterPills(container, activeRoomFilter, (newFilter) => {
                activeRoomFilter = newFilter; updateRoomFilterTabs(); refreshBenchNodes();
            }, getDeviceList());
        }
    }

    function refreshBenchNodes() {
        const bench = document.getElementById('spatial-bench');
        if (!bench) return;
        bench.innerHTML = '';

        const devices = getDeviceList();
        const ribbonChips = document.getElementById('spatial-ribbon-chips');
        if (ribbonChips) ribbonChips.innerHTML = '';
        updateRoomFilterTabs();

        let defaultX = 20;
        devices.forEach((dev, idx) => {
            const addr = dev.address || ('dev-' + idx), spec = resolveDeviceSpec(dev);
            const w = Math.round(spec.w_mm * SCALE), h = Math.round(spec.h_mm * SCALE);
            const sw = Math.round(spec.screen_mm * SCALE), pw = spec.pw, ph = spec.ph;

            let pos = window.SpatialRooms ? window.SpatialRooms.findPosition(devicePositions, addr) : devicePositions[addr];
            if (!pos) pos = { x: defaultX, y: Math.max(10, 160 - h) };
            devicePositions[addr] = pos;
            defaultX += w + 12;

            const isSelected = selectedMac ? (selectedMac === addr) : (idx === 0);
            if (isSelected && !selectedMac) selectedMac = addr;

            const devRoom = deviceRooms[addr] !== undefined ? deviceRooms[addr] : (dev.room || '');
            const isDimmed = (activeRoomFilter !== 'all' && (devRoom || '').toLowerCase() !== activeRoomFilter.toLowerCase());

            // Create node element with model-proportional sizing
            const node = document.createElement('div');
            node.id = `spatial-node-${addr}`;
            node.className = `spatial-node form-${spec.form}` + (isSelected ? ' selected' : '') + (isDimmed ? ' dimmed' : '');
            node.style.left = `${pos.x}px`;
            node.style.top = `${pos.y}px`;
            node.style.width = `${w}px`;
            node.style.height = `${h}px`;
            node.style.zIndex = isSelected ? '20' : '10';

            node.innerHTML = `
                <div class="spatial-node-header" style="width: 100%;">
                    <span class="spatial-node-name" title="${dev.name || spec.name}">${dev.name || spec.name}</span>
                    <span class="spatial-jewel online"></span>
                </div>
                <div class="spatial-node-screen" style="width: ${sw}px; height: ${sw}px; margin: auto;">
                    <canvas id="stage-canvas-${addr}" width="${pw}" height="${ph}" 
                        class="spatial-node-canvas" 
                        style="width: ${sw}px; height: ${sw}px;">
                    </canvas>
                </div>
            `;

            // Node Click Selection & Drag
            node.addEventListener('mousedown', (e) => {
                highlightNode(addr, dev);
                startNodeDrag(e, addr, node, dev);
            });

            bench.appendChild(node);

            // Ribbon chip
            if (ribbonChips) {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'spatial-ribbon-chip' + (isSelected ? ' active' : '');
                chip.innerHTML = `<span class="spatial-jewel online"></span> ${dev.name || 'Screen'}`;
                chip.addEventListener('click', () => selectDevice(addr, dev));
                ribbonChips.appendChild(chip);
            }

            if (isSelected) updateInspector(dev);
        });
    }

    function highlightNode(addr, dev) {
        selectedMac = addr;
        document.querySelectorAll('.spatial-node').forEach(n => { n.classList.remove('selected'); n.style.zIndex = '10'; });
        const activeNode = document.getElementById(`spatial-node-${addr}`);
        if (activeNode) { activeNode.classList.add('selected'); activeNode.style.zIndex = '25'; }
        const bm = document.getElementById('banner-device-mac'), bn = document.getElementById('banner-device-name');
        if (bm) bm.textContent = addr;
        if (bn) { const s = resolveDeviceSpec(dev); bn.textContent = dev.name || s.name; }
        updateInspector(dev);
        updateRibbonSelection();
        if (typeof window.restoreDevicePreview === 'function') window.restoreDevicePreview(addr);
        const act = window.DivoomState?.deviceActivity?.[addr];
        if (act?.kind) {
            const card = document.querySelector(`.tab-btn[data-channel="${act.kind}"]`);
            if (card) {
                document.querySelectorAll('.tab-btn[data-channel]').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                window.DivoomState.activeChannel = act.kind;
            }
        }
    }

    function selectDevice(addr, dev) {
        highlightNode(addr, dev);
        if (typeof window.connectDevice === 'function') {
            window.connectDevice(dev.name || resolveDeviceSpec(dev).name, addr);
        }
    }

    function updateInspector(dev) {
        const spec = resolveDeviceSpec(dev), addr = dev.address || 'dev';
        const nameEl = document.getElementById('deck-device-name'), tagEl = document.getElementById('deck-device-tag');
        const roomSelect = document.getElementById('deck-room-select'), volContainer = document.getElementById('deck-volume-container');
        const bSlider = document.getElementById('global-brightness-slider'), bVal = document.getElementById('global-brightness-value');

        if (nameEl) nameEl.textContent = dev.name || spec.name;
        if (tagEl) tagEl.textContent = `${spec.pw}×${spec.ph}`;
        if (roomSelect) {
            const rm = deviceRooms[addr] !== undefined ? deviceRooms[addr] : (dev.room || '');
            if (window.SpatialRooms) window.SpatialRooms.populateSelect(roomSelect, rm);
            else roomSelect.value = rm;
        }
        if (volContainer) volContainer.style.display = (spec.form !== 'pixoo') ? 'block' : 'none';

        const curB = (deviceBrightness[addr] !== undefined) ? deviceBrightness[addr] : 85;
        if (bSlider) bSlider.value = curB;
        if (bVal) bVal.textContent = curB + '%';
    }

    function updateRibbonSelection() {
        const chips = document.querySelectorAll('.spatial-ribbon-chip');
        const devices = getDeviceList();
        chips.forEach((chip, idx) => {
            const d = devices[idx];
            chip.classList.toggle('active', !!(d && d.address === selectedMac));
        });
    }

    function startNodeDrag(e, addr, node, dev) {
        if (e.button !== 0) return;
        const bench = document.getElementById('spatial-bench');
        if (!bench) return;
        activeDrag = {
            addr, dev, node, startX: e.clientX, startY: e.clientY,
            initialX: devicePositions[addr] ? devicePositions[addr].x : 0,
            initialY: devicePositions[addr] ? devicePositions[addr].y : 0,
            benchWidth: bench.clientWidth, benchHeight: bench.clientHeight,
            nodeWidth: node.offsetWidth, nodeHeight: node.offsetHeight, hasMoved: false
        };
        window.addEventListener('mousemove', onNodeDrag);
        window.addEventListener('mouseup', endNodeDrag);
        e.preventDefault();
    }

    function onNodeDrag(e) {
        if (!activeDrag) return;
        const dx = e.clientX - activeDrag.startX, dy = e.clientY - activeDrag.startY;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) activeDrag.hasMoved = true;
        const nx = Math.max(0, Math.min(activeDrag.benchWidth - activeDrag.nodeWidth, activeDrag.initialX + dx));
        const ny = Math.max(0, Math.min(activeDrag.benchHeight - activeDrag.nodeHeight, activeDrag.initialY + dy));
        if (!devicePositions[activeDrag.addr]) devicePositions[activeDrag.addr] = {};
        devicePositions[activeDrag.addr].x = nx;
        devicePositions[activeDrag.addr].y = ny;
        activeDrag.node.style.left = `${nx}px`;
        activeDrag.node.style.top = `${ny}px`;
    }

    function endNodeDrag(e) {
        if (activeDrag) {
            if (!activeDrag.hasMoved && typeof window.connectDevice === 'function') {
                window.connectDevice(activeDrag.dev.name || resolveDeviceSpec(activeDrag.dev).name, activeDrag.addr);
            } else if (window.SpatialRooms) {
                window.SpatialRooms.savePositions(devicePositions, deviceRooms);
            } else {
                try { localStorage.setItem('divoom_stage_positions', JSON.stringify(devicePositions)); } catch (_) {}
            }
        }
        activeDrag = null;
        window.removeEventListener('mousemove', onNodeDrag);
        window.removeEventListener('mouseup', endNodeDrag);
    }

    function centerDevices() {
        const devs = getDeviceList(), bench = document.getElementById('spatial-bench');
        if (!devs.length || !bench) return;
        let minX = Infinity, maxX = -Infinity;
        devs.forEach(d => {
            const a = d.address || 'dev', p = devicePositions[a] || { x: 20, y: 50 };
            const w = Math.round(resolveDeviceSpec(d).w_mm * SCALE);
            if (p.x < minX) minX = p.x;
            if (p.x + w > maxX) maxX = p.x + w;
        });
        if (minX === Infinity) return;
        const dx = Math.max(10, Math.round((bench.clientWidth - (maxX - minX)) / 2)) - minX;
        devs.forEach(d => { const a = d.address || 'dev'; if (devicePositions[a]) devicePositions[a].x += dx; });
        if (window.SpatialRooms) window.SpatialRooms.savePositions(devicePositions, deviceRooms);
        else try { localStorage.setItem('divoom_stage_positions', JSON.stringify(devicePositions)); } catch (_) {}
        refreshBenchNodes();
    }

    function snapToDesk() {
        let curX = 20;
        getDeviceList().forEach((dev) => {
            const addr = dev.address || 'dev', spec = resolveDeviceSpec(dev);
            devicePositions[addr] = { x: curX, y: Math.max(10, 165 - Math.round(spec.h_mm * SCALE)) };
            curX += Math.round(spec.w_mm * SCALE) + 12;
        });
        if (window.SpatialRooms) window.SpatialRooms.savePositions(devicePositions, deviceRooms);
        else try { localStorage.setItem('divoom_stage_positions', JSON.stringify(devicePositions)); } catch (_) {}
        refreshBenchNodes();
    }

    const previewImgCache = new Map();

    function startAnimationLoop() {
        function renderLoop() {
            tick++;
            getDeviceList().forEach((dev, idx) => {
                const addr = dev.address || ('dev-' + idx);
                const cvs = document.getElementById(`stage-canvas-${addr}`);
                if (!cvs) return;
                const ctx = cvs.getContext('2d');
                ctx.imageSmoothingEnabled = false;

                const wallSlot = window.DivoomState?.assignedSlots?.[addr];
                const act = (window.DivoomState && window.DivoomState.deviceActivity && window.DivoomState.deviceActivity[addr]) || {};
                let src = (wallSlot && wallSlot.preview) || (window.DivoomState && window.DivoomState.devicePreviews && window.DivoomState.devicePreviews[addr]) || act.src;
                const kind = act.kind || dev.activityKind || (addr === selectedMac ? window.DivoomState.activeChannel : null);
                if (!src && wallSlot && window._renderWallSlotSVG) {
                    src = window._renderWallSlotSVG(wallSlot, addr);
                } else if (!src && window._channelPreviewSVG) {
                    src = window._channelPreviewSVG(kind || 'clock', act.opts || { defaultColor: '#00cc66' });
                }

                let entry = previewImgCache.get(addr);
                if (src && (!entry || entry.src !== src)) {
                    const img = new Image();
                    entry = { src, img, loaded: false };
                    img.onload = () => { entry.loaded = true; };
                    img.src = src;
                    previewImgCache.set(addr, entry);
                }

                ctx.fillStyle = '#07080a';
                ctx.fillRect(0, 0, cvs.width, cvs.height);

                if (entry && entry.loaded) {
                    ctx.drawImage(entry.img, 0, 0, cvs.width, cvs.height);
                } else if (kind === 'sysmon') {
                    ctx.fillStyle = '#00cc66';
                    for (let x = 1; x < 15; x += 2) {
                        const h = Math.round(3 + 2.5 * Math.sin(x * 0.4 + tick * 0.1));
                        for (let y = 14; y > 14 - h; y--) ctx.fillRect(x, y, 1, 1);
                    }
                } else if (kind === 'visualizer' || kind === 'eq') {
                    for (let x = 0; x < 16; x++) {
                        const h = Math.round(4 + 3.5 * Math.cos(x * 0.35 + tick * 0.12));
                        for (let y = 0; y < h; y++) {
                            ctx.fillStyle = y > 8 ? '#ff5a1f' : y > 4 ? '#ffcc00' : '#00cc66';
                            ctx.fillRect(x, 15 - y, 1, 1);
                        }
                    }
                } else {
                    const c = (act.opts && act.opts.color) || '#ffffff';
                    ctx.fillStyle = c;
                    ctx.fillRect(2, 5, 1, 6); ctx.fillRect(5, 5, 3, 1); ctx.fillRect(5, 6, 1, 4); ctx.fillRect(7, 6, 1, 4); ctx.fillRect(5, 10, 3, 1);
                    if (Math.floor(tick / 25) % 2 === 0) { ctx.fillRect(9, 7, 1, 1); ctx.fillRect(9, 9, 1, 1); }
                    ctx.fillRect(11, 5, 1, 4); ctx.fillRect(13, 5, 1, 6); ctx.fillRect(11, 8, 3, 1);
                }
            });
            requestAnimationFrame(renderLoop);
        }
        renderLoop();
    }

    // Expose API
    window.SpatialStage = { init: initSpatialStage, refresh: refreshBenchNodes, snap: snapToDesk, center: centerDevices, getSelectedMac: () => selectedMac };

    // Auto-init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSpatialStage);
    } else {
        setTimeout(initSpatialStage, 50);
    }
})();
