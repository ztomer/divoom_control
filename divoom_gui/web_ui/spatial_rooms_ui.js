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
        // A redraw (a room assigned, the topology loaded, the fleet refreshed)
        // KEEPS each control's element and updates it in place. It used to
        // rebuild them all, and that broke two things a user does:
        // - a click is a press and a release on ONE element; a redraw between
        //   them left the release on a new button, so the browser fired no
        //   click -- "+" opened no form, a pill selected nothing;
        // - the open add-room form, and the name typed into it, went with the
        //   old elements (CI's timeout on .stage-room-confirm-btn).
        // Handlers read the CURRENT callback from the container, so a kept
        // element never acts on a stale one.
        containerEl._onFilterChange = onFilterChange;
        const change = (v) => {
            const f = containerEl._onFilterChange;
            if (typeof f === 'function') f(v);
        };
        const old = new Map();
        [...containerEl.children].forEach(el => { if (el.dataset.key) old.set(el.dataset.key, el); });
        const keep = (key, make) => {
            let el = old.get(key);
            if (el) { old.delete(key); return el; }
            el = make();
            el.dataset.key = key;
            return el;
        };
        const button = (cls) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = cls;
            return b;
        };
        const wanted = [];

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
            const pill = keep(`pill:${r}`, () => {
                const el = document.createElement('div');
                el.dataset.room = r;
                const label = document.createElement('span');
                label.className = 'stage-room-pill-label';
                label.textContent = isAll ? 'All' : r;
                el.appendChild(label);
                const countSpan = document.createElement('span');
                countSpan.className = 'stage-room-pill-count';
                el.appendChild(countSpan);
                // Allow deletion for custom rooms (not All and not default Desk)
                if (!isAll && r.toLowerCase() !== 'desk') {
                    const delBtn = button('stage-room-del-btn');
                    delBtn.title = `Delete ${r} room`;
                    delBtn.setAttribute('aria-label', `Delete ${r} room`);
                    delBtn.textContent = '×';
                    el.appendChild(delBtn);
                }
                return el;
            });
            pill.className = `stage-room-pill ${isActive ? 'active' : ''}`;
            pill.querySelector('.stage-room-pill-count').textContent = `(${counts[r] !== undefined ? counts[r] : 0})`;
            const delBtn = pill.querySelector('.stage-room-del-btn');
            if (delBtn) {
                delBtn.onclick = (e) => {
                    e.stopPropagation();
                    if (confirm(`Remove room "${r}"? Devices in this room will move to Desk.`)) {
                        R.removeRoom(r);
                        change(activeFilter.toLowerCase() === r.toLowerCase() ? 'all' : activeFilter);
                    }
                };
            }
            pill.onclick = () => change(r);
            wanted.push(pill);
        });

        // Manage Devices button when a specific room is selected
        if (activeFilter !== 'all') {
            const manageBtn = keep('manage', () => {
                const b = button('stage-room-manage-btn');
                b.innerHTML = '<svg class="kare-icon" viewBox="0 0 16 16"><circle cx="4" cy="4" r="2" fill="currentColor"/><circle cx="12" cy="4" r="2" fill="currentColor"/><circle cx="8" cy="11" r="2" fill="currentColor"/></svg> Devices';
                return b;
            });
            manageBtn.title = `Add or remove devices in ${activeFilter}`;
            manageBtn.setAttribute('aria-label', `Add or remove devices in ${activeFilter}`);
            manageBtn.onclick = (e) => {
                e.stopPropagation();
                showRoomDevicesPopover(containerEl, activeFilter, devices, change);
            };
            wanted.push(manageBtn);
        }

        // Add Room button at the end, then its form while one is open
        const addBtn = keep('add', () => {
            const b = button('stage-room-add-btn');
            b.title = 'Add new room';
            b.setAttribute('aria-label', 'Add new room');
            b.innerHTML = '<svg class="kare-icon" viewBox="0 0 16 16"><path d="M8,2 L8,14 M2,8 L14,8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
            return b;
        });
        addBtn.onclick = () => showInlineAddInput(containerEl, addBtn, change);
        wanted.push(addBtn);
        const form = old.get('form');
        if (form) { old.delete('form'); wanted.push(form); }

        // Only what is out of place moves; a kept element that is already in
        // position is never detached, so a press on it still ends in a click.
        wanted.forEach((el, i) => {
            if (containerEl.children[i] !== el) containerEl.insertBefore(el, containerEl.children[i] || null);
        });
        [...containerEl.children].slice(wanted.length).forEach(el => el.remove());
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


    function showInlineAddInput(containerEl, addBtn, onFilterChange) {
        addBtn.style.display = 'none';

        const form = document.createElement('div');
        form.className = 'stage-room-input-form';
        form.dataset.key = 'form';   // a redraw keeps it (renderFilterPills)

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
            // once, and a form still open then would be kept open.
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
        input.focus();
    }

    Object.assign(window.SpatialRooms, { populateSelect, renderFilterPills, showRoomDevicesPopover });
})();
