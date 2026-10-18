// spatial_snap.js — where a dragged panel lands on the Spatial Bench (P6.1).
//
// Pure geometry, no DOM: given the rectangle a drag proposes and the other
// panels' rectangles, answer where the panel goes. A wall slices one image by
// each slot's place on the bench (divoomd/src/wall.rs cuts per slot by x/y), so
// panels that are meant to be one surface must touch edge to edge; dragging
// used to only clamp to the bench, which left gaps and overlaps the image was
// cut across.
//
// The rules, in order:
//   1. A panel within THRESHOLD px of another's edge snaps flush against it,
//      and, when it is also within THRESHOLD of that panel's top/bottom (or
//      left/right) edge, lines up with it -- a row or column, not a stagger.
//   2. Contact means a shared edge of non-zero length; corners do not join.
//   3. A panel never lands overlapping another. A drop ON another panel is
//      pushed to the nearest flush position, however far that is.
//   4. A drop near nothing stays where it was dropped.
//   5. Nothing lands outside `bounds` when bounds are given.
(function (root) {
    'use strict';

    const THRESHOLD = 12;

    const overlaps = (a, b) =>
        a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

    const inBounds = (r, bounds) => !bounds ||
        (r.x >= 0 && r.y >= 0 && r.x + r.w <= bounds.w && r.y + r.h <= bounds.h);

    // Every flush position against `o`: `dc` is how far the panel moves to
    // touch, `da` how far along the edge it moves to line up (0 to keep its
    // place), `aligned` whether it lines up an edge with `o`.
    function contacts(m, o) {
        const out = [];
        const push = (x, y, dc, da, aligned) => out.push({ x, y, dc, da, aligned });
        [o.x - m.w, o.x + o.w].forEach(x => {                       // left of / right of o
            [[m.y, 0], [o.y, 1], [o.y + o.h - m.h, 1]].forEach(([y, aligned]) => {
                if (y < o.y + o.h && y + m.h > o.y) push(x, y, Math.abs(x - m.x), Math.abs(y - m.y), aligned);
            });
        });
        [o.y - m.h, o.y + o.h].forEach(y => {                       // above / below o
            [[m.x, 0], [o.x, 1], [o.x + o.w - m.w, 1]].forEach(([x, aligned]) => {
                if (x < o.x + o.w && x + m.w > o.x) push(x, y, Math.abs(y - m.y), Math.abs(x - m.x), aligned);
            });
        });
        return out;
    }

    /**
     * Where `moving` ({x, y, w, h}, the position the drag proposes) lands among
     * `others` (the same shape). Returns {x, y, snapped}: `snapped` is true when
     * it was moved flush against another panel.
     */
    function snap(moving, others, opts) {
        const threshold = (opts && opts.threshold) || THRESHOLD;
        const bounds = opts && opts.bounds;
        const m = { x: moving.x, y: moving.y, w: moving.w, h: moving.h };
        const free = (r) => inBounds(r, bounds) && !others.some(o => overlaps(r, o));
        // Dropped clear of every panel: snap only within reach. Dropped on one:
        // the nearest way out, however far.
        const clear = !others.some(o => overlaps(m, o));

        const candidates = [];
        others.forEach(o => contacts(m, o).forEach(c => {
            if ((clear && c.dc > threshold) || c.da > threshold) return;
            if (!free({ x: c.x, y: c.y, w: m.w, h: m.h })) return;
            candidates.push(c);
        }));

        if (candidates.length === 0) return { x: m.x, y: m.y, snapped: false };
        // The nearest contact; among equals, the one that lines up; then the
        // smaller shift along the edge.
        candidates.sort((a, b) => (a.dc - b.dc) || (b.aligned - a.aligned) || (a.da - b.da));
        return { x: candidates[0].x, y: candidates[0].y, snapped: true };
    }

    root.SpatialSnap = { snap, THRESHOLD };
})(typeof window !== 'undefined' ? window : globalThis);
