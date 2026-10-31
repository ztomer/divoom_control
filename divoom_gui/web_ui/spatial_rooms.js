/**
 * spatial_rooms.js — Room lifecycle & management engine
 * Dieter Rams & Susan Kare inspired room grouping and spatial filtering.
 * Manages custom rooms, default Desk baseline, and persistence across
 * localStorage and divoomd topology. The pills, the Devices popover and the
 * room select are spatial_rooms_ui.js (500-line cap).
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

    // The ONE reader of a panel's room (U.4): the stored room, the stored key
    // matched without regard to letter case (as findPosition and the daemon
    // match), spelled as the room list spells it; '' when it has none. No
    // caller invents a default room -- "unassigned" is '' everywhere.
    function keyFor(map, mac) {
        if (!map || !mac) return null;
        if (Object.prototype.hasOwnProperty.call(map, mac)) return mac;
        const lower = mac.toLowerCase();
        return Object.keys(map).find(k => k.toLowerCase() === lower) || null;
    }

    function roomOf(mac, map) {
        const m = map || getDeviceRooms();
        const k = keyFor(m, mac);
        const r = k ? String(m[k] || '') : '';
        if (!r) return '';
        return getRooms().find(rm => rm.toLowerCase() === r.toLowerCase()) || r;
    }

    // Is the panel drawn under this filter? 'all' draws every panel; a room
    // draws exactly its own (U.4: it dimmed the rest, so every room showed all).
    function inRoom(mac, filter) {
        if (!filter || filter === 'all') return true;
        return roomOf(mac).toLowerCase() === filter.toLowerCase();
    }

    // The ONE writer of a panel's room: '' or null takes it out of every room.
    // It writes the store, tells the daemon and announces the change; nothing
    // keeps a copy, so a removal cannot be written back over (U.4).
    function assignRoom(mac, room) {
        if (!mac) return;
        const map = getDeviceRooms();
        const k = keyFor(map, mac);
        const clean = (room || '').trim();
        if (clean) map[k || mac] = clean;
        else if (k) delete map[k];
        saveDeviceRooms(map);
        syncTopology(null, null, map);
        window.dispatchEvent(new CustomEvent('divoom:rooms-updated', { detail: { action: 'devices-updated' } }));
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

        // A panel's entry carries what is known: its place, and its room only
        // when it has one (the daemon replaces the entry, so a missing room is
        // how a removal reaches it -- never filled in as 'Desk').
        const devices = {};
        Object.keys(posMap).forEach(addr => {
            const p = posMap[addr];
            if (p && typeof p.x === 'number' && typeof p.y === 'number') devices[addr] = { x: p.x, y: p.y };
        });
        Object.keys(roomMap).forEach(addr => {
            const k = keyFor(devices, addr) || addr;
            const room = roomOf(addr, roomMap);
            if (room) devices[k] = Object.assign(devices[k] || {}, { room });
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

                // The daemon's layout is the stored truth for WHICH panels are
                // placed (D.DV2): a key it does not hold is dropped here, or
                // the next sync would write it back. This is how an invented
                // fleet (the owner's 11:22:33:44:55:0x placements, refused by
                // the daemon as never reported) leaves this store too.
                const held = Object.keys(top.devices).map(k => k.toLowerCase());
                const unheld = (m) => Object.keys(m).filter(k => !held.includes(k.toLowerCase()));
                unheld(posMap).forEach(k => { delete posMap[k]; changedPos = true; });
                unheld(roomMap).forEach(k => { delete roomMap[k]; changedRooms = true; });

                Object.keys(top.devices).forEach(addr => {
                    const dev = top.devices[addr];
                    if (dev && typeof dev.x === 'number' && typeof dev.y === 'number') {
                        posMap[addr] = { x: dev.x, y: dev.y };
                        changedPos = true;
                    }
                    // The daemon's entry is the stored truth for this panel's
                    // room, "none" included: a stale local room is dropped.
                    if (dev && typeof dev === 'object') {
                        const k = keyFor(roomMap, addr);
                        if (k && k !== addr) delete roomMap[k];
                        if (dev.room) roomMap[addr] = dev.room;
                        else delete roomMap[addr];
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

    // Positions only: a room is written by assignRoom alone.
    function savePositions(positions) {
        try {
            localStorage.setItem(POSITIONS_KEY, JSON.stringify(positions));
        } catch (_) {}
        syncTopology(null, positions);
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
        if (changed) { saveDeviceRooms(devRooms); syncTopology(null, null, devRooms); }

        window.dispatchEvent(new CustomEvent('divoom:rooms-updated', { detail: { action: 'remove', room: clean } }));
        return true;
    }

    function getWallSlots(devices) {
        const devList = devices || (window.DivoomState && window.DivoomState.discoveredDevices) || [];
        const posMap = getSavedPositions();
        const roomMap = getDeviceRooms();
        const slots = {};
        devList.forEach(dev => {
            const addr = dev.address;
            // A panel the daemon refuses as a slot (P6.1) is no slot here
            // either; getWallRefusals says which and why.
            if (!addr || dev.wallRefusal) return;
            const p = findPosition(posMap, addr) || { x: 0, y: 0 };
            // The bench footprint the user placed (the chassis drawing) and the
            // daemon's diode count (P5.1), from one source with the bench.
            const enc = window.panelEnclosure(dev);
            const dims = { width: Math.round(enc.w_mm * 0.65), height: Math.round(enc.h_mm * 0.65), size: enc.pw };
            slots[addr] = {
                x: p.x,
                y: p.y,
                width: dims.width,
                height: dims.height,
                size: dims.size,
                name: dev.name || 'Divoom Screen',
                room: roomOf(addr, roomMap)
            };
        });
        return slots;
    }

    // The panels left out of the wall, with the daemon's reason and their room.
    function getWallRefusals(devices) {
        const devList = devices || (window.DivoomState && window.DivoomState.discoveredDevices) || [];
        const roomMap = getDeviceRooms();
        return devList.filter(d => d.address && d.wallRefusal).map(d => ({
            mac: d.address, name: d.name || d.address, reason: d.wallRefusal, room: roomOf(d.address, roomMap) }));
    }

    window.SpatialRooms = {
        getRooms,
        addRoom,
        removeRoom,
        getDeviceRooms,
        roomOf,
        inRoom,
        assignRoom,
        getSavedPositions,
        savePositions,
        findPosition,
        getWallSlots,
        getWallRefusals,
        syncTopology,
        loadTopology
    };

    window.addEventListener('pywebviewready', () => {
        loadTopology();
    });
})();
