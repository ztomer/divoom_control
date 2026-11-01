/**
 * spatial_rooms.js — Room lifecycle & management engine
 * Dieter Rams & Susan Kare inspired room grouping and spatial filtering.
 * The pills, the Devices popover and the room select are spatial_rooms_ui.js
 * (500-line cap).
 *
 * THE ARRANGEMENT HAS ONE STORE: the daemon's topology (2026-11-01). The
 * owner: "divoom control seems to be forgetting the device arrangements on
 * each restart". The bench kept places, rooms and the room list in
 * localStorage, which pywebview's private mode wiped on every launch, and
 * read the daemon's copy once, swallowing any failure. Until that read
 * landed the bench drew from empty storage, and the first write sent the
 * GUI's defaults over the daemon's copy -- the custom room "Ethan" was
 * erased that way. So:
 *   - this module holds the daemon's copy in memory and nothing else; the
 *     old localStorage keys are dropped once the copy has arrived;
 *   - until it has arrived the bench shows a loading state (spatial_stage.js)
 *     and every write is refused -- nothing is ever sent from a guess;
 *   - the read is retried until it lands, and the state says why it has not;
 *   - writes send what changed: a room list is merged by the daemon and a
 *     room leaves it only through `remove_rooms` (divoomd/src/wall/cmds.rs).
 * Panels are keyed by the daemon's stable id (the CoreBluetooth UUID).
 */
(function() {
    'use strict';

    const LEGACY_KEYS = ['divoom_stage_room_list', 'divoom_stage_rooms', 'divoom_stage_positions'];
    const RETRY_MS = [250, 500, 1000, 2000, 4000];

    // The daemon's copy: { rooms: [...], devices: { id: {x, y, room, ...} } },
    // null until it has been read. `screens` is get_topology's per-panel list
    // (model and size), so a placed panel this session has not seen keeps
    // its wall slot.
    let store = null;
    let screens = [];
    let status = { state: 'loading', attempts: 0, error: '' };
    let loading = null;

    function isLoaded() { return store !== null; }
    function loadStatus() { return Object.assign({}, status); }

    function announce(name, detail) {
        window.dispatchEvent(new CustomEvent(name, { detail }));
    }

    function getRooms() {
        if (!store) return [];
        const rooms = store.rooms.slice();
        if (!rooms.some(r => r.toLowerCase() === 'desk')) rooms.unshift('Desk');
        return rooms;
    }

    function getSavedPositions() {
        const out = {};
        if (!store) return out;
        Object.keys(store.devices).forEach(id => {
            const d = store.devices[id];
            if (d && typeof d.x === 'number' && typeof d.y === 'number') out[id] = { x: d.x, y: d.y };
        });
        return out;
    }

    function findPosition(positions, mac) {
        if (!positions || !mac) return null;
        const k = keyFor(positions, mac);
        return k ? positions[k] : null;
    }

    // A panel is one key whatever its letter case, as the daemon matches it.
    function keyFor(map, mac) {
        if (!map || !mac) return null;
        if (Object.prototype.hasOwnProperty.call(map, mac)) return mac;
        const lower = String(mac).toLowerCase();
        return Object.keys(map).find(k => k.toLowerCase() === lower) || null;
    }

    function getDeviceRooms() {
        const out = {};
        if (!store) return out;
        Object.keys(store.devices).forEach(id => {
            const r = store.devices[id] && store.devices[id].room;
            if (r) out[id] = r;
        });
        return out;
    }

    // The ONE reader of a panel's room (U.4), spelled as the room list spells
    // it; '' when it has none. No caller invents a default room.
    function roomOf(mac, map) {
        const m = map || getDeviceRooms();
        const k = keyFor(m, mac);
        const r = k ? String(m[k] || '') : '';
        if (!r) return '';
        return getRooms().find(rm => rm.toLowerCase() === r.toLowerCase()) || r;
    }

    // Is the panel drawn under this filter? 'all' draws every panel; a room
    // draws exactly its own (U.4).
    function inRoom(mac, filter) {
        if (!filter || filter === 'all') return true;
        return roomOf(mac).toLowerCase() === filter.toLowerCase();
    }

    // The stored entry for a panel, to change and send WHOLE: the daemon
    // replaces a panel's entry with the one it is sent.
    function entryFor(mac) {
        const k = keyFor(store.devices, mac) || mac;
        if (!store.devices[k]) store.devices[k] = {};
        return { key: k, entry: store.devices[k] };
    }

    function send(patch) {
        if (!store) return false;
        const api = window.pywebview && window.pywebview.api;
        if (!api || !api.set_topology) return false;
        let pending;
        try { pending = api.set_topology(patch); } catch (e) { pending = Promise.reject(e); }
        Promise.resolve(pending).then(reply => {
            if (reply && reply.success === false && window.showToast) {
                window.showToast(`The arrangement was not saved: ${reply.error || 'the daemon refused it'}`, 'error');
            }
        }, e => {
            if (window.showToast) window.showToast(`The arrangement was not saved: ${e}`, 'error');
        });
        return true;
    }

    function devicesPatch(keys) {
        const out = {};
        keys.forEach(k => { out[k] = Object.assign({}, store.devices[k]); });
        return out;
    }

    // The ONE writer of a panel's room: '' or null takes it out of every room.
    function assignRoom(mac, room) {
        if (!mac || !store) return false;
        const { key, entry } = entryFor(mac);
        const clean = (room || '').trim();
        if (clean) entry.room = clean;
        else delete entry.room;
        send({ devices: devicesPatch([key]) });
        announce('divoom:rooms-updated', { action: 'devices-updated' });
        return true;
    }

    function addRoom(name) {
        if (!name || !store) return false;
        const clean = name.trim();
        if (!clean || clean.length > 24) return false;
        if (getRooms().some(r => r.toLowerCase() === clean.toLowerCase())) return false;
        store.rooms.push(clean);
        send({ rooms: [clean] });
        announce('divoom:rooms-updated', { action: 'add', room: clean });
        return clean;
    }

    // Removing a room is the explicit operation; its panels go to Desk.
    function removeRoom(name) {
        if (!name || !store || name.toLowerCase() === 'desk') return false;
        const clean = name.trim();
        if (!store.rooms.some(r => r.toLowerCase() === clean.toLowerCase())) return false;
        store.rooms = store.rooms.filter(r => r.toLowerCase() !== clean.toLowerCase());
        const moved = Object.keys(store.devices).filter(k => {
            const d = store.devices[k];
            if (!d || !d.room || d.room.toLowerCase() !== clean.toLowerCase()) return false;
            d.room = 'Desk';
            return true;
        });
        const patch = { remove_rooms: [clean] };
        if (moved.length) patch.devices = devicesPatch(moved);
        send(patch);
        announce('divoom:rooms-updated', { action: 'remove', room: clean });
        return true;
    }

    // Places only: a drag, Center or Snap never writes a room (U.4).
    function savePositions(positions) {
        if (!store || !positions) return false;
        const changed = [];
        Object.keys(positions).forEach(addr => {
            const p = positions[addr];
            if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return;
            const { key, entry } = entryFor(addr);
            if (entry.x === p.x && entry.y === p.y) return;
            entry.x = p.x;
            entry.y = p.y;
            changed.push(key);
        });
        if (changed.length) send({ devices: devicesPatch(changed) });
        return true;
    }

    // The whole store, sent again (the daemon merges it).
    function syncTopology() {
        if (!store) return false;
        return send({ rooms: store.rooms.slice(), devices: devicesPatch(Object.keys(store.devices)), wall_linked: true });
    }

    function adopt(reply) {
        const top = reply.topology;
        const rooms = [];
        (Array.isArray(top.rooms) ? top.rooms : []).forEach(r => {
            if (typeof r === 'string' && r.trim() && !rooms.some(x => x.toLowerCase() === r.trim().toLowerCase())) rooms.push(r.trim());
        });
        const devices = {};
        if (top.devices && typeof top.devices === 'object') {
            Object.keys(top.devices).forEach(id => {
                const d = top.devices[id];
                if (d && typeof d === 'object') devices[id] = Object.assign({}, d);
            });
        }
        store = { rooms, devices };
        screens = Array.isArray(reply.screens) ? reply.screens : [];
        status = { state: 'loaded', attempts: status.attempts, error: '' };
        // The old copies are not a source of anything any more.
        try { LEGACY_KEYS.forEach(k => localStorage.removeItem(k)); } catch (_) {}
        announce('divoom:topology-state', loadStatus());
        announce('divoom:topology-loaded', top);
        return top;
    }

    const sleep = (ms) => new Promise(r => setTimeout(r, ms));

    // Read the daemon's copy, retrying until it lands. Every caller shares
    // the one read in flight; once loaded it answers from the store.
    function loadTopology() {
        if (store) return Promise.resolve({ rooms: store.rooms.slice(), devices: Object.assign({}, store.devices) });
        if (loading) return loading;
        loading = (async () => {
            for (;;) {
                status.attempts += 1;
                const api = window.pywebview && window.pywebview.api;
                let error = '';
                if (!api || !api.get_topology) {
                    error = 'the app is still starting';
                } else {
                    try {
                        const reply = await api.get_topology();
                        if (reply && reply.success && reply.topology && typeof reply.topology === 'object') {
                            loading = null;
                            return adopt(reply);
                        }
                        error = (reply && reply.error) || 'the daemon did not answer';
                    } catch (e) {
                        error = String((e && e.message) || e);
                    }
                }
                status = { state: status.attempts > 1 ? 'retrying' : 'loading', attempts: status.attempts, error };
                announce('divoom:topology-state', loadStatus());
                await sleep(RETRY_MS[Math.min(status.attempts - 1, RETRY_MS.length - 1)]);
            }
        })();
        return loading;
    }

    function slotFor(dev, addr, posMap, roomMap) {
        const p = findPosition(posMap, addr) || { x: 0, y: 0 };
        // The bench footprint the user placed (the chassis drawing) and the
        // daemon's diode count (P5.1), from one source with the bench.
        const enc = window.panelEnclosure(dev);
        return {
            x: p.x, y: p.y,
            width: Math.round(enc.w_mm * 0.65), height: Math.round(enc.h_mm * 0.65), size: enc.pw,
            name: dev.name || 'Divoom Screen',
            room: roomOf(addr, roomMap)
        };
    }

    // The wall's slots. Before the daemon's copy has arrived there is no
    // arrangement to make slots from: {} (callers check isLoaded). A panel
    // the daemon's layout places keeps its slot while it is off or out of
    // range -- the wall is the arrangement, not this session's scan.
    function getWallSlots(devices) {
        const slots = {};
        if (!store) return slots;
        const devList = devices || (window.DivoomState && window.DivoomState.discoveredDevices) || [];
        const posMap = getSavedPositions();
        const roomMap = getDeviceRooms();
        devList.forEach(dev => {
            const addr = dev.address;
            // A panel the daemon refuses as a slot (P6.1) is no slot here
            // either; getWallRefusals says which and why.
            if (!addr || dev.wallRefusal) return;
            slots[addr] = slotFor(dev, addr, posMap, roomMap);
        });
        if (devices) return apart(slots);
        Object.keys(posMap).forEach(id => {
            if (devList.some(d => d.address && d.address.toLowerCase() === id.toLowerCase())) return;
            if (id.startsWith('LAN:')) return; // a LAN panel is never a wall slot (P6.1)
            const scr = screens.find(s => s && typeof s.mac === 'string' && s.mac.toLowerCase() === id.toLowerCase()) || {};
            slots[id] = slotFor(Object.assign({ address: id }, scr), id, posMap, roomMap);
        });
        return apart(slots);
    }

    // The slots where the bench draws them: saved places at real sizes, made
    // not to overlap by the bench's own rule (SpatialSnap.separate).
    function apart(slots) {
        if (!window.SpatialSnap) return slots;
        const at = window.SpatialSnap.separate(Object.keys(slots).map(id =>
            ({ id, x: slots[id].x, y: slots[id].y, w: slots[id].width, h: slots[id].height })),
            { height: window.SpatialSnap.BENCH_HEIGHT });
        Object.keys(slots).forEach(id => Object.assign(slots[id], at[id]));
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
        loadTopology,
        isLoaded,
        loadStatus
    };

    window.addEventListener('pywebviewready', () => { loadTopology(); });
})();
