/* widgets.js — Live music synchronizer, stocks ticker, and system monitor */

document.addEventListener("DOMContentLoaded", () => {
    // Frameless window titlebar button bindings
    const winMin = document.getElementById("win-min");
    const winMax = document.getElementById("win-max");
    const winClose = document.getElementById("win-close");

    if (winMin) winMin.addEventListener("click", () => window.pywebview?.api?.minimize_window());
    if (winMax) winMax.addEventListener("click", () => window.pywebview?.api?.maximize_window());
    if (winClose) winClose.addEventListener("click", () => window.pywebview?.api?.close_window());

    // (Frameless window drag handler lives in app.js, see "0. FRAMELESS WINDOW DRAG".)

    let sysmonTimer = null;
    let stockTimer = null;

    // ── 2. LIVE COVER ART ─────────────────────────────────────────────
    // Split to widgets_music.js for the 500-line cap; it exposes
    // window.startTrackPolling / window.stopTrackPolling and asks this file
    // which card is selected via window.selectedWidgetIs().
    const startTrackPolling = () => window.startTrackPolling?.();
    const stopTrackPolling = () => window.stopTrackPolling?.();

    // ── 3. YAHOO STOCKS TICKER WIDGET ──
    // R24 #9: no "Display" button — a symbol is shown automatically when typed
    // (Enter / blur) or selected from the saved list; "Add" saves + displays.
    window.displayTicker = function(symbol) {
        symbol = (symbol || "").trim().toUpperCase();
        if (!symbol) return;
        {
            window.showToast(`Fetching Yahoo price data for ${symbol}...`, "success");
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.apply_stock_ticker(symbol).then(resJson => {
                    if (resJson) {
                        const res = JSON.parse(resJson);
                        if (res.success) {
                            const stockCard = document.getElementById("widget-card-stock");
                            if (stockCard) stockCard.classList.add("widget-active");
                            window.showToast(`Displaying ${symbol} price frame!`, "success", " Ext");
                            const priceMock = document.querySelector(".ticker-price-mock");
                            const arrowMock = document.querySelector(".ticker-arrow-mock");
                            const nameMock = document.querySelector(".ticker-name-mock");

                            if (nameMock) nameMock.textContent = symbol;
                            if (priceMock) priceMock.textContent = `$${res.price}`;
                            if (arrowMock) {
                                arrowMock.textContent = res.change >= 0 ? "↑" : "↓";
                                arrowMock.style.color = res.change >= 0 ? "var(--secondary)" : "red";
                            }
                            showTickerDevicePreview(res.preview);
                            
                            // Re-trigger/update active stocks background sync
                            if (window.pywebview.api.toggle_stocks_sync) {
                                window.pywebview.api.toggle_stocks_sync(true, symbol);
                            }
                        } else {
                            const stockCard = document.getElementById("widget-card-stock");
                            if (stockCard) stockCard.classList.remove("widget-active");
                            window.showToast(res.error || `Failed to display ${symbol}`, "error");
                            showTickerDevicePreview(res.preview);
                        }
                    }
                });
            }
        }
    };

    // Auto-display: Enter or leaving the symbol box shows it (no Display button).
    const stockInput = document.getElementById("stock-symbol-input");
    if (stockInput) {
        stockInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") { e.preventDefault(); window.displayTicker(stockInput.value); }
        });
        stockInput.addEventListener("change", () => window.displayTicker(stockInput.value));
    }

    function refreshStockPreview() {
        const symbol = document.getElementById("stock-symbol-input")?.value.trim().toUpperCase();
        if (!symbol || !(window.pywebview && window.pywebview.api && window.pywebview.api.get_ticker_preview)) return;
        window.pywebview.api.get_ticker_preview(symbol).then(resJson => {
            try {
                if (!resJson) return;
                const res = JSON.parse(resJson);
                if (res.ok) {
                    const priceMock = document.querySelector(".ticker-price-mock");
                    const arrowMock = document.querySelector(".ticker-arrow-mock");
                    const nameMock = document.querySelector(".ticker-name-mock");

                    if (nameMock) nameMock.textContent = symbol;
                    if (priceMock) priceMock.textContent = `$${res.price}`;
                    if (arrowMock) {
                        arrowMock.textContent = res.change >= 0 ? "↑" : "↓";
                        arrowMock.style.color = res.change >= 0 ? "var(--secondary)" : "red";
                    }
                    showTickerDevicePreview(res.preview);
                }
            } catch (e) {}
        });
    }

    function showTickerDevicePreview(dataUrl) {
        const img = document.getElementById("ticker-device-preview");
        if (img && dataUrl) {
            img.src = dataUrl;
            img.style.display = "inline-block";
            // R46 #2: the stock ticker is the device's last-active element.
            if (selectedWidget === "stock" || selectedWidget === "stocks") window.markActiveDeviceFrame?.(dataUrl);
        }
    }


    // ── 4. SYSTEM STATS MONITOR ──
    // Rendering lives in widgets_sysmon.js; this file owns selection + the
    // Live (5s) timer. Called through `window` so the split is explicit rather
    // than depending on two files sharing a closure.
    const refreshSysmonPreview = (...a) => window.refreshSysmonPreview?.(...a);

    // R40 §4: the "Push to Device" button was removed — the Live (5s) header
    // toggle is the single control (on = stream sysmon to the device).

    // (Duplicate sysmonDisplayBtn block was removed; the wiring below at
    //  line ~403 was the second declaration of the same const. The first
    //  declaration at line ~284 already attaches the handler.)

    let selectedWidget = "music"; // Default selected widget is cover art
    // Single owner of the selection; widgets_music.js asks rather than keeping
    // a second copy that could drift.
    window.selectedWidgetIs = (id) => selectedWidget === id;
    let weatherTimer = null;  // R15 §3: 10-minute poll for the weather card

    // R15 §3: weather card icon SVGs (one per WeatherType). Inline so the
    // preview doesn't depend on an external sprite.
    const WEATHER_ICON_SVG = {
        1: '<circle cx="8" cy="8" r="3" fill="currentColor"/><g stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><line x1="8" y1="1" x2="8" y2="3"/><line x1="8" y1="13" x2="8" y2="15"/><line x1="1" y1="8" x2="3" y2="8"/><line x1="13" y1="8" x2="15" y2="8"/><line x1="3" y1="3" x2="4.5" y2="4.5"/><line x1="11.5" y1="11.5" x2="13" y2="13"/><line x1="3" y1="13" x2="4.5" y2="11.5"/><line x1="11.5" y1="4.5" x2="13" y2="3"/></g>', // Clear (sun)
        3: '<path d="M3,12 C1.5,12 0.5,10.5 0.5,9 C0.5,7.5 1.5,6 3,6 C3.5,4 5.5,3 8,3 C11,3 13.5,5.5 13.5,8.5 C13.5,10.5 12,12 10,12 Z" fill="none" stroke="currentColor" stroke-width="1.5"/>', // CloudySky
        5: '<path d="M3,11 C1.5,11 0.5,9.5 0.5,8 C0.5,6.5 1.5,5 3,5 C3.5,3 5.5,2 8,2 C11,2 13.5,4.5 13.5,7.5 C13.5,9.5 12,11 10,11 Z" fill="none" stroke="currentColor" stroke-width="1.5"/><line x1="4" y1="13" x2="6" y2="15" stroke="currentColor" stroke-width="1.2"/><line x1="12" y1="13" x2="10" y2="15" stroke="currentColor" stroke-width="1.2"/>', // Thunderstorm
        6: '<path d="M3,9 C1.5,9 0.5,7.5 0.5,6 C0.5,4.5 1.5,3 3,3 C3.5,1 5.5,0 8,0 C11,0 13.5,2.5 13.5,5.5 C13.5,7.5 12,9 10,9 Z" fill="none" stroke="currentColor" stroke-width="1.2"/><g stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><line x1="4" y1="11" x2="3" y2="13"/><line x1="8" y1="11" x2="7" y2="13"/><line x1="12" y1="11" x2="11" y2="13"/></g>', // Rain (drops)
        8: '<g fill="currentColor"><circle cx="5" cy="3" r="0.8"/><circle cx="9" cy="3" r="0.8"/><circle cx="13" cy="3" r="0.8"/><circle cx="3" cy="6" r="0.8"/><circle cx="7" cy="6" r="0.8"/><circle cx="11" cy="6" r="0.8"/><circle cx="15" cy="6" r="0.8"/><circle cx="5" cy="9" r="0.8"/><circle cx="9" cy="9" r="0.8"/><circle cx="13" cy="9" r="0.8"/></g>', // Snow (dots)
        9: '<g fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><line x1="2" y1="6" x2="14" y2="6"/><line x1="2" y1="9" x2="14" y2="9"/><line x1="2" y1="12" x2="14" y2="12"/></g>', // Fog (lines)
    };

    function renderWeatherPreview(info) {
        const tempEl = document.getElementById("weather-preview-temp");
        const iconEl = document.getElementById("weather-preview-icon");
        const locEl = document.getElementById("weather-preview-location");
        if (tempEl) tempEl.textContent = `${info.temperature_c}°`;
        if (iconEl) {
            const svg = WEATHER_ICON_SVG[info.weather_type] || WEATHER_ICON_SVG[1];
            iconEl.innerHTML = svg;
        }
        if (locEl) {
            // Truncate long location strings to keep the card tidy.
            const loc = info.location || "--";
            const short = loc.length > 28 ? `${loc.slice(0, 25)}…` : loc;
            locEl.textContent = short;
        }
    }

    function refreshWeatherPreview() {
        if (!window.pywebview || !window.pywebview.api) return;
        const api = window.pywebview.api;
        if (typeof api.get_weather !== "function") return;
        Promise.resolve(api.get_weather()).then(info => {
            if (info && typeof info === "object") renderWeatherPreview(info);
        });
    }

    function startWeatherPolling() {
        if (weatherTimer) return;
        refreshWeatherPreview();
        weatherTimer = setInterval(refreshWeatherPreview, 15 * 60 * 1000);
    }

    function stopWeatherPolling() {
        if (weatherTimer) {
            clearInterval(weatherTimer);
            weatherTimer = null;
        }
    }

    window.restoreActiveWidgetForDevice = function(mac) {
        if (!mac || !window.pywebview || !window.pywebview.api || !window.pywebview.api.live_job_list) return;
        window.pywebview.api.live_job_list(mac).then(resJson => {
            let res = resJson;
            if (typeof resJson === "string") {
                try { res = JSON.parse(resJson); } catch (e) {}
            }
            // ADOPT the device's truth; never OVERRIDE the user's choice.
            //
            // This used to force `selectedWidget = "music"` whenever the device
            // had no live job — including 250ms after the user clicked System
            // Monitor. The click set the selection, this poll took it straight
            // back, and because the Live (5s) timer only runs while its widget
            // is selected, the card then sat frozen on whatever it read once.
            // Traced at 250ms resolution: true at 0ms, false at 250ms, and the
            // numbers never moved again.
            //
            // A running job is real state worth adopting. "No job running" is
            // NOT evidence the user wants cover art — most often it just means
            // no device is connected yet, which is exactly when someone is
            // clicking around the widgets. House rule: resolve user intent at
            // interaction time, and never silently swallow a click.
            const activeJob = (res && res.success && res.jobs)
                ? res.jobs.find(j => !j.done && !j.cancelled)
                : null;
            if (activeJob) {
                selectedWidget = activeJob.kind;
            }
            const cards = ["music", "stock", "sysmon", "weather", "notif-manual", "notif-mirror"];
            cards.forEach(id => {
                const cardEl = document.getElementById(`widget-card-${id}`);
                if (cardEl) {
                    cardEl.classList.toggle("widget-active", id === selectedWidget);
                }
            });
            syncActiveWidgetPreviewsOnly();
        });
    };

    function selectWidget(widgetId) {
        selectedWidget = widgetId;

        // Update visual card states
        const cards = ["music", "stock", "sysmon", "weather", "notif-manual", "notif-mirror"];
        cards.forEach(id => {
            const cardEl = document.getElementById(`widget-card-${id}`);
            if (cardEl) {
                cardEl.classList.toggle("widget-active", id === widgetId);
            }
        });

        // Trigger background sync toggles
        syncActiveWidget();
    }

    function syncActiveWidgetPreviewsOnly() {
        const isTabActive = document.getElementById("data-sources")?.classList.contains("active");

        // 1. Music (Cover Art)
        const startMusic = isTabActive && (selectedWidget === "music");
        if (startMusic) {
            startTrackPolling();
        } else {
            stopTrackPolling();
        }

        // 2. Stocks
        const symbol = document.getElementById("stock-symbol-input")?.value.trim().toUpperCase();
        const startStocks = isTabActive && (selectedWidget === "stock") && !!symbol;
        if (startStocks) {
            refreshStockPreview();
            if (!stockTimer) {
                stockTimer = setInterval(refreshStockPreview, 15000);
            }
        } else {
            if (stockTimer) {
                clearInterval(stockTimer);
                stockTimer = null;
            }
        }

        // 3. System Monitor
        const sysmonLiveChecked = sysmonLive ? sysmonLive.checked : true;
        const startSysmon = isTabActive && (selectedWidget === "sysmon") && sysmonLiveChecked;
        if (startSysmon) {
            refreshSysmonPreview();
            if (!sysmonTimer) {
                sysmonTimer = setInterval(refreshSysmonPreview, 5000);
            }
        } else {
            if (sysmonTimer) {
                clearInterval(sysmonTimer);
                sysmonTimer = null;
            }
        }

        // 4. Weather
        const weatherLiveChecked = weatherLive ? weatherLive.checked : true;
        const startWeather = isTabActive && (selectedWidget === "weather") && weatherLiveChecked;
        if (startWeather) {
            startWeatherPolling();
        } else {
            stopWeatherPolling();
        }
    }

    function syncActiveWidget() {
        if (!window.pywebview || !window.pywebview.api) return;
        const isTabActive = document.getElementById("data-sources")?.classList.contains("active");

        // 1. Music (Cover Art)
        const startMusic = isTabActive && (selectedWidget === "music");
        window.pywebview.api.toggle_music_sync(startMusic);
        if (startMusic) {
            startTrackPolling();
        } else {
            stopTrackPolling();
        }

        // 2. Stocks
        const symbol = document.getElementById("stock-symbol-input")?.value.trim().toUpperCase();
        const startStocks = isTabActive && (selectedWidget === "stock") && !!symbol;
        if (window.pywebview.api.toggle_stocks_sync) {
            window.pywebview.api.toggle_stocks_sync(startStocks, symbol || "");
        }
        if (startStocks) {
            refreshStockPreview();
            if (!stockTimer) {
                stockTimer = setInterval(refreshStockPreview, 15000);
            }
        } else {
            if (stockTimer) {
                clearInterval(stockTimer);
                stockTimer = null;
            }
        }

        // 3. System Monitor
        const sysmonLiveChecked = sysmonLive ? sysmonLive.checked : true;
        const startSysmon = isTabActive && (selectedWidget === "sysmon") && sysmonLiveChecked;
        if (window.pywebview.api.toggle_sysmon_sync) {
            window.pywebview.api.toggle_sysmon_sync(startSysmon);
        }
        if (startSysmon) {
            refreshSysmonPreview();
            if (!sysmonTimer) {
                sysmonTimer = setInterval(refreshSysmonPreview, 5000);
            }
        } else {
            if (sysmonTimer) {
                clearInterval(sysmonTimer);
                sysmonTimer = null;
            }
        }

        // 4. Weather
        const weatherLiveChecked = weatherLive ? weatherLive.checked : true;
        const startWeather = isTabActive && (selectedWidget === "weather") && weatherLiveChecked;
        if (window.pywebview.api.toggle_weather_sync) {
            window.pywebview.api.toggle_weather_sync(startWeather);
        }
        if (startWeather) {
            startWeatherPolling();
        } else {
            stopWeatherPolling();
        }
    }

    function bindCardSelection(cardId, widgetName) {
        const card = document.getElementById(cardId);
        if (card) {
            card.style.cursor = "pointer";
            card.addEventListener("click", (e) => {
                if (e.target.closest("input") || e.target.closest("button") || e.target.closest("select")) {
                    if (e.target.closest("#apply-stock-btn") || e.target.closest("#sysmon-live")) {
                        selectWidget(widgetName);
                    }
                    return;
                }
                selectWidget(widgetName);
            });
        }
    }

    bindCardSelection("widget-card-music", "music");
    bindCardSelection("widget-card-stock", "stock");
    bindCardSelection("widget-card-sysmon", "sysmon");
    // R15 §3: new cards in the Live Widgets grid.
    bindCardSelection("widget-card-weather", "weather");
    bindCardSelection("widget-card-notif-manual", "notif-manual");
    bindCardSelection("widget-card-notif-mirror", "notif-mirror");

    // R18 item 1: populate the weather card on load — no click required.
    // (Preview only; pushing to the device still happens when weather is the
    // selected widget, per the one-active-widget model.)
    refreshWeatherPreview();

    const sysmonLive = document.getElementById("sysmon-live");
    if (sysmonLive) {
        // R40 §4: persist the Live (5s) state across launches.
        const saved = localStorage.getItem("divoom.sysmonLive");
        if (saved !== null) sysmonLive.checked = saved === "1";
        sysmonLive.addEventListener("change", () => {
            localStorage.setItem("divoom.sysmonLive", sysmonLive.checked ? "1" : "0");
            if (sysmonLive.checked) {
                selectWidget("sysmon");
            } else {
                syncActiveWidget();
            }
        });
    }

    // R40 §4: Weather Live (15m) toggle — replaces the old Push button.
    const weatherLive = document.getElementById("weather-live");
    if (weatherLive) {
        const saved = localStorage.getItem("divoom.weatherLive");
        if (saved !== null) weatherLive.checked = saved === "1";
        const applyWeatherLive = () => {
            localStorage.setItem("divoom.weatherLive", weatherLive.checked ? "1" : "0");
            syncActiveWidget();
        };
        weatherLive.addEventListener("change", applyWeatherLive);
    }

    // ── 5. TAB-CHANGED AUTOMATIC WIDGET WORKER CONTROL ──
    window.addEventListener("tab-changed", (e) => {
        const tab = e.detail.tab;
        const mac = (document.getElementById("banner-device-mac")?.textContent || "").trim();
        if (tab === "data-sources") {
            // Auto-refresh all previews on tab open (no device push until card is selected)
            refreshSysmonPreview();
            refreshWeatherPreview();
            const sym = document.getElementById("stock-symbol-input")?.value.trim().toUpperCase();
            if (sym) refreshStockPreview();
            if (mac && mac !== "None") {
                window.restoreActiveWidgetForDevice(mac);
            } else {
                selectWidget(selectedWidget);
            }
        } else {
            // Stop local preview pollers (but let the daemon background tasks keep running)
            stopTrackPolling();
            if (sysmonTimer) {
                clearInterval(sysmonTimer);
                sysmonTimer = null;
            }
            if (stockTimer) {
                clearInterval(stockTimer);
                stockTimer = null;
            }
            stopWeatherPolling();
            ["music", "stock", "sysmon", "weather", "notif-manual", "notif-mirror"].forEach(id => {
                const cardEl = document.getElementById(`widget-card-${id}`);
                if (cardEl) cardEl.classList.remove("widget-active");
            });
        }
    });

    // Startup Delay Inits
    setTimeout(() => window.loadTickers && window.loadTickers(), 1500);
    setTimeout(() => {
        if (document.getElementById("data-sources")?.classList.contains("active")) {
            window.dispatchEvent(new CustomEvent("tab-changed", { detail: { tab: "data-sources" } }));
        } else {
            refreshSysmonPreview();
            refreshWeatherPreview();
            const sym = document.getElementById("stock-symbol-input")?.value.trim().toUpperCase();
            if (sym) refreshStockPreview();
        }
    }, 1800);
});
