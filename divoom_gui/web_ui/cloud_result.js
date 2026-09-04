/* cloud_result.js — unwrap a cloud panel's reply, and SHOW THE REASON.

   R70 P2.4. Every cloud browse used to answer with a bare list, and the
   panels rendered "nothing found" whether the catalog was empty, the
   background service was down, the account was not signed in, or Divoom
   returned an error. Four states, one message, no way to act on any of them.

   The Python side now returns {ok, items, error, cause}. This is the one
   place that unwraps it, for the same reason `_cloud_list` is the one place
   that produces it: five panels each doing their own branching is how the
   old pattern got to five panels in the first place.

   `cause` is a flag, never parsed text — 'unreachable' | 'auth' | 'cloud' —
   so the wording of an error can change without changing behaviour here. */
(function () {
    "use strict";

    /* What the user can DO about it. Deliberately not a restatement of the
       reason: seen on screen, "Could not load clock faces: the background
       service is not running" followed by "The background service is not
       running." reads as a stutter and adds nothing. A hint that repeats the
       reason is worse than no hint, so `renderProblem` drops it when the reason
       already contains it. */
    const HINTS = {
        unreachable: "Reopen Divoom Control to start it again.",
        auth: "Sign in to your Divoom account in Settings.",
        cloud: "Divoom's servers rejected the request — try again shortly.",
        /* R71 P3.1 — LAN-backed actions. Before these, a LAN command on a
           Bluetooth-only device answered a bare false and the UI said "Failed
           to send", which reads as a broken feature rather than a device that
           has no such API. Same defect this file was written to fix for cloud
           browse, on the other transport. */
        no_lan_capability: "Add a WiFi-capable Divoom device in Settings → Hardware.",
        not_configured: "Add this device's IP address in Settings → Hardware.",
        lan: "The device did not accept the command.",
        wall: "Pick a single device instead of a Virtual Wall.",
        input: "",
    };

    /* True when the hint would only echo the reason back. */
    function addsNothing(hint, detail) {
        if (!hint) return true;
        const norm = (t) => String(t).toLowerCase().replace(/[.]/g, "").trim();
        return norm(detail).includes(norm(hint));
    }

    /* Render a failed browse into `el`, saying what went wrong and what to
       do about it. Deliberately not styled as an empty state: an error that
       looks like "no results" is the bug this replaces. */
    function renderProblem(el, reply, emptyLabel) {
        if (!el) return;
        const detail = (reply && reply.error) || emptyLabel || "Could not load.";
        let hint = HINTS[reply && reply.cause] || "";
        if (addsNothing(hint, detail)) hint = "";
        el.innerHTML =
            '<div class="empty-list cloud-problem">' +
            '<div class="cloud-problem-reason"></div>' +
            (hint ? '<div class="cloud-problem-hint"></div>' : "") +
            "</div>";
        el.querySelector(".cloud-problem-reason").textContent = detail;
        if (hint) el.querySelector(".cloud-problem-hint").textContent = hint;
    }

    /* Returns the items array, or null if the reply was a failure (in which
       case the reason has been rendered into `el`).

       Tolerates a bare array so a panel keeps working if it is called before
       its Python side is migrated — during a staged rollout the alternative
       is a blank panel, which is the failure mode being removed. */
    function unwrap(reply, el, emptyLabel) {
        if (Array.isArray(reply)) return reply;
        if (reply && reply.ok) return reply.items || [];
        renderProblem(el, reply, emptyLabel);
        return null;
    }

    /* The same reason+hint, as one line of text — for surfaces that report
       through a toast rather than into a list element (the danmaku overlay is
       the first). Deliberately the SAME producer as renderProblem: a second
       way of phrasing "no" is how the old five-panel divergence started. */
    function problemText(reply, fallback) {
        const detail = (reply && reply.error) || fallback || "Could not do that.";
        let hint = HINTS[reply && reply.cause] || "";
        if (addsNothing(hint, detail)) hint = "";
        return hint ? detail + " " + hint : detail;
    }

    window.DivoomCloud = {
        unwrap: unwrap, renderProblem: renderProblem, problemText: problemText,
    };
})();
