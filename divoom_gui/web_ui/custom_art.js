/* Custom Art channel controller — page tabs, slot grid, push.
 *
 * UX model (Rams: as little design as possible; Kare: direct manipulation):
 *   - 3 page tabs + 12-slot grid stay fixed; the art library scrolls below.
 *   - Click an art tile → it fills the selected slot, or the first empty one.
 *   - Click a slot to choose where the next art goes; × clears a filled slot.
 *   - "Push Page N to Device" sends the page's full 12-slot layout at once.
 *
 * Device flow (APK LightMakeNewModel):
 *   page tab → 0xBD [0x17, page] display switch; push → daemon custom_art_push
 *   with a {slot: file_id} mapping (single N2 header + data + K0 per page).
 */

(function () {
  "use strict";

  const PAGES = 3;
  const SLOTS = 12;

  let currentPage = 0;
  let selectedSlot = null;
  // assignments[page][slot] = {fileId, thumb} | null
  const assignments = Array.from({ length: PAGES }, () => new Array(SLOTS).fill(null));
  let initialized = false;

  function init() {
    if (initialized) return;
    const panel = document.getElementById("panel-design");
    if (!panel) return;

    initialized = true;
    initPageTabs(panel);
    buildSlotGrid(panel);
    initLibraryClicks(panel);
    initPushButton(panel);
  }

  // ── Page tabs ────────────────────────────────────────────────────────────

  function initPageTabs(panel) {
    const tabs = panel.querySelectorAll(".page-tab");
    tabs.forEach((btn) => {
      btn.addEventListener("click", () => {
        const page = parseInt(btn.dataset.page, 10);
        tabs.forEach((b, i) => b.classList.toggle("active", i === page));
        currentPage = page;
        selectedSlot = null;
        renderSlots();
        updatePushLabel();
        // Switch device display to this page
        window.pywebview?.api?.device_call?.("design.use_user_define_index", [page])
          .then((raw) => {
            let r;
            try { r = typeof raw === "string" ? JSON.parse(raw) : raw; } catch { r = {}; }
            if (r && r.success) {
              window.showToast(`Switched to Page ${page + 1}`, "success", " BLE");
            }
          })
          .catch(() => {});
      });
    });
    if (tabs.length > 0) tabs[0].classList.add("active");
  }

  // ── Slot grid ────────────────────────────────────────────────────────────

  function buildSlotGrid(panel) {
    const grid = panel.querySelector("#custom-art-slot-grid");
    if (!grid) return;

    grid.innerHTML = "";
    for (let i = 0; i < SLOTS; i++) {
      const slot = document.createElement("div");
      slot.className = "custom-art-slot";
      slot.dataset.slot = i;
      slot.textContent = `${i + 1}`;

      const clear = document.createElement("button");
      clear.className = "slot-clear";
      clear.title = "Clear slot";
      clear.textContent = "×";
      clear.addEventListener("click", (e) => {
        e.stopPropagation();
        assignments[currentPage][i] = null;
        if (selectedSlot === i) selectedSlot = null;
        renderSlots();
        markAssignedLibraryItems();
      });
      slot.appendChild(clear);

      slot.addEventListener("click", () => {
        selectedSlot = selectedSlot === i ? null : i;
        renderSlots();
      });

      // Drag & drop: drag a filled slot onto another to swap; drag art
      // from the library onto a slot to place it there.
      slot.addEventListener("dragstart", (e) => {
        if (!assignments[currentPage][i]) { e.preventDefault(); return; }
        e.dataTransfer.setData("text/x-slot", String(i));
        e.dataTransfer.effectAllowed = "move";
      });
      slot.addEventListener("dragover", (e) => {
        e.preventDefault();
        slot.classList.add("drag-over");
      });
      slot.addEventListener("dragleave", () => slot.classList.remove("drag-over"));
      slot.addEventListener("drop", (e) => {
        e.preventDefault();
        slot.classList.remove("drag-over");
        const page = assignments[currentPage];
        const fromSlot = e.dataTransfer.getData("text/x-slot");
        if (fromSlot !== "") {
          const from = parseInt(fromSlot, 10);
          if (from === i) return;
          [page[from], page[i]] = [page[i], page[from]];
        } else {
          const fileId = e.dataTransfer.getData("text/x-fileid");
          const thumb = e.dataTransfer.getData("text/x-thumb");
          if (!fileId) return;
          page[i] = { fileId, thumb };
        }
        renderSlots();
        markAssignedLibraryItems();
      });

      grid.appendChild(slot);
    }
    renderSlots();
  }

  function renderSlots() {
    const grid = document.getElementById("custom-art-slot-grid");
    if (!grid) return;
    grid.querySelectorAll(".custom-art-slot").forEach((slot, i) => {
      const a = assignments[currentPage][i];
      slot.classList.toggle("filled", !!a);
      slot.classList.toggle("selected", selectedSlot === i);
      slot.draggable = !!a;
      const img = slot.querySelector("img");
      if (a) {
        if (img) {
          img.src = a.thumb;
        } else {
          const el = document.createElement("img");
          el.src = a.thumb;
          slot.insertBefore(el, slot.firstChild);
        }
      } else if (img) {
        img.remove();
      }
    });
  }

  // ── Library → slot assignment ────────────────────────────────────────────

  function initLibraryClicks(panel) {
    const grid = panel.querySelector("#custom-art-cache-grid");
    if (!grid) return;
    // Delegate: tiles are re-rendered on search, the grid node persists.
    grid.addEventListener("click", (e) => {
      const tile = e.target.closest(".cache-thumb-item");
      if (!tile || !grid.contains(tile)) return;
      const img = tile.querySelector("img");
      const fileId = tile.dataset.fileId || img?.dataset.fileId;
      if (!fileId || !img) return;
      assignToSlot(fileId, img.src);
    });
    // Delegated dragstart so tiles can be dropped straight onto a slot.
    grid.addEventListener("dragstart", (e) => {
      const tile = e.target.closest(".cache-thumb-item");
      if (!tile || !grid.contains(tile)) return;
      const img = tile.querySelector("img");
      const fileId = tile.dataset.fileId || img?.dataset.fileId;
      if (!fileId || !img) { e.preventDefault(); return; }
      e.dataTransfer.setData("text/x-fileid", fileId);
      e.dataTransfer.setData("text/x-thumb", img.src);
      e.dataTransfer.effectAllowed = "copy";
    });
  }

  function assignToSlot(fileId, thumb) {
    const page = assignments[currentPage];
    let target = selectedSlot;
    if (target === null) {
      target = page.findIndex((a) => !a);
      if (target === -1) {
        window.showToast("Page is full — clear a slot first", "warning");
        return;
      }
    }
    page[target] = { fileId, thumb };
    // Advance the selection to the next empty slot so repeated clicks
    // fill the page in order without extra steps.
    const next = page.findIndex((a) => !a);
    selectedSlot = next === -1 ? null : next;
    renderSlots();
    markAssignedLibraryItems();
  }

  /** Dim library tiles already placed on the current page. */
  function markAssignedLibraryItems() {
    const grid = document.getElementById("custom-art-cache-grid");
    if (!grid) return;
    const placed = new Set(
      assignments[currentPage].filter(Boolean).map((a) => a.fileId)
    );
    grid.querySelectorAll(".cache-thumb-item").forEach((tile) => {
      const fid = tile.dataset.fileId || tile.querySelector("img")?.dataset.fileId;
      tile.classList.toggle("assigned", placed.has(fid));
    });
  }
  // Re-apply the dimming after the library re-renders (search/refresh).
  window.customArtSyncLibrary = markAssignedLibraryItems;

  // ── Push button ──────────────────────────────────────────────────────────

  function updatePushLabel() {
    const btn = document.getElementById("push-custom-art-btn");
    if (btn && !btn.disabled) btn.textContent = `Push Page ${currentPage + 1} to Device`;
  }

  function initPushButton(panel) {
    const btn = panel.querySelector("#push-custom-art-btn");
    if (!btn) return;

    btn.addEventListener("click", () => {
      if (!window.requireDevice()) return;

      const slots = {};
      assignments[currentPage].forEach((a, i) => {
        if (a) slots[i] = a.fileId;
      });
      if (Object.keys(slots).length === 0) {
        window.showToast("Fill at least one slot first", "warning");
        return;
      }

      btn.disabled = true;
      btn.textContent = "Pushing…";

      window.pywebview?.api?.custom_art_push?.(JSON.stringify(slots), currentPage)
        .then((raw) => {
          let result;
          try {
            result = typeof raw === "string" ? JSON.parse(raw) : raw;
          } catch {
            result = { success: false, error: "parse error" };
          }
          if (result && result.success) {
            // ACK ≠ device-confirmed: the daemon reports device_confirmed:false
            // because custom-art storage can't be verified on real HW (0x8E is
            // unreliable). Say "sent" (writes accepted) rather than "pushed"
            // (which overstates a confirmed result) until a device confirms.
            const verb = result.device_confirmed === false ? "sent" : "pushed";
            window.showToast(
              `Page ${currentPage + 1} ${verb} (${result.files_pushed} slot${result.files_pushed !== 1 ? "s" : ""})`,
              "success", " BLE");
          } else {
            window.showToast("Push failed: " + (result?.error || "unknown"), "error");
          }
        })
        .catch((err) => {
          window.showToast("Push error: " + err, "error");
        })
        .finally(() => {
          btn.disabled = false;
          updatePushLabel();
        });
    });
  }

  // R45 #1: force a (re)build of the slot grid. Exposed so the pixel sub-tab
  // nav and the startup safety net below can GUARANTEE the slots exist even if
  // a prior init() ran before the pixel-art template was injected, or the
  // panel's innerHTML was replaced after init. (Symptom: only the sub-tabs
  // render — the 12 slots + library are missing — when the app lands directly
  // on Pixel Art with no tab-change event.)
  window.buildCustomArtSlots = function () {
    const panel = document.getElementById("panel-design");
    if (!panel) return;
    initialized = true;
    initPageTabs(panel);
    buildSlotGrid(panel);
    initLibraryClicks(panel);
    initPushButton(panel);
    renderSlots();
  };

  // Self-heal on tab changes to make sure initialization happens if
  // templates were loaded after DOMContentLoaded.
  window.addEventListener("tab-changed", (e) => {
    if (e.detail && e.detail.tab === "pixel-art") {
      init();
    }
  });

  function bootstrap() {
    init();
    // If init() bailed earlier (panel not yet injected) the slots can be empty
    // and no later tab-change fires when Pixel Art is the LANDING tab — rebuild
    // directly, and kick the library load that the nav normally triggers.
    const grid = document.getElementById("custom-art-slot-grid");
    if (grid && grid.querySelectorAll(".custom-art-slot").length === 0 &&
        document.getElementById("panel-design")) {
      window.buildCustomArtSlots();
    }
    if (document.getElementById("pixel-art")?.classList.contains("active") &&
        window.loadCustomArtCacheGrid) {
      setTimeout(window.loadCustomArtCacheGrid, 60);
    }
  }

  // Bootstrap
  if (document.getElementById("panel-design")) {
    bootstrap();
  } else {
    document.addEventListener("DOMContentLoaded", bootstrap);
  }
})();
