/**
 * spatial_rooms.js — Room lifecycle & management engine
 * Dieter Rams & Susan Kare inspired room grouping and spatial filtering.
 * Manages custom rooms, default Desk baseline, and persistence across
 * localStorage and divoomd topology.
 */
(function() {
    'use strict';

    const DEFAULT_ROOMS = ['Desk', 'Shelf', 'Wall'];
    const STORAGE_KEY = 'divoom_stage_room_list';
    const DEVICE_ROOMS_KEY = 'divoom_stage_rooms';
    const POSITIONS_KEY = 'divoom_stage_positions';

    function getRooms() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed) && parsed.length > 0) {
                    if (!parsed.includes('Desk')) parsed.unshift('Desk');
                    return parsed;
                }
            }
        } catch (_) {}
        return [...DEFAULT_ROOMS];
    }

    function getSavedPositions() {
        try {
            const raw = localStorage.getItem(POSITIONS_KEY);
            if (raw) return JSON.parse(raw);
        } catch (_) {}
        return {};
    }

    function findPosition(positions, mac) {
        if (!positions || !mac) return null;
        if (positions[mac]) return positions[mac];
        const lower = mac.toLowerCase();
        if (positions[lower]) return positions[lower];
        const upper = mac.toUpperCase();
        if (positions[upper]) return positions[upper];
        return null;
    }

    function saveRooms(rooms) {
        if (!rooms.includes('Desk')) rooms.unshift('Desk');
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(rooms));
        } catch (_) {}
        syncTopology(rooms);
    }

    function syncTopology(rooms, positions, devRooms) {
        const rms = rooms || getRooms();
        const posMap = positions || getSavedPositions();
        const roomMap = devRooms || getDeviceRooms();

        const devices = {};
        Object.keys(posMap).forEach(addr => {
            const p = posMap[addr];
            if (p && typeof p.x === 'number' && typeof p.y === 'number') {
                devices[addr] = {
                    x: p.x,
                    y: p.y,
                    room: roomMap[addr] || 'Desk'
                };
            }
        });

        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_topology) {
            try {
                window.pywebview.api.set_topology({
                    rooms: rms,
                    devices: devices,
                    wall_linked: true
                });
            } catch (_) {}
        }
    }

    async function loadTopology() {
        if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_topology) {
            return null;
        }
        try {
            const reply = await window.pywebview.api.get_topology();
            if (!reply || !reply.success) return null;
            const top = reply.topology || {};

            if (Array.isArray(top.rooms) && top.rooms.length > 0) {
                const current = getRooms();
                top.rooms.forEach(r => {
                    if (r && !current.some(c => c.toLowerCase() === r.toLowerCase())) {
                        current.push(r);
                    }
                });
                if (!current.includes('Desk')) current.unshift('Desk');
                try { localStorage.setItem(STORAGE_KEY, JSON.stringify(current)); } catch (_) {}
            }

            if (top.devices && typeof top.devices === 'object') {
                const posMap = getSavedPositions();
                const roomMap = getDeviceRooms();
                let changedPos = false;
                let changedRooms = false;

                Object.keys(top.devices).forEach(addr => {
                    const dev = top.devices[addr];
                    if (dev && typeof dev.x === 'number' && typeof dev.y === 'number') {
                        posMap[addr] = { x: dev.x, y: dev.y };
                        changedPos = true;
                    }
                    if (dev && dev.room) {
                        roomMap[addr] = dev.room;
                        changedRooms = true;
                    }
                });

                if (changedPos) {
                    try { localStorage.setItem(POSITIONS_KEY, JSON.stringify(posMap)); } catch (_) {}
                }
                if (changedRooms) {
                    try { localStorage.setItem(DEVICE_ROOMS_KEY, JSON.stringify(roomMap)); } catch (_) {}
                }
            }

            window.dispatchEvent(new CustomEvent('divoom:topology-loaded', { detail: top }));
            return top;
        } catch (_) {
            return null;
        }
    }

    function savePositions(positions, devRooms) {
        try {
            localStorage.setItem(POSITIONS_KEY, JSON.stringify(positions));
        } catch (_) {}
        syncTopology(null, positions, devRooms);
    }

    function getDeviceRooms() {
        try {
            const raw = localStorage.getItem(DEVICE_ROOMS_KEY);
            if (raw) return JSON.parse(raw);
        } catch (_) {}
        return {};
    }

    function saveDeviceRooms(map) {
        try {
            localStorage.setItem(DEVICE_ROOMS_KEY, JSON.stringify(map));
        } catch (_) {}
    }

    function addRoom(name) {
        if (!name) return false;
        const clean = name.trim();
        if (!clean || clean.length > 24) return false;

        const rooms = getRooms();
        const exists = rooms.some(r => r.toLowerCase() === clean.toLowerCase());
        if (exists) return false;

        rooms.push(clean);
        saveRooms(rooms);
        window.dispatchEvent(new CustomEvent('divoom:rooms-updated', { detail: { action: 'add', room: clean } }));
        return clean;
    }

    function removeRoom(name) {
        if (!name || name.toLowerCase() === 'desk') return false;
        const clean = name.trim();
        let rooms = getRooms();
        if (!rooms.includes(clean)) return false;

        rooms = rooms.filter(r => r.toLowerCase() !== clean.toLowerCase());
        saveRooms(rooms);

        // Reassign any devices in the deleted room to 'Desk'
        const devRooms = getDeviceRooms();
        let changed = false;
        Object.keys(devRooms).forEach(addr => {
            if (devRooms[addr] && devRooms[addr].toLowerCase() === clean.toLowerCase()) {
                devRooms[addr] = 'Desk';
                changed = true;
            }
        });
        if (changed) saveDeviceRooms(devRooms);

        window.dispatchEvent(new CustomEvent('divoom:rooms-updated', { detail: { action: 'remove', room: clean } }));
        return true;
    }

    function populateSelect(selectEl, currentRoom) {
        if (!selectEl) return;
        const rooms = getRooms();
        const val = (currentRoom !== undefined && currentRoom !== null) ? currentRoom : '';

        selectEl.innerHTML = '';

        const unassignedOpt = document.createElement('option');
        unassignedOpt.value = '';
        unassignedOpt.textContent = '(Unassigned / No Room)';
        if (!val || val === 'unassigned') unassignedOpt.selected = true;
        selectEl.appendChild(unassignedOpt);

        rooms.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.textContent = r;
            if (r.toLowerCase() === val.toLowerCase()) opt.selected = true;
            selectEl.appendChild(opt);
        });

        const addOpt = document.createElement('option');
        addOpt.value = '__add_new__';
        addOpt.textContent = '+ Add Room...';
        selectEl.appendChild(addOpt);
    }

    function renderFilterPills(containerEl, activeFilter, onFilterChange, deviceList) {
        if (!containerEl) return;
        containerEl.innerHTML = '';

        const rooms = getRooms();
        const allFilters = ['all', ...rooms];
        const devRooms = getDeviceRooms();
        const devices = Array.isArray(deviceList) ? deviceList : [];
        const counts = { all: devices.length };
        rooms.forEach(r => { counts[r] = 0; });
        devices.forEach(d => {
            const r = devRooms[d.address] !== undefined ? devRooms[d.address] : (d.room || '');
            if (r) {
                const match = rooms.find(rm => rm.toLowerCase() === r.toLowerCase());
                if (match) counts[match] = (counts[match] || 0) + 1;
            }
        });

        allFilters.forEach(r => {
            const isAll = (r === 'all');
            const isActive = (activeFilter.toLowerCase() === r.toLowerCase());
            const pill = document.createElement('div');
            pill.className = `stage-room-pill ${isActive ? 'active' : ''}`;
            pill.dataset.room = r;

            const label = document.createElement('span');
            label.className = 'stage-room-pill-label';
            label.textContent = isAll ? 'All' : r;
            pill.appendChild(label);

            const countSpan = document.createElement('span');
            countSpan.className = 'stage-room-pill-count';
            countSpan.textContent = `(${counts[r] !== undefined ? counts[r] : 0})`;
            pill.appendChild(countSpan);

            // Allow deletion for custom rooms (not All and not default Desk)
            if (!isAll && r.toLowerCase() !== 'desk') {
                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'stage-room-del-btn';
                delBtn.title = `Delete ${r} room`;
                delBtn.setAttribute('aria-label', `Delete ${r} room`);
                delBtn.textContent = '×';
                delBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (confirm(`Remove room "${r}"? Devices in this room will move to Desk.`)) {
                        removeRoom(r);
                        if (typeof onFilterChange === 'function') {
                            onFilterChange(activeFilter.toLowerCase() === r.toLowerCase() ? 'all' : activeFilter);
                        }
                    }
                });
                pill.appendChild(delBtn);
            }

            pill.addEventListener('click', () => {
                if (typeof onFilterChange === 'function') {
                    onFilterChange(r);
                }
            });

            containerEl.appendChild(pill);
        });

        // Manage Devices button when a specific room is selected
        if (activeFilter !== 'all') {
            const manageBtn = document.createElement('button');
            manageBtn.type = 'button';
            manageBtn.className = 'stage-room-manage-btn';
            manageBtn.title = `Add or remove devices in ${activeFilter}`;
            manageBtn.setAttribute('aria-label', `Add or remove devices in ${activeFilter}`);
            manageBtn.innerHTML = '<svg class="kare-icon" viewBox="0 0 16 16"><circle cx="4" cy="4" r="2" fill="currentColor"/><circle cx="12" cy="4" r="2" fill="currentColor"/><circle cx="8" cy="11" r="2" fill="currentColor"/></svg> Devices';
            manageBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                showRoomDevicesPopover(containerEl, activeFilter, devices, onFilterChange);
            });
            containerEl.appendChild(manageBtn);
        }

        // Add Room button at the end
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'stage-room-add-btn';
        addBtn.title = 'Add new room';
        addBtn.setAttribute('aria-label', 'Add new room');
        addBtn.innerHTML = '<svg class="kare-icon" viewBox="0 0 16 16"><path d="M8,2 L8,14 M2,8 L14,8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

        addBtn.addEventListener('click', () => {
            showInlineAddInput(containerEl, addBtn, onFilterChange);
        });

        containerEl.appendChild(addBtn);
    }

    function showRoomDevicesPopover(containerEl, roomName, deviceList, onFilterChange) {
        const existing = document.querySelector('.stage-room-devices-popover');
        if (existing) { existing.remove(); return; }

        const pop = document.createElement('div');
        pop.className = 'stage-room-devices-popover';

        const hdr = document.createElement('div');
        hdr.className = 'stage-room-popover-header';
        hdr.innerHTML = `<span>Devices in ${roomName}</span>`;
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'stage-room-popover-close';
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', () => pop.remove());
        hdr.appendChild(closeBtn);
        pop.appendChild(hdr);

        const devRooms = getDeviceRooms();
        if (!deviceList || deviceList.length === 0) {
            const empty = document.createElement('div');
            empty.style.cssText = 'font-size:10px;color:var(--text-muted);padding:4px;';
            empty.textContent = 'No devices detected';
            pop.appendChild(empty);
        } else {
            deviceList.forEach(dev => {
                const item = document.createElement('label');
                item.className = 'room-device-item';
                const chk = document.createElement('input');
                chk.type = 'checkbox';
                const currentRm = devRooms[dev.address] !== undefined ? devRooms[dev.address] : (dev.room || '');
                chk.checked = (currentRm.toLowerCase() === roomName.toLowerCase());
                chk.addEventListener('change', () => {
                    if (chk.checked) {
                        devRooms[dev.address] = roomName;
                    } else {
                        delete devRooms[dev.address];
                    }
                    saveDeviceRooms(devRooms);
                    syncTopology(null, null, devRooms);
                    window.dispatchEvent(new CustomEvent('divoom:rooms-updated', { detail: { action: 'devices-updated' } }));
                    if (typeof onFilterChange === 'function') onFilterChange(roomName);
                });
                const lbl = document.createElement('span');
                lbl.textContent = dev.name || dev.address;
                item.appendChild(chk);
                item.appendChild(lbl);
                pop.appendChild(item);
            });
        }

        document.body.appendChild(pop);
        const rect = containerEl.getBoundingClientRect();
        pop.style.top = `${rect.bottom + 4}px`;
        pop.style.left = `${Math.max(10, rect.left)}px`;

        const onDocClick = (e) => {
            if (!pop.contains(e.target) && !e.target.closest('.stage-room-manage-btn')) {
                pop.remove();
                document.removeEventListener('click', onDocClick);
            }
        };
        setTimeout(() => document.addEventListener('click', onDocClick), 50);
    }


    function showInlineAddInput(containerEl, addBtn, onFilterChange) {
        addBtn.style.display = 'none';

        const form = document.createElement('div');
        form.className = 'stage-room-input-form';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'stage-room-input';
        input.placeholder = 'Room name';
        input.maxLength = 20;

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'stage-room-confirm-btn';
        confirmBtn.textContent = 'Add';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'stage-room-cancel-btn';
        cancelBtn.textContent = '×';

        const closeForm = () => {
            form.remove();
            addBtn.style.display = 'inline-flex';
        };

        const doAdd = () => {
            const val = input.value.trim();
            if (val) {
                const added = addRoom(val);
                if (added) {
                    closeForm();
                    if (typeof onFilterChange === 'function') {
                        onFilterChange(added);
                    }
                    return;
                }
            }
            closeForm();
        };

        confirmBtn.addEventListener('click', doAdd);
        cancelBtn.addEventListener('click', closeForm);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); doAdd(); }
            if (e.key === 'Escape') { e.preventDefault(); closeForm(); }
        });

        form.appendChild(input);
        form.appendChild(confirmBtn);
        form.appendChild(cancelBtn);
        containerEl.appendChild(form);
        input.focus();
    }

    window.SpatialRooms = {
        getRooms,
        addRoom,
        removeRoom,
        getDeviceRooms,
        saveDeviceRooms,
        getSavedPositions,
        savePositions,
        findPosition,
        syncTopology,
        loadTopology,
        populateSelect,
        renderFilterPills,
        showRoomDevicesPopover
    };

    window.addEventListener('pywebviewready', () => {
        loadTopology();
    });
})();
