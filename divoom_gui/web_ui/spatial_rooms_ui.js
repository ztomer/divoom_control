/**
 * spatial_rooms_ui.js — the room pills, the Devices popover and the room
 * select. Split from spatial_rooms.js (500-line cap); every read and write of
 * a panel's room goes through SpatialRooms.roomOf / assignRoom (U.4).
 */
(function() {
    'use strict';

    const R = window.SpatialRooms;

    function populateSelect(selectEl, currentRoom) {
        if (!selectEl) return;
        const rooms = R.getRooms();
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
        // An open add-room form lives in this container, and a redraw (a room
        // assigned, the topology loaded, the fleet refreshed) clears it: the
        // form and its typed name vanished between "+" and "Add" -- CI's
        // timeout on .stage-room-confirm-btn. The redraw gives it back.
        const openInput = containerEl.querySelector('.stage-room-input');
        const reopen = openInput
            ? { value: openInput.value, focused: document.activeElement === openInput }
            : null;
        containerEl.innerHTML = '';

        const rooms = R.getRooms();
        const allFilters = ['all', ...rooms];
        const devRooms = R.getDeviceRooms();
        const devices = Array.isArray(deviceList) ? deviceList : [];
        const counts = { all: devices.length };
        rooms.forEach(r => { counts[r] = 0; });
        devices.forEach(d => {
            const r = R.roomOf(d.address, devRooms);
            if (r && counts[r] !== undefined) counts[r] += 1;
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
                        R.removeRoom(r);
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
        if (reopen) showInlineAddInput(containerEl, addBtn, onFilterChange, reopen);
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

        const devRooms = R.getDeviceRooms();
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
                chk.checked = R.roomOf(dev.address, devRooms).toLowerCase() === roomName.toLowerCase();
                chk.addEventListener('change', () => {
                    R.assignRoom(dev.address, chk.checked ? roomName : '');
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


    function showInlineAddInput(containerEl, addBtn, onFilterChange, restore) {
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
            // Closed FIRST: addRoom announces the change, the pills redraw at
            // once, and a form still open then would be given back as open.
            closeForm();
            const added = val ? R.addRoom(val) : false;
            if (added && typeof onFilterChange === 'function') onFilterChange(added);
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
        if (restore) {
            input.value = restore.value;
            if (restore.focused) input.focus();
        } else {
            input.focus();
        }
    }

    Object.assign(window.SpatialRooms, { populateSelect, renderFilterPills, showRoomDevicesPopover });
})();
