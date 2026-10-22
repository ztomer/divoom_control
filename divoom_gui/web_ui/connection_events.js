/* connection_events.js — connection actions + live status (extracted from
 * app_globals.js to keep files under the 500-LOC gate).
 *
 * Loaded AFTER app_globals.js (which owns DivoomState + the shared utilities
 * this module calls). Two update paths feed the connection dot + banner:
 *   1. event-driven  — window.Divoom.onDaemonEvent, pushed by the GUI's daemon
 *      subscription on every connect/disconnect (R58/UI-reliability). Immediate.
 *   2. polling        — refreshConnectionState, the heartbeat that catches a
 *      mid-session DEGRADED drop the connect/disconnect events don't cover.
 * The heartbeat is the safety net; the event is the fast path.
 *
 * #6: every path below funnels through window.setConnectionState — the SOLE
 * writer of the dot class, the banner, and DivoomState.appConnected. Three
 * writers with no funnel is how the UI got stuck on "connecting" while the
 * daemon was connected: the click flow owned the dot, the heartbeat refused
 * to heal upward (early-return unless already connected), and a status event
 * arriving mid-click wrote around both.
 */

// ── THE funnel for connection surface state ─────────────────────────────
// mode: "connecting" | "active" | "degraded" | "inactive".
// A degraded link stays "connected" (the daemon self-heals); "connecting"
// never wipes the banner (a pending click must not erase the last known
// device before its outcome is known).
//
// P7.2: the dot is a `transport-mark` now. Its SHAPE says which transport is
// being driven (circle = Bluetooth, square = Wi-Fi, 2x2 grid = the Virtual
// Wall) and its FILL says what the link is doing (solid = linked, solid with
// a bar = degraded, hollow = not linked, hollow and pulsing = a connect in
// flight). Colour reinforces. One funnel call writes the class, the
// aria-label and nothing else -- the `title` is DELETED, not made reachable:
// the dot is pointer-events:none, so a title could never be seen, and a
// hit-testable 10px corner dot would swallow the clicks it covers.
window._transportOfMac = function(mac) {
    const m = (mac || "").trim();
    if (!m) return null;
    if (m === "MatrixWall") return "wall";
    if (m.startsWith("LAN:")) return "lan";
    return "ble";
};

// The dot's one spoken name: it names BOTH axes, because the shape names
// them visually and the label is what a screen reader hears. `transport` is
// null when no target is known -- then the label says the state alone.
window._connectionStatusLabel = function(mode, transport) {
    const what = transport === "wall" ? "Virtual Wall"
        : transport === "lan" ? "Wi-Fi screen"
        : transport === "ble" ? "Bluetooth screen" : null;
    const state = mode === "active" ? "connected"
        : mode === "degraded" ? "link degraded, reconnecting"
        : mode === "connecting" ? "connecting" : "disconnected";
    return what ? `Connection status: ${state} — ${what}`
                 : `Connection status: ${state}`;
};

window.setConnectionState = function(s) {
    s = s || {};
    const mode = s.mode || "inactive";
    const dot = document.getElementById("global-status-dot");
    if (dot) {
        // ONE transport derivation, in the one writer (P7.2's second
        // defect). The transport used to be derived TWICE -- the heartbeat
        // read the banner's mac, the event path read the event's mac -- and
        // the two disagreed about the wall, which could be painted the BLE
        // hue. Under the shape vocabulary a wrong derivation paints the
        // wrong SHAPE, which is worse than a wrong colour, so this is the
        // only place the transport is decided: the mac this call is about,
        // else the SELECTED target (the dot speaks for the selected target
        // only), else Bluetooth as the default shape.
        const selectedMac = (typeof window._activeDeviceMac === "function")
            ? window._activeDeviceMac() : null;
        const knownTransport = window._transportOfMac(s.mac)
            || window._transportOfMac(selectedMac);
        const transport = knownTransport || "ble";
        const fill = mode === "active" ? "linked"
            : mode === "degraded" ? "fault"
            : mode === "connecting" ? "pending" : "open";
        dot.className = "transport-mark mark-" + transport + " mark-" + fill;
        dot.setAttribute("aria-label", window._connectionStatusLabel(mode, knownTransport));
        dot.removeAttribute("style");
    }
    // The funnel writes BOTH views of one fact -- the panel's own flags
    // (what jewels, requireDevice and getFleetStatus read) and appConnected,
    // which is the selected target's link and nothing more. They must agree,
    // and "connecting" is the case that made them disagree: it says a connect
    // is IN FLIGHT, which is not a statement about the link. Only a settled
    // answer moves the link.
    //
    // The banner has always followed that rule -- "connecting" never wipes it,
    // because a pending click must not erase the last known device before its
    // outcome is known -- and the link flags did not.
    const list = window.DivoomState.discoveredDevices || [];
    if (s.mac) {
        const known = list.find(d => d.address === s.mac);
        // A pending connect names a mac (the dot's shape needs it) but must
        // not move the panel's flags: the old code got that by passing no mac
        // at all, so it says so here instead.
        if (known && mode !== "connecting") {
            known.daemonOwned = (mode === "active" || mode === "degraded");
            known.activityState = mode === "degraded" ? "degraded"
                : mode === "active" ? "active"
                : mode === "inactive" ? "disconnected" : known.activityState;
        }
    } else if (mode === "inactive") {
        // Nobody named: the daemon (or the bridge) is gone for every panel.
        list.forEach(d => { d.daemonOwned = false; d.activityState = "disconnected"; });
    }
    // appConnected is the SELECTED target's link (app_globals.js), and a
    // pending connect is NOT a lost link: "connecting" says a connect is in
    // flight, and only the daemon saying so ("inactive") means the link is
    // down.
    //
    // It cost the app a real write: `requireDevice()` gates every channel
    // write, and for the Virtual Wall (a composite of panels, with no
    // discoveredDevices record of its own) it falls back to that app-wide
    // flag. So every wall write in the window of a pending connect was
    // refused with "Connect a device first" and DROPPED, never reaching the
    // daemon. The window is ordinary rather than exotic: the app's own
    // startup restore (app_init.js) reconnects the last device a second after
    // load, so the writes that land in that second are lost.
    //
    // The panel's own flags above are already right: a pending connect names
    // no mac, so it never touched them. This line was the one view of the
    // fact that a pending connect could move.
    window.DivoomState.appConnected = (mode === "active" || mode === "degraded")
        || (mode === "connecting" && window.DivoomState.appConnected);
    const shown = (document.getElementById("banner-device-mac")?.textContent || "").trim();
    if ((mode === "active" || mode === "degraded") && s.mac) {
        let name = s.name || s.mac;
        const found = (window.DivoomState.discoveredDevices || [])
            .find(d => d.address === s.mac);
        if (found && found.name) name = found.name;
        const bannerName = document.getElementById("banner-device-name");
        const bannerMac = document.getElementById("banner-device-mac");
        if (bannerName) bannerName.textContent = name;
        if (bannerMac) bannerMac.textContent = s.mac;
    } else if (mode === "inactive") {
        const bannerName = document.getElementById("banner-device-name");
        const bannerMac = document.getElementById("banner-device-mac");
        if (bannerName) bannerName.textContent = "None";
        if (bannerMac) bannerMac.textContent = "None";
    }
    // The deck follows the display: choosing the wall (or leaving it) changes
    // what its levels write to (P6.6).
    const now = (document.getElementById("banner-device-mac")?.textContent || "").trim();
    if (now !== shown && window.SpatialStage?.showDeck) window.SpatialStage.showDeck();
};

// ── 3. CONNECTION ACTIONS ──
// updateSidebarSpeakerIcon was removed — speaker status now lives in
// Settings → Devices tables. Kept as a no-op for backward compatibility.
window.updateSidebarSpeakerIcon = function(_hasSpeaker) {
    return;
};

window.connectDevice = function(name, address) {
    window.showToast(`Connecting to ${name}...`, "success");
    // The mac goes with the state: the dot's SHAPE is the transport of the
    // target being connected, so a connect to a Wi-Fi panel shows the square
    // and not the Bluetooth circle it fell back to before.
    window.setConnectionState({ mode: "connecting", mac: address });
    // R35 §2: pulse the sidebar chip being connected. Cleared by re-render on
    // success or explicitly on failure.
    const deviceDot = document.querySelector(
        `#device-dots [data-value="${(window.CSS && CSS.escape) ? CSS.escape(address) : address}"]`);
    if (deviceDot) {
        deviceDot.classList.add("connecting");
    }

    if (window.pywebview && window.pywebview.api) {
        // R57 watchdog: if the daemon never answers the connect (dead/!wedged
        // central that the Rust BleCentral timeout + client read_timeout failed
        // to catch — defense in depth), don't leave the UI stuck on "connecting".
        // The client read_timeout is ~30s; fire the watchdog a beat after.
        let connectWatchdog = null;
        connectWatchdog = setTimeout(() => {
            window.setConnectionState({ mode: "inactive", mac: address });
            window.showToast(`Background service not responding for ${name}. Try Reconnect.`, "error");
            if (window.renderDeviceDots) window.renderDeviceDots();
        }, 35000);
        window.pywebview.api.connect_single_device(address).then(res => {
            clearTimeout(connectWatchdog);
            if (res) {
                const type = window._transportOfMac(address);
                const label = type === "wall" ? " Wall" : (type === "lan" ? " LAN" : " BLE");
                window.showToast(`Connected to ${name}!`, "success", label);
                window.setConnectionState({ mode: "active", mac: address, name: name });
                window._updateDeviceLabel(name);
                // R32 §C2: prefer the last-pushed preview; fall back to the
                // product icon when this device hasn't been pushed to yet.
                window.restoreDevicePreview(address);
                if (window.renderDeviceDots) window.renderDeviceDots();
                if (window.loadDeviceName) window.loadDeviceName();
                if (window.restoreActiveWidgetForDevice) window.restoreActiveWidgetForDevice(address);
                // banner-device-res and banner-device-speaker moved to Settings → Devices.
                // Their textContent assignments are intentionally skipped here.
                // Whether it has a speaker is the vendor app's per-model switch,
                // as the daemon reports it (P5.1) -- not a guess from the name.
                window.updateSidebarSpeakerIcon(window.panelHasSpeaker(address) !== false);
                const sidebarSelect = document.getElementById("sidebar-device-select");
                if (sidebarSelect) sidebarSelect.value = address;
                if (window.updateSyncTargetList) window.updateSyncTargetList();
                // The channel cards follow the PANEL IN HAND (P3.6), and the
                // panel in hand is the one the channel bar writes to -- not
                // the panel that happened to answer this connect. A late
                // reply for a panel the user has moved on from used to put
                // that panel's abilities back on screen: a radio offered to a
                // panel with no radio. The daemon says whether the panel in
                // hand has a radio and whether it has the VJ channel.
                if (window.updateChannelButtonsVisibility) {
                    window.updateChannelButtonsVisibility(
                        (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null);
                }
            } else {
                window.setConnectionState({ mode: "inactive", mac: address });
                // BLE Hardening P1: show the daemon's actionable reason (asleep /
                // BT off / held by the phone app), not a generic failure.
                if (window.pywebview?.api?.get_last_connect_error) {
                    window.pywebview.api.get_last_connect_error().then(msg => {
                        window.showToast(msg && msg.trim()
                            ? `${name}: ${msg}` : `Failed to connect to ${name}`, "error");
                    });
                } else {
                    window.showToast(`Failed to connect to ${name}`, "error");
                }
                // R34 §2: stop the pulse + restore the per-device hue.
                if (window.renderDeviceDots) window.renderDeviceDots();
                window._updateDeviceLabel(null);
                window.updateSidebarSpeakerIcon(false);
                if (window.updateSyncTargetList) window.updateSyncTargetList();
                // A connect that failed says nothing about what the panel IS:
                // the bar describes the panel in hand (its abilities), and the
                // connection dot is where the link is shown (P7.2). So the
                // cards are recomputed for the panel in hand, not taken away.
                if (window.updateChannelButtonsVisibility) {
                    window.updateChannelButtonsVisibility(
                        (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null);
                }
            }
        });
    } else {
        // No bridge (page loaded before pywebview attached): never leave the
        // dot parked on "connecting" with nothing that can clear it.
        window.setConnectionState({ mode: "inactive" });
        window.showToast("Backend not ready — retry in a moment.", "error");
    }
};

// ── BLE Hardening P6: appbar connection heartbeat ─────────────────────────
// The connect/disconnect handlers set the dot at transition time, but a link
// can DROP mid-session (device sleeps, RF blip). Poll the daemon's honest
// connection_state so the dot reflects DEGRADED (amber) and a genuine drop,
// not a stale solid "connected". (The fast path is the event-driven
// window.Divoom.onDaemonEvent below; this heartbeat is the safety net.)
//
// P7.2: the heartbeat no longer derives the transport. It used to read the
// banner's mac here and the event's mac in the event path, and the two
// disagreed about the wall — which could be painted the Bluetooth hue. The
// funnel derives it once, from the mac this call is about.
window.refreshConnectionState = function() {
    // No latch: an authoritative answer heals in BOTH directions. The old
    // early-return unless appConnected meant a false flag could never become
    // true again no matter what the daemon reported (#6).
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.get_connection_state) return;
    api.get_connection_state().then(raw => {
        let s;
        try { s = JSON.parse(raw); } catch (e) { return; }
        if (s && s.selected && window.SpatialStage?.followSelection) window.SpatialStage.followSelection(s.selected);
        const state = s && s.state;
        // The daemon's ACTIVE panel — the target the answer is about.
        const selected = (s && s.selected) || null;
        if (state === "degraded") {
            // Reports connected but a write/drop just failed — show amber, keep
            // appConnected (the daemon's live-job self-heal may revive it).
            window.setConnectionState({ mode: "degraded", mac: selected });
        } else if (state === "disconnected" || !s || !s.connected) {
            // Genuinely dropped — or the daemon explicitly reports disconnected
            // while a stale connected:true lingered. Flip the dot + the global
            // flag so the UI stops claiming a live link; a disconnected state
            // must NOT be masked by a stale connected flag. The answer is about
            // the SELECTED panel (the proxy asks for it by mac), so name it;
            // no answer at all is the daemon gone, which names nobody.
            const sel = (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null;
            window.setConnectionState({ mode: "inactive", mac: s ? sel : null });
        } else {
            // Honest connected (ble/lan/wall) — the funnel gives the dot the
            // SHAPE of the transport and the FILL of the link.
            window.setConnectionState({ mode: "active", mac: selected });
        }
    }).catch(() => {});
};

// R58/UI-reliability: live daemon event forwarder. The GUI subscribes to the
// daemon and calls this with every `status`/`notification` event, so the
// dashboard reflects connect/disconnect IMMEDIATELY (event-driven) instead of
// waiting for the 4s polling heartbeat. The event carries honest state
// (`connected` + `mac`/`lan_ip`) — see daemon `status_payload` / `initial_status`.
window.Divoom = window.Divoom || {};
window.Divoom.onDaemonEvent = function(ev) {
    if (!ev || typeof ev !== "object") return;
    const type = ev.type;
    if (type !== "status") return;  // notifications are surfaced natively by macOS
    const connected = ev.connected === true;
    const degraded = ev.state === "degraded";
    const dropped = ev.state === "disconnected";
    const mac = ev.lan_ip ? ("LAN:" + ev.lan_ip) : (ev.mac || null);
    // A degraded link stays "connected" (the daemon self-heals); a genuine drop
    // or an explicit `disconnected` state flips appConnected so the rest of the
    // UI stops acting connected — an honest state must NOT be masked by a stale
    // connected flag (the P6 honest-state regression). As the authoritative
    // writer, a status event also clears a stale "connecting" dot left by a
    // click flow whose promise never settled (#6).
    // Per-panel first (2026-09-12): the daemon names the panel a status is
    // about, and with a fleet the global dot is the SELECTED panel's link,
    // not whichever panel last spoke. An event naming nobody is fleet-wide.
    const list = window.DivoomState.discoveredDevices || [];
    const known = mac ? list.find(d => d.address === mac) : null;
    const stateWord = (!connected || dropped) ? "disconnected" : (degraded ? "degraded" : "active");
    if (known) {
        known.activityState = stateWord;
        known.daemonOwned = connected && !dropped;
    } else if (!mac) {
        list.forEach(d => { d.activityState = stateWord; if (stateWord === "disconnected") d.daemonOwned = false; });
    }
    const activeMac = (typeof window._activeDeviceMac === "function") ? window._activeDeviceMac() : null;
    // A selection that is not a known panel (a bench placeholder, a stale
    // restore) does not own the dot; the event then speaks for the app.
    const selectionIsReal = !!activeMac && list.some(d => d.address === activeMac);
    const aboutSelected = !mac || !selectionIsReal || mac === activeMac;
    if (aboutSelected) {
        if (!connected || dropped) {
            window.setConnectionState({ mode: "inactive", mac: mac });
        } else if (degraded) {
            window.setConnectionState({ mode: "degraded", mac: mac });
        } else {
            // P7.2: no transport here. The event's mac went in and the funnel
            // derives the shape from it — the old ternary here said "ble" for
            // anything that was not a LAN mac, so the wall could be painted
            // the Bluetooth hue (and, under the shape vocabulary, the wrong
            // SHAPE).
            window.setConnectionState({ mode: "active", mac: mac });
        }
    }
    if (window.renderDeviceDots) window.renderDeviceDots();
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
};

// R59/event-driven: the daemon pushes owned-device changes as `owned_devices`
// events, so the 4s get_device_activity poll is gone. Merge the event's device
// list into discoveredDevices (mirrors the old refreshOwnedDevices merge): drop
// all daemonOwned flags, then re-mark the ones the daemon reports as owned.
window.Divoom = window.Divoom || {};
window.Divoom.onOwnedDevices = function(ev) {
    if (!ev || !Array.isArray(ev.devices)) return;
    const list = window.DivoomState.discoveredDevices || [];
    list.forEach(d => { d.daemonOwned = false; });
    ev.devices.forEach(dev => {
        const address = dev.address;
        if (!address) return;
        let known = list.find(d => d.address === address);
        if (!known) {
            known = { address: address, name: dev.name || "Screen", daemonOwned: true };
            list.push(known);
        } else {
            known.daemonOwned = true;
            if (dev.name && known.name !== dev.name) known.name = dev.name;
        }
        known.activityKind = dev.kind || "idle";
        known.activityState = dev.state || "active";
    });
    if (window.renderDeviceDots) window.renderDeviceDots();
    // The bench and deck jewels read daemonOwned too (2026-09-12).
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
    // What each owned panel IS (model, size, speaker): the daemon's word, by mac (P5.1).
    if (window.refreshPanelFacts) window.refreshPanelFacts();
    // The daemon owns the ACTIVE panel; the bench follows its word.
    const active = ev.devices.find(dev => dev.selected === true);
    if (active && active.address && window.SpatialStage?.followSelection) window.SpatialStage.followSelection(active.address);
};

// The daemon's `selection` broadcast: a menubar switch, a CLI call, or its
// own first-link default. One funnel with a bench click.
window.Divoom.onSelection = function(ev) {
    if (!ev || !ev.mac) return;
    if (window.SpatialStage?.followSelection) window.SpatialStage.followSelection(ev.mac);
};

// R59/event-driven: macOS notification-monitor status. The daemon broadcasts
// `notif_status` (same shape as get_notification_listener_status) so the 5s
// poll is gone. renderMacNotifStatus lives in settings_notifications.js.
window.Divoom.onNotifStatus = function(ev) {
    if (window.renderMacNotifStatus) window.renderMacNotifStatus(ev);
};

// R59/event-driven: hot-channel update progress. The daemon broadcasts
// `hot_progress` (phases: starting/done/error) so the 600ms poll is gone.
window.Divoom.onHotProgress = function(ev) {
    if (!ev || !ev.phase) return;
    if (window.applyProgress) window.applyProgress(ev);
    if (ev.phase === "done" || ev.phase === "error") {
        if (window.finishProgress) window.finishProgress(ev);
        if (window._pollTimer) { clearInterval(window._pollTimer); window._pollTimer = null; }
    }
};

// Activity event: daemon or menubar switched channel or started a job
window.Divoom.onActivity = function(ev) {
    if (!ev || !ev.mac || !ev.kind) return;
    const mac = ev.mac;
    const kind = ev.kind;
    const opts = Object.assign({}, ev.opts || {});
    // A live job's frame arrives with the pixels; the preview mirrors it.
    if (ev.preview && !opts.src) opts.src = ev.preview;
    if (typeof window.saveDeviceChannel === "function") {
        window.saveDeviceChannel(mac, kind, opts);
    }
    if (window.DisplayPreviewRegistry) {
        window.DisplayPreviewRegistry.get(mac).setActivity(kind, opts);
    }
    window.DivoomState.deviceActivity = window.DivoomState.deviceActivity || {};
    window.DivoomState.deviceActivity[mac] = { kind: kind, at: Date.now(), opts: opts };
    if (mac === (typeof window._activeDeviceMac === "function" ? window._activeDeviceMac() : null)) {
        window.DivoomState.activeChannel = kind;
        const card = document.querySelector(`.tab-btn[data-channel="${kind}"]`);
        if (card) {
            document.querySelectorAll(".tab-btn[data-channel]").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
        }
        if (typeof window.showChannelPanel === "function") {
            window.showChannelPanel(kind);
        }
        if (typeof window.syncChannelControlsToDisplay === "function") {
            window.syncChannelControlsToDisplay(mac);
        }
    }
    if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
};

window.startConnectionHeartbeat = function() {
    // No polling: connection state, owned devices, and daemon health are all
    // event-driven now (window.Divoom.onDaemonEvent / onOwnedDevices /
    // onDaemonDown). The GUI's daemon subscription pushes updates immediately.
    if (window._connHeartbeat) return;
    window._connHeartbeat = true;  // sentinel so this is idempotent
};
