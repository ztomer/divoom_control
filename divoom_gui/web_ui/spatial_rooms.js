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

    function saveRooms(rooms) {
        if (!rooms.includes('Desk')) rooms.unshift('Desk');
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(rooms));
        } catch (_) {}
        syncTopology(rooms);
    }

    function syncTopology(rooms) {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_topology) {
            try {
                window.pywebview.api.set_topology({ rooms: rooms });
            } catch (_) {}
        }
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
        const val = currentRoom || 'Desk';

        selectEl.innerHTML = '';
        rooms.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r;
            opt.textContent = r;
            if (r === val) opt.selected = true;
            selectEl.appendChild(opt);
        });

        const addOpt = document.createElement('option');
        addOpt.value = '__add_new__';
        addOpt.textContent = '+ Add Room...';
        selectEl.appendChild(addOpt);
    }

    function renderFilterPills(containerEl, activeFilter, onFilterChange) {
        if (!containerEl) return;
        containerEl.innerHTML = '';

        const rooms = getRooms();
        const allFilters = ['all', ...rooms];

        allFilters.forEach(r => {
            const isAll = (r === 'all');
            const isActive = (activeFilter === r);
            const pill = document.createElement('div');
            pill.className = `stage-room-pill ${isActive ? 'active' : ''}`;
            pill.dataset.room = r;

            const label = document.createElement('span');
            label.className = 'stage-room-pill-label';
            label.textContent = isAll ? 'All' : r;
            pill.appendChild(label);

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
                            onFilterChange(activeFilter === r ? 'all' : activeFilter);
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
        populateSelect,
        renderFilterPills
    };
})();
