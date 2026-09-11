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
        const mainContent = document.querySelector('.main-content');
        if (!mainContent) return;

        // Load saved collapsed state
        const isCollapsed = localStorage.getItem('spatial_stage_collapsed') === 'true';

        // Container wrapper
        const wrapper = document.createElement('div');
        wrapper.id = 'spatial-stage-wrapper';
        wrapper.className = 'spatial-stage-wrapper' + (isCollapsed ? ' hidden' : '');
        if (isCollapsed) wrapper.style.display = 'none';

        // Stage Header
        const header = document.createElement('div');
        header.className = 'spatial-stage-header';
        header.innerHTML = `
            <div class="spatial-stage-title-area">
                <span class="spatial-jewel online"></span>
                <span class="spatial-stage-title">BENCH</span>
                <div id="stage-room-filters" class="stage-room-filters"></div>
            </div>
            <div class="spatial-stage-actions">
                <button id="stage-snap-btn" class="stage-btn" type="button" title="Align to desk baseline">
                    <svg class="kare-icon" viewBox="0 0 16 16"><rect x="2" y="2" width="4" height="4" fill="currentColor"/><rect x="10" y="2" width="4" height="4" fill="currentColor"/><rect x="2" y="10" width="4" height="4" fill="currentColor"/><rect x="10" y="10" width="4" height="4" fill="currentColor"/></svg> Align
                </button>
                <button id="stage-collapse-btn" class="stage-btn" type="button" title="Collapse to ribbon">
                    <svg class="kare-icon" viewBox="0 0 16 16"><rect x="2" y="4" width="12" height="8" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="5" cy="8" r="2"/></svg> Ribbon
                </button>
            </div>
        `;
        wrapper.appendChild(header);

        // 2D Bench Canvas
        const bench = document.createElement('div');
        bench.id = 'spatial-bench';
        bench.className = 'spatial-bench';
        wrapper.appendChild(bench);

        // Contextual Inspector Strip
        const inspector = document.createElement('div');
        inspector.id = 'spatial-inspector';
        inspector.className = 'spatial-inspector';
        inspector.innerHTML = `
            <div class="spatial-inspector-left">
                <span class="spatial-jewel online" id="insp-dot"></span>
                <span class="spatial-inspector-name" id="insp-name">Screen</span>
                <span class="spatial-inspector-tag" id="insp-model">16×16</span>
                <select id="insp-room-select" class="spatial-room-select" title="Assign Room">
                    <option value="Desk">Desk</option>
                    <option value="Shelf">Shelf</option>
                    <option value="Wall">Wall</option>
                    <option value="Studio">Studio</option>
                </select>
                <span id="insp-channel" style="font-family: var(--font-mono); font-size: 10px; color: var(--primary);">Clock</span>
            </div>
            <div class="spatial-inspector-right">
                <div class="spatial-brightness-control">
                    <svg class="kare-icon" viewBox="0 0 16 16" style="color: var(--text-muted);"><circle cx="8" cy="8" r="3" fill="currentColor"/><line x1="8" y1="1" x2="8" y2="3" stroke="currentColor" stroke-width="1.5"/><line x1="8" y1="13" x2="8" y2="15" stroke="currentColor" stroke-width="1.5"/><line x1="1" y1="8" x2="3" y2="8" stroke="currentColor" stroke-width="1.5"/><line x1="13" y1="8" x2="15" y2="8" stroke="currentColor" stroke-width="1.5"/></svg>
                    <input type="range" id="stage-brightness-slider" min="5" max="100" value="85" class="spatial-slider">
                    <span id="stage-brightness-val" style="font-family: var(--font-mono); font-size: 10px; min-width: 28px; text-align: right;">85%</span>
                </div>
            </div>
        `;
        wrapper.appendChild(inspector);

        // Compact Ribbon View
        const ribbon = document.createElement('div');
        ribbon.id = 'spatial-stage-ribbon';
        ribbon.className = 'spatial-ribbon' + (!isCollapsed ? ' hidden' : '');
        if (!isCollapsed) ribbon.style.display = 'none';
        ribbon.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-family: var(--font-display); font-weight: 700; font-size: 11px; color: var(--text-muted);">STAGE:</span>
                <div id="spatial-ribbon-chips" class="spatial-ribbon-chips"></div>
            </div>
            <button id="stage-expand-btn" class="stage-btn" type="button">Expand Bench</button>
        `;

        // Mount at top of mainContent before first child
        mainContent.insertBefore(ribbon, mainContent.firstChild);
        mainContent.insertBefore(wrapper, mainContent.firstChild);
        stageMounted = true;

        // Wire event handlers
        document.getElementById('stage-collapse-btn').addEventListener('click', () => {
            wrapper.style.display = 'none';
            ribbon.style.display = 'flex';
            localStorage.setItem('spatial_stage_collapsed', 'true');
        });

        document.getElementById('stage-expand-btn').addEventListener('click', () => {
            ribbon.style.display = 'none';
            wrapper.style.display = 'flex';
            localStorage.setItem('spatial_stage_collapsed', 'false');
            refreshBenchNodes();
        });

        document.getElementById('stage-snap-btn').addEventListener('click', snapToDesk);

        const roomSelect = document.getElementById('insp-room-select');
        if (roomSelect) {
            roomSelect.addEventListener('change', (e) => {
                if (!selectedMac) return;
                deviceRooms[selectedMac] = e.target.value;
                try { localStorage.setItem('divoom_stage_rooms', JSON.stringify(deviceRooms)); } catch (_) {}
                updateRoomFilterTabs();
                refreshBenchNodes();
            });
        }

        const bSlider = document.getElementById('stage-brightness-slider');
        const bVal = document.getElementById('stage-brightness-val');
        bSlider.addEventListener('input', (e) => {
            const val = parseInt(e.target.value);
            bVal.textContent = val + '%';
            if (selectedMac) {
                deviceBrightness[selectedMac] = val;
                try { localStorage.setItem('divoom_stage_brightness', JSON.stringify(deviceBrightness)); } catch (_) {}
            }
            if (window.pywebview && window.pywebview.api && window.pywebview.api.set_brightness) {
                window.pywebview.api.set_brightness(val);
            }
        });

        // Load topology, rooms, and brightness from local cache
        try {
            const saved = localStorage.getItem('divoom_stage_positions');
            if (saved) Object.assign(devicePositions, JSON.parse(saved));
            const r = localStorage.getItem('divoom_stage_rooms');
            if (r) Object.assign(deviceRooms, JSON.parse(r));
            const b = localStorage.getItem('divoom_stage_brightness');
            if (b) Object.assign(deviceBrightness, JSON.parse(b));
        } catch (_) {}

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
        if (name.includes('64')) return DIVOOM_SPECS.pixoo64;
        if (name.includes('max') || name.includes('tivoo-max')) return DIVOOM_SPECS.tivoo_max;
        if (name.includes('timoo')) return DIVOOM_SPECS.timoo;
        if (name.includes('ditoo')) return DIVOOM_SPECS.ditoo;
        if (name.includes('pixoo')) return DIVOOM_SPECS.pixoo;
        if (dev.size === 64) return DIVOOM_SPECS.pixoo64;
        return DIVOOM_SPECS.ditoo;
    }

    function updateRoomFilterTabs() {
        const container = document.getElementById('stage-room-filters');
        if (!container) return;
        const devices = getDeviceList();
        const rooms = new Set(['Desk']);
        devices.forEach(d => {
            const addr = d.address || 'dev';
            rooms.add(deviceRooms[addr] || d.room || 'Desk');
        });
        const list = ['all', ...Array.from(rooms)];
        container.innerHTML = list.map(r => `
            <button type="button" class="stage-room-pill ${activeRoomFilter === r ? 'active' : ''}" data-room="${r}">
                ${r === 'all' ? 'All' : r}
            </button>
        `).join('');
        container.querySelectorAll('.stage-room-pill').forEach(btn => {
            btn.addEventListener('click', (e) => {
                activeRoomFilter = e.currentTarget.dataset.room;
                updateRoomFilterTabs();
                refreshBenchNodes();
            });
        });
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
            const addr = dev.address || ('dev-' + idx);
            const spec = resolveDeviceSpec(dev);
            const w = Math.round(spec.w_mm * SCALE);
            const h = Math.round(spec.h_mm * SCALE);
            const sw = Math.round(spec.screen_mm * SCALE);
            const pw = spec.pw;
            const ph = spec.ph;

            if (!devicePositions[addr]) {
                const baselineY = Math.max(10, 160 - h);
                devicePositions[addr] = { x: defaultX, y: baselineY };
            }
            const pos = devicePositions[addr];
            defaultX += w + 12;

            const isSelected = selectedMac ? (selectedMac === addr) : (idx === 0);
            if (isSelected && !selectedMac) selectedMac = addr;

            const devRoom = deviceRooms[addr] || dev.room || 'Desk';
            const isDimmed = (activeRoomFilter !== 'all' && devRoom !== activeRoomFilter);

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
                selectDevice(addr, dev);
                startNodeDrag(e, addr, node);
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

    function selectDevice(addr, dev) {
        selectedMac = addr;
        document.querySelectorAll('.spatial-node').forEach(n => {
            n.classList.remove('selected');
            n.style.zIndex = '10';
        });
        const activeNode = document.getElementById(`spatial-node-${addr}`);
        if (activeNode) {
            activeNode.classList.add('selected');
            activeNode.style.zIndex = '25';
        }

        // Switch active device in pywebview / app state
        if (typeof window.connectDevice === 'function') {
            const spec = resolveDeviceSpec(dev);
            window.connectDevice(dev.name || spec.name, addr);
        }

        updateInspector(dev);
        updateRibbonSelection();
    }

    function updateInspector(dev) {
        const spec = resolveDeviceSpec(dev);
        const inspName = document.getElementById('insp-name');
        const inspModel = document.getElementById('insp-model');
        const inspChannel = document.getElementById('insp-channel');
        const inspRoom = document.getElementById('insp-room-select');
        const bSlider = document.getElementById('stage-brightness-slider');
        const bVal = document.getElementById('stage-brightness-val');

        const addr = dev.address || 'dev';
        if (inspName) inspName.textContent = dev.name || spec.name;
        if (inspModel) inspModel.textContent = `${spec.pw}×${spec.ph}`;
        if (inspChannel) inspChannel.textContent = dev.activityKind || 'Clock';
        if (inspRoom) inspRoom.value = deviceRooms[addr] || dev.room || 'Desk';

        const curB = (deviceBrightness[addr] !== undefined) ? deviceBrightness[addr] : 85;
        if (bSlider) bSlider.value = curB;
        if (bVal) bVal.textContent = curB + '%';
    }

    function updateRibbonSelection() {
        const chips = document.querySelectorAll('.spatial-ribbon-chip');
        const devices = getDeviceList();
        chips.forEach((chip, idx) => {
            const d = devices[idx];
            if (d && (d.address === selectedMac)) {
                chip.classList.add('active');
            } else {
                chip.classList.remove('active');
            }
        });
    }

    function startNodeDrag(e, addr, node) {
        if (e.button !== 0) return;
        const bench = document.getElementById('spatial-bench');
        if (!bench) return;

        activeDrag = {
            addr,
            node,
            startX: e.clientX,
            startY: e.clientY,
            initialX: devicePositions[addr] ? devicePositions[addr].x : 0,
            initialY: devicePositions[addr] ? devicePositions[addr].y : 0,
            benchWidth: bench.clientWidth,
            benchHeight: bench.clientHeight,
            nodeWidth: node.offsetWidth,
            nodeHeight: node.offsetHeight
        };

        window.addEventListener('mousemove', onNodeDrag);
        window.addEventListener('mouseup', endNodeDrag);
        e.preventDefault();
    }

    function onNodeDrag(e) {
        if (!activeDrag) return;
        const dx = e.clientX - activeDrag.startX;
        const dy = e.clientY - activeDrag.startY;

        let nx = Math.max(0, Math.min(activeDrag.benchWidth - activeDrag.nodeWidth, activeDrag.initialX + dx));
        let ny = Math.max(0, Math.min(activeDrag.benchHeight - activeDrag.nodeHeight, activeDrag.initialY + dy));

        if (!devicePositions[activeDrag.addr]) devicePositions[activeDrag.addr] = {};
        devicePositions[activeDrag.addr].x = nx;
        devicePositions[activeDrag.addr].y = ny;

        activeDrag.node.style.left = `${nx}px`;
        activeDrag.node.style.top = `${ny}px`;
    }

    function endNodeDrag() {
        if (activeDrag) {
            try {
                localStorage.setItem('divoom_stage_positions', JSON.stringify(devicePositions));
            } catch (_) {}
        }
        activeDrag = null;
        window.removeEventListener('mousemove', onNodeDrag);
        window.removeEventListener('mouseup', endNodeDrag);
    }

    function snapToDesk() {
        const devices = getDeviceList();
        let curX = 20;
        devices.forEach((dev) => {
            const addr = dev.address || 'dev';
            const spec = resolveDeviceSpec(dev);
            const w = Math.round(spec.w_mm * SCALE);
            const h = Math.round(spec.h_mm * SCALE);
            devicePositions[addr] = { x: curX, y: Math.max(10, 165 - h) };
            curX += w + 12;
        });
        try {
            localStorage.setItem('divoom_stage_positions', JSON.stringify(devicePositions));
        } catch (_) {}
        refreshBenchNodes();
    }

    // Live canvas rendering loop
    function startAnimationLoop() {
        function renderLoop() {
            tick++;
            getDeviceList().forEach((dev, idx) => {
                const addr = dev.address || ('dev-' + idx);
                const cvs = document.getElementById(`stage-canvas-${addr}`);
                if (!cvs) return;
                const ctx = cvs.getContext('2d');
                ctx.fillStyle = '#07080a';
                ctx.fillRect(0, 0, cvs.width, cvs.height);
                const kind = dev.activityKind || 'clock';
                if (kind === 'clock') {
                    ctx.fillStyle = '#ff5a1f';
                    ctx.fillRect(2, 5, 1, 6);
                    ctx.fillRect(5, 5, 3, 1); ctx.fillRect(5, 6, 1, 4); ctx.fillRect(7, 6, 1, 4); ctx.fillRect(5, 10, 3, 1);
                    if (Math.floor(tick / 25) % 2 === 0) { ctx.fillRect(9, 7, 1, 1); ctx.fillRect(9, 9, 1, 1); }
                    ctx.fillRect(11, 5, 1, 4); ctx.fillRect(13, 5, 1, 6); ctx.fillRect(11, 8, 3, 1);
                } else if (kind === 'sysmon') {
                    ctx.fillStyle = '#00cc66';
                    for (let x = 1; x < 15; x += 2) {
                        const h = Math.round(3 + 2.5 * Math.sin(x * 0.4 + tick * 0.1));
                        for (let y = 14; y > 14 - h; y--) ctx.fillRect(x, y, 1, 1);
                    }
                } else if (kind === 'visualizer') {
                    for (let x = 0; x < 16; x++) {
                        const h = Math.round(4 + 3.5 * Math.cos(x * 0.35 + tick * 0.12));
                        for (let y = 0; y < h; y++) {
                            ctx.fillStyle = y > 8 ? '#ff5a1f' : y > 4 ? '#ffcc00' : '#00cc66';
                            ctx.fillRect(x, 15 - y, 1, 1);
                        }
                    }
                } else if (cvs.width === 64) {
                    ctx.strokeStyle = '#1e293b'; ctx.strokeRect(6, 6, 52, 52);
                    ctx.fillStyle = '#38bdf8';
                    for (let i = 0; i < 20; i++) {
                        ctx.fillRect(Math.round(32 + 16 * Math.cos(i * 0.3 + tick * 0.02)),
                                     Math.round(32 + 12 * Math.sin(i * 0.35 + tick * 0.02)), 2, 2);
                    }
                } else {
                    ctx.fillStyle = '#ff5a1f'; ctx.fillRect(5, 5, 6, 6);
                }
            });
            requestAnimationFrame(renderLoop);
        }
        renderLoop();
    }

    // Expose API
    window.SpatialStage = {
        init: initSpatialStage,
        refresh: refreshBenchNodes,
        snap: snapToDesk
    };

    // Auto-init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSpatialStage);
    } else {
        setTimeout(initSpatialStage, 50);
    }
})();
