// DV.BGLAUNCH: the app keeps WebKit painting a covered window (divoom_gui/first_paint.py), so
// WebKit no longer throttles a render loop while the window is covered. The app tells the page
// instead: it sets window.__divoomCovered and fires `divoom:window-covered` on every change.
//
// DivoomCovered.hold(resume): a render loop calls it first on every frame. Covered: it returns
// true (the loop stops; the last frame stays on screen) and keeps `resume`, which it calls once
// the window is seen again. Not covered: false, and the loop runs as before.
(function () {
    "use strict";
    const held = new Set();
    window.addEventListener("divoom:window-covered", () => {
        if (window.__divoomCovered) return;
        const resumes = [...held];
        held.clear();
        resumes.forEach((fn) => fn());
    });
    window.DivoomCovered = {
        hold(resume) {
            if (!window.__divoomCovered) return false;
            held.add(resume);
            return true;
        },
    };
})();
