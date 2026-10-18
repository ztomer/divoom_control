// spatial_drag.js — dragging a panel node on the Spatial Bench.
// Split from spatial_stage.js (500-line cap). A drag that never moved is a
// click: it connects the panel. One that moved saves the new position, which
// SpatialSnap (spatial_snap.js) has put flush against a panel it was dropped
// near or on (P6.1): a wall cuts its image by these positions.
(function() {
    'use strict';

    let activeDrag = null;

    function start(e, ctx) {
        if (e.button !== 0) return;
        const bench = document.getElementById('spatial-bench');
        if (!bench) return;
        const { addr, node, dev, positions, rooms, nameOf } = ctx;
        activeDrag = {
            addr, dev, node, positions, rooms, nameOf, startX: e.clientX, startY: e.clientY,
            initialX: positions[addr] ? positions[addr].x : 0,
            initialY: positions[addr] ? positions[addr].y : 0,
            benchWidth: bench.clientWidth, benchHeight: bench.clientHeight,
            nodeWidth: node.offsetWidth, nodeHeight: node.offsetHeight, hasMoved: false,
            // Every other panel's footprint, read once: they do not move while this one does.
            others: [...bench.querySelectorAll('.spatial-node')].filter(n => n !== node).map(n => ({
                x: n.offsetLeft, y: n.offsetTop, w: n.offsetWidth, h: n.offsetHeight }))
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', end);
        e.preventDefault();
    }

    function onMove(e) {
        if (!activeDrag) return;
        const dx = e.clientX - activeDrag.startX, dy = e.clientY - activeDrag.startY;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) activeDrag.hasMoved = true;
        const d = activeDrag;
        const cx = Math.max(0, Math.min(d.benchWidth - d.nodeWidth, d.initialX + dx));
        const cy = Math.max(0, Math.min(d.benchHeight - d.nodeHeight, d.initialY + dy));
        const { x: nx, y: ny } = window.SpatialSnap.snap(
            { x: cx, y: cy, w: d.nodeWidth, h: d.nodeHeight }, d.others,
            { bounds: { w: d.benchWidth, h: d.benchHeight } });
        const positions = activeDrag.positions;
        if (!positions[activeDrag.addr]) positions[activeDrag.addr] = {};
        positions[activeDrag.addr].x = nx;
        positions[activeDrag.addr].y = ny;
        activeDrag.node.style.left = `${nx}px`;
        activeDrag.node.style.top = `${ny}px`;
    }

    function end() {
        if (activeDrag) {
            const { addr, dev, positions, rooms, nameOf } = activeDrag;
            if (!activeDrag.hasMoved && typeof window.connectDevice === 'function') {
                window.connectDevice(nameOf(dev), addr);
            } else {
                if (window.SpatialRooms) window.SpatialRooms.savePositions(positions, rooms);
                else try { localStorage.setItem('divoom_stage_positions', JSON.stringify(positions)); } catch (_) {}
                if (window.DivoomState?.assignedSlots?.[addr]) {
                    window.DivoomState.assignedSlots[addr].x = positions[addr].x;
                    window.DivoomState.assignedSlots[addr].y = positions[addr].y;
                    if (window.renderArrangerCanvas) window.renderArrangerCanvas();
                    if (window.syncArrangerToPython) window.syncArrangerToPython();
                }
            }
        }
        activeDrag = null;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', end);
    }

    window.SpatialDrag = { start };
})();
