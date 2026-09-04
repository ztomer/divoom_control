/* widgets_tickers.js — R44: saved stock-ticker chip list CRUD (split from
   widgets.js for the 500-LOC rule). Self-contained DOM/DivoomState work;
   the rest of widgets.js calls window.loadTickers(). */
document.addEventListener("DOMContentLoaded", () => {
    function renderTickers(symbols) {
        const el = document.getElementById("tickers-list");
        if (!el) return;
        el.innerHTML = "";
        (symbols || []).forEach(sym => {
            const chip = document.createElement("span");
            chip.className = "ticker-chip";
            const label = document.createElement("button");
            label.className = "ticker-chip-label";
            label.textContent = sym;
            label.title = `Display ${sym}`;
            label.addEventListener("click", () => {
                const input = document.getElementById("stock-symbol-input");
                if (input) input.value = sym;
                window.displayTicker(sym);   // R24 #9: selecting displays immediately
            });
            const rm = document.createElement("button");
            rm.className = "ticker-chip-remove";
            rm.textContent = "×";
            rm.title = `Remove ${sym}`;
            rm.addEventListener("click", () => removeTicker(sym));
            chip.append(label, rm);
            el.appendChild(chip);
        });
    }

    function loadTickers() {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.get_tickers) {
            window.pywebview.api.get_tickers().then(json => {
                try { window.DivoomState.savedTickers = JSON.parse(json) || []; renderTickers(window.DivoomState.savedTickers); } catch (e) {}
            });
        }
    }

    function persistTickers() {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_tickers) {
            window.pywebview.api.set_tickers(JSON.stringify(window.DivoomState.savedTickers));
        }
        renderTickers(window.DivoomState.savedTickers);
    }

    function removeTicker(sym) {
        window.DivoomState.savedTickers = window.DivoomState.savedTickers.filter(s => s !== sym);
        persistTickers();
    }

    const addTickerBtn = document.getElementById("add-ticker-btn");
    if (addTickerBtn) {
        addTickerBtn.addEventListener("click", () => {
            const sym = document.getElementById("stock-symbol-input")?.value.trim().toUpperCase();
            if (!sym) { window.showToast("Enter a ticker symbol first.", "error"); return; }
            if (!window.DivoomState.savedTickers.includes(sym)) {
                window.DivoomState.savedTickers.push(sym);
                persistTickers();
                window.showToast(`Saved ${sym}`, "success");
            }
            window.displayTicker(sym);   // R24 #9: Add also displays
        });
    }

    window.loadTickers = loadTickers;
});
