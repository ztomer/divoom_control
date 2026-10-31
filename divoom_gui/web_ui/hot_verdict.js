/* hot_verdict.js — each panel's hot-channel verdict, in words (U.5, P5.13 A).
 *
 * The owner picked option A (2026-10-31): one LASTING line per panel that says
 * what the newest hot-channel run did, whichever path ran it -- the Update Hot
 * Channel button, Sync Now or the daily schedule. The daemon keeps one record
 * per panel and every path writes it, failures included
 * (divoomd/src/hot_verdict.rs); this file only turns a record into the line,
 * in two lengths: the Hot tab's full line and the Auto-Sync row's short one
 * (two zoom levels of one fact, from ONE renderer).
 *
 * Never one channel: the glyph and the words carry the verdict; the colour
 * (`data-kind`) only reinforces it. Glyphs are the Kare set:
 *   ✓ up to date / stored    ↓ new files arrived    ⚠ some files missing
 *   ✗ failed                 · never checked         → checking now
 */
(function () {
    "use strict";

    const BY = { button: "", sync_now: "by Sync Now", schedule: "by the schedule" };
    const STALE_MS = 14 * 86400000;
    const cache = {};

    function ago(atSec, nowMs) {
        const diff = nowMs - atSec * 1000;
        const m = 60000, h = 3600000, d = 86400000;
        if (diff < m) return "just now";
        if (diff < h) return `${Math.round(diff / m)} min ago`;
        if (diff < d) return `${Math.round(diff / h)} h ago`;
        if (diff < 30 * d) { const n = Math.round(diff / d); return `${n} day${n > 1 ? "s" : ""} ago`; }
        return new Date(atSec * 1000).toLocaleDateString();
    }

    function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

    // The first clause of an error, without the daemon's "Connection to <id>
    // failed:" preamble -- the panel is already named by where the line sits.
    function reason(err) {
        let r = String(err || "unknown error");
        r = r.replace(/^Connection to \S+ failed:\s*/i, "");
        return r.length > 80 ? r.slice(0, 79) + "…" : r;
    }

    // {glyph, kind, text, title} for one record. `short`: the Auto-Sync row.
    function line(entry, opts) {
        const o = opts || {};
        const now = o.nowMs != null ? o.nowMs : Date.now();
        if (!entry || !entry.at) {
            return { glyph: "·", kind: "none", text: "Never checked", title: "" };
        }
        const when = ago(entry.at, now);
        const by = BY[entry.by] || "";
        const title = new Date(entry.at * 1000).toLocaleString() + (by ? ` — ${by}` : "")
            + (entry.error ? `\n${entry.error}` : "");
        const stale = now - entry.at * 1000 > STALE_MS;
        const offered = entry.offered || 0, fetched = entry.fetched || 0, delivered = entry.delivered || 0;
        let glyph, kind, head;
        if (entry.outcome === "failed") {
            glyph = "✗"; kind = "fail";
            head = o.short ? "Failed" : `Failed ${when}: ${reason(entry.error)}`;
            const text = o.short ? `${head} · ${when}` : head + (by ? ` · ${by}` : "");
            return { glyph, kind, text, title, stale };
        }
        if (entry.by === "schedule") {
            if (delivered < offered) {
                glyph = "⚠"; kind = "warn";
                head = o.short ? `${delivered}/${offered} stored` : `${delivered} of ${plural(offered, "file")} stored`;
            } else {
                glyph = "✓"; kind = "ok";
                head = o.short ? `${delivered} stored` : `${plural(delivered, "file")} stored`;
            }
        } else if (offered > 0 && fetched < offered) {
            glyph = "⚠"; kind = "warn";
            head = o.short ? `${offered - fetched}/${offered} missing`
                : `${offered - fetched} of ${plural(offered, "file")} could not be fetched`;
        } else if (delivered > 0) {
            glyph = "↓"; kind = "new";
            head = o.short ? `${delivered} new` : `${delivered} new ${delivered === 1 ? "file" : "files"}`;
        } else {
            glyph = "✓"; kind = "ok";
            head = "Up to date";
        }
        let text;
        if (o.short) text = `${head} · ${when}`;
        else if (kind === "ok" && entry.by !== "schedule") text = `${head} · checked ${when}` + (by ? ` ${by}` : "");
        else text = `${head} · ${when}` + (by ? ` ${by}` : "");
        return { glyph, kind, text, title, stale };
    }

    // Paint `el` with `entry`'s line. The glyph is its own span so a reader
    // (and a test) can tell the verdicts apart without the colour.
    function render(el, entry, opts) {
        if (!el) return;
        const l = line(entry, opts);
        el.textContent = "";
        const g = document.createElement("span");
        g.className = "hot-verdict-glyph";
        g.textContent = l.glyph;
        const t = document.createElement("span");
        t.className = "hot-verdict-text";
        t.textContent = l.text;
        el.append(g, t);
        el.dataset.kind = l.kind;
        el.classList.add("hot-verdict");
        el.classList.toggle("stale", !!l.stale && l.kind !== "fail");
        el.title = l.title;
    }

    // "→ Checking now" while a run is under way on the panel.
    function renderChecking(el, detail) {
        if (!el) return;
        el.textContent = "";
        const g = document.createElement("span");
        g.className = "hot-verdict-glyph";
        g.textContent = "→";
        const t = document.createElement("span");
        t.className = "hot-verdict-text";
        t.textContent = detail ? `Checking now (${detail})` : "Checking now";
        el.append(g, t);
        el.dataset.kind = "busy";
        el.classList.add("hot-verdict");
        el.classList.remove("stale");
        el.title = "";
    }

    // Keep the NEWER record: a read that left before a `hot_status` event
    // and lands after it must not put the older verdict back.
    function put(mac, e) {
        const cur = cache[mac];
        if (cur && e && cur.at && e.at && e.at < cur.at) return;
        cache[mac] = e && e.at ? e : (cur || null);
    }

    function parse(json) {
        if (json && typeof json === "object") return json;
        try { return JSON.parse(json); } catch (_) { return null; }
    }

    // Re-read one panel's record from the daemon's state; resolves the entry.
    function refresh(mac) {
        const api = window.pywebview?.api;
        if (!mac || !api?.hot_verdict) return Promise.resolve(cache[mac] || null);
        return Promise.resolve(api.hot_verdict(mac)).then(json => {
            put(mac, parse(json));
            announce(mac);
            return cache[mac];
        });
    }

    function refreshAll() {
        const api = window.pywebview?.api;
        if (!api?.hot_verdicts) return Promise.resolve(cache);
        return Promise.resolve(api.hot_verdicts()).then(json => {
            const all = parse(json) || {};
            Object.keys(all).forEach(mac => { put(mac, all[mac]); announce(mac); });
            return cache;
        });
    }

    function get(mac) {
        if (!mac) return null;
        if (cache[mac]) return cache[mac];
        const low = mac.toLowerCase();
        const k = Object.keys(cache).find(c => c.toLowerCase() === low);
        return k ? cache[k] : null;
    }

    function announce(mac) {
        window.dispatchEvent(new CustomEvent("divoom:hot-verdict", { detail: { mac } }));
    }

    window.HotVerdict = { line, render, renderChecking, refresh, refreshAll, get };

    // The daemon's `hot_status` event: a panel's record just changed.
    window.Divoom = window.Divoom || {};
    window.Divoom.onHotStatus = function (ev) {
        if (!ev || !ev.mac) return;
        put(ev.mac, ev.verdict || null);
        announce(ev.mac);
    };
})();
