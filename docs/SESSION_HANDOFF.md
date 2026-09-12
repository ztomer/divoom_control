# Session Handoff — read this first

**Consolidated roadmap**: `docs/ROADMAP.md` — shipped rounds, open workstreams.
This file tracks the per-round current state and open threads.

This is the **cross-agent session state**. opencode and Claude Code keep their
own conversation stores. THIS FILE + git history + CHANGELOG + ROADMAP are the
shared memory. Read this on entry and **update it at the end of every round**
(see the core rule in `AGENTS.md`).

## How to resume

- **opencode**: `opencode -s ses_184471307ffeCUHgzv9w51O0oA` (or `opencode export <id>`).
- **Claude Code**: reads `CLAUDE.md` → `AGENTS.md` → this file, plus `git log`.
- Both: `git log --oneline`, `CHANGELOG.md`, `docs/ROADMAP.md`.
- This file is the CURRENT state, not an archive. Once a round ships and its
  CHANGELOG stanza is written, its entry here is pruned to git history (house
  rule: one forward-looking doc). To recover older context:
  `git log -p -- docs/SESSION_HANDOFF.md` for past entries,
  `git log --diff-filter=D -- 'docs/**/PLANNING_*'` for round plans.

## Current state — _update this section each round_

- **2026-09-12 — test rearrangement Phase 2 SHIPPED (uncommitted): `tests/` squatters cleared.**
  - Deleted trio + 2 superseded runners (self-referential only, verified by re-grep); `perf_*` → `scripts/` (11 perf tests pass explicitly, were never suite-collected).
  - Verification: collection 3182 before/after (delta 0), full suite 2946/236 identical to Phase 1, placement/scripts/file-size gates green.
  - Procedural note: `git stash` + `pop` around staged renames split the index (repaired with `git add -A`, re-verified) — recorded in the plan file.
  - Next up: Phase 3 (obsolete-Python retirement: `examples/` × 7, old-path scripts, `divoom_lib/cli.py` audit, `scratch/` rm).

- **2026-09-12 — test rearrangement Phase 1 SHIPPED (uncommitted): plan `docs/PLANNING_TEST_REORG.md`, roadmap item updated.**
  - 4 strays moved into `tests/` (all hardware-gated): `test_show_image_hw.py`, `test_smoke_display_aliases_hw.py` (bonus find), `test_watchface_roundtrip.py` (move-not-port: mock test pins the facade seam; importer updated, 15/15 pass). `hw_test_modes.py` → `hw_walk_modes.py`.
  - 4 ungated `pub mod *_tests` in `divoomd/src/lib.rs` gated with `#[cfg(test)]`; `mock_transport` kept `pub` (runtime). All 21 `mock_*` tests pass.
  - New gate `tools/check_test_placement.py` (step 5/26, mirrored in CI, calibrated both directions, probe removed).
  - Verification: pytest 2946 passed / 236 skipped, cargo both matrices green, clippy both cfgs + fmt clean, `ci_local.sh --fast` 26/26.
  - Next up: Phase 2 (`tests/` squatters) and Phase 3 (obsolete-Python retirement) from the plan file. Six user-reported defects + connection-state flow still open in the roadmap.

- **2026-09-12 — v0.35.4 RELEASED & INSTALLED LOCALLY: Virtual Wall Simplification, Spatial Bench Alignment & Channel Persistence.**
  - **Release & Local Verification**: GitHub Actions CI all green (5/5 jobs in 6m3s), release `v0.35.4` published with DMG and Homebrew cask updated; installed to `/Applications/Divoom.app` via `scripts/install_local.sh`, verified running daemon inode (`540421883`, PID 76699). Development BLE-free debug binary restored.
  - **Virtual Wall Tab Simplification & Arranger Canvas Elimination (`index.html`, `app_globals.js`, `app_init.js`, `spatial_stage.js`, `presets_manager.py`)**:
    - Completely removed redundant `.arranger-card` (`#arranger-canvas`, `#add-arranger-screen-btn`, `#clear-arranger-btn`, `#preset-name-input`, `#save-preset-btn`, `#presets-select`) from Tab 2.
    - Virtual Wall Tab is now a clean "Split & Sync Wall Art" controller powered directly by the physical Spatial Stage Bench (`SpatialRooms.getWallSlots()`), respecting physical screen dimensions, 2D coordinates, and room assignments.
    - Pruned redundant arranger blitting and DOM listeners from `app_globals.js`, `app_init.js`, and `spatial_stage.js`.
    - Deleted dead methods `save_preset`, `load_preset_names`, and `load_preset_by_name` from `PresetsManagerMixin`. Verified by `tools/check_gui_api_reachable.py` (114 reachable, 0 allowlisted, 0 unreached).
  - **Per-Device Active Channel Persistence & Preview Rehydration (`app_globals.js`, `channels_core.js`, `channel_preview.js`, `preview_controller.js`, `spatial_stage.js`, `gui_main.py`, `connection_events.js`)**:
    - Added `saveDeviceChannel` and `getDeviceChannel` in `app_globals.js`, storing active channels and options per-MAC in `localStorage['divoom_device_channels']` with case-insensitive MAC lookup.
    - Rehydrates active channel on device selection and bench refresh (`refreshBenchNodes`), updating `DisplayPreviewRegistry`, active tab buttons, and channel panels.
    - Whitelisted `"activity"` event in `gui_main.py:_start_shutdown_follower`, delivering daemon channel switch broadcasts to `connection_events.js:window.Divoom.onActivity` for instant cross-surface synchronization.
    - Added automated test suite `tests/test_channel_persistence.py` (3 passed).
  - **Separation of Concerns Formalization**:
    - Audited architectural boundaries across Daemon (`divoomd`), Native Menubar (`divoom-menubar`), and Web GUI (`divoom_gui`).
    - Formally established Daemon as sole device transport authority & event broadcaster; Native Menubar as lightweight system-wide monitor & action trigger; and Web GUI as rich multi-screen spatial staging & content authoring environment.
  - **Automated Verification**:
    - Full local CI (`./scripts/ci_local.sh --fast`): all 25 steps passed.
    - Full Python suite: 2946 passed, 234 skipped.
    - Playwright browser suite: `tests/test_channel_persistence.py`, `tests/test_virtual_wall_preview_sync.py`, `tests/test_gui_wall_canvas_drag.py` (11 passed).
    - House gates clean: 389/389 files <= 500 LOC (`check_file_size.py`), 744 files clean in emoji gate (`house_emoji_gate.sh`).
    - Real application test: `scripts/gui_pov.py` completed with 0 errors.

- **2026-09-12 — v0.35.3 RELEASED & INSTALLED LOCALLY: Architectural Remediation, Multi-Surface State Coordination & Virtual Wall Spatial Synchronization.**
  - **Release & Local Verification**: GitHub Actions CI all green (5/5 jobs), release `v0.35.3` published with DMG and Homebrew cask updated; installed to `/Applications/Divoom.app` via `scripts/install_local.sh`, verified running daemon inode (`540204817`, PID 36828). Development BLE-free debug binary restored.
  - **Defects Remediated**: Addressed 5 core architectural defects discovered during the full system audit (`architectural_audit_report.md`).
  - **Serialized Device Dispatch via QueuePermit (`divoomd/src/command_queue.rs`, `divoomd/src/daemon.rs`)**:
    - Added RAII `QueuePermit` backed by a oneshot release channel to `CommandQueue`.
    - Added `pub async fn acquire(&self, token: Option<String>) -> Result<QueuePermit, AcquireError>` to `CommandQueue`.
    - In `cmd_device_call`: acquired `_permit = q.acquire(token).await` before resolving `dev` and calling `handle_device_call`.
    - Enforces strict FIFO ordering and mutual exclusion between RPC callers, live streamers (`run_sysmon`, `run_stocks`, etc.), and multi-packet firmware transfers (`art_hot.rs`), eliminating mid-frame packet collisions and stolen upload ACKs.
    - Exposed `resolve_target_device` as `pub(crate)`.
  - **Ghost Live Streamer Cleanup & Multi-Device Disconnect (`divoomd/src/daemon_connect.rs`)**:
    - In `cmd_disconnect`: halts all active background streamers via `daemon.live_jobs.stop_all(daemon).await`, preventing zombie streaming tasks from running in infinite loops and state-hijacking upon device reconnect.
    - Drained `daemon.devices` and invoked `disconnect().await` on all active BLE/SPP transports, eliminating orphaned Bluetooth connections.
  - **Virtual Wall Coordinate-Task Invariance (`divoomd/src/wall.rs`)**:
    - Refactored `DivoomWall::connect` so spawned connection tasks directly yield `(WallConfig, Result<Arc<DeviceTransport>, String>)`.
    - Eliminated positional indexing (`configs[idx]`), guaranteeing zero spatial coordinate displacement across the wall even if individual panel connections fail or panic.
  - **Transport Pool Unification & Fleet Preservation (`divoomd/src/wall/cmds.rs`, `divoomd/src/wall.rs`)**:
    - In `cmd_wall_configure`: unified `daemon.devices` and `daemon.device` into `existing_by_mac`, preventing redundant BLE connections to already-connected displays and enabling `MockTransport` support for virtual walls.
    - In `DivoomWall::disconnect`: added `preserved_macs: &[String]`, ensuring active fleet connections in `daemon.devices` are preserved when walls are reconfigured or torn down.
    - Factored out `teardown_wall` and `parse_wall_configs` to keep `cmd_wall_configure` under Clippy's 100-line ceiling.
  - **Custom Art Multi-Device MAC Targeting (`divoomd/src/art.rs`)**:
    - Updated `cmd_custom_art_push` and `cmd_custom_art_query_page` to accept `mac` / `target_mac` and resolve devices via `daemon.resolve_target_device(mac).await`.
  - **Automated Verification**:
    - Integration tests in `divoomd/tests/multi_device_routing.rs`: `test_disconnect_stops_live_jobs_and_drains_devices` and `test_wall_configure_reuses_daemon_transports_and_binds_coordinates` (7/7 passed in 1.51s).
    - Full local CI (`./scripts/ci_local.sh --fast`): all 25 steps passed.
    - House gates clean: 389/389 files <= 500 LOC, 744 files clean in emoji gate.
    - BLE-free debug binary restored (`cargo build -p divoomd --no-default-features`).

- **2026-09-12 — Multi-Surface State Coordination Fix: `system.set_screen_on` Implementation, Standby Job Preemption & Menubar Activity Event Streaming.**
  - **Defect Class Solved**: Uncoordinated Background Streamers & Split-Brain State Mutations across Multi-Surface Clients (Daemon, Menubar, GUI).
  - **Unified Screen Power RPC (`divoomd/src/device_call`)**:
    - Implemented `system.set_screen_on` and its aliases (`device.set_screen_on`, `set_screen_on`, `display.set_screen_on`) in `basic.rs` and `routing.rs`. Fixes broken `divoom-menubar` power toggles ("Turn Off Screen" / "Turn On Screen") that previously failed with unported method error.
    - Added direct support for LAN devices in `device_call/mod.rs` (`Channel/OnOffScreen` and `Channel/SetBrightness`), allowing both Bluetooth and Wi-Fi displays to be controlled identically from all surfaces.
    - Factored `decode_blob_map`, `report_no_lan`, and `handle_lan_fallback` to ensure all dispatch functions strictly honor Clippy's 100-line cap.
  - **Standby & Zero-Brightness Preemption (`divoomd/src/daemon.rs`)**:
    - In `preempt_conflicting_live_jobs`, added preemption on `set_screen_on` with `on: false` and `set_brightness` with `0`. Stops all active background live streaming jobs immediately so sleeping devices are not woken up 5s later.
  - **Broadcast Stream Event Ingestion (`divoomd/src/daemon/dispatch.rs`, `divoom-menubar/src/daemon.rs`)**:
    - In `dispatch.rs:set_device_activity`: broadcasts `{"type": "activity", "mac": mac, "kind": kind, "name": name, "preview": preview}` over `daemon.tx` to all subscribers.
    - In `daemon.rs:cmd_device_call`: broadcasts `"activity"` event when `switch_channel` completes.
    - In `divoom-menubar/src/daemon.rs`: updated `update_snapshot_from_event` so existing device names are never clobbered by empty/default names upon receiving activity events.
  - **Automated Verification**:
    - Integration tests in `divoomd/tests/multi_device_routing.rs`: `test_device_call_set_screen_on_and_standby_preemption` and `test_set_device_activity_broadcasts_event` (5/5 passed in 1.51s).
    - Menubar tests in `divoom-menubar/src/daemon/tests.rs`: `snapshot_updates_from_stream_events` (19/19 passed in 0.41s).
    - Local CI (`./scripts/ci_local.sh --fast`): all 25 steps passed.
    - House gates clean: 389/389 files <= 500 LOC, 744 files clean in emoji gate.
    - Development BLE-free binary restored (`cargo build -p divoomd --no-default-features`).

- **2026-09-12 — State Management Fix: Background Live Job Preemption on Channel Switch, Image Push & Gallery Art Selection.**
  - **Problem Solved**: When a user selected System Monitor (stats) and subsequently pushed a gallery artwork or changed channels, the device briefly switched and then reverted back to stats after 5 seconds due to competing background live streaming tasks (`run_sysmon`) continuing to push frames indefinitely.
  - **Rust Daemon Preemption (`divoomd/src/daemon.rs`, `divoomd/src/art.rs`)**:
    - Added `preempt_conflicting_live_jobs(&self, req: &Request, target_mac: Option<&str>)` in `Daemon::cmd_device_call`. Automatically halts all active streaming tasks (`self.live_jobs.stop_all_for_device(self, &m).await`, or `stop_all` if `target: "wall"`) upon receiving any display-disruptive command (`show_image`, `display_image`, `show_clock`, `set_clock`, `set_clock_rich`, `show_light`, `set_light`, `switch_channel`, `show_text`, `set_design`, `show_design`, `send_image`, `push_animation`, `stream_animation_8b`, `show_effects`, `show_visualization`, `show_scoreboard`, `show_hot_channel`).
    - Added preemption in `art.rs:cmd_custom_art_push` to stop active jobs on the target MAC when pushing custom art slots.
  - **Python API & Client Preemption (`divoom_gui/api/lighting.py`, `divoom_gui/gallery_sync.py`)**:
    - Fixed `_stop_live_widgets(self, mac: str | None = None)` in `LightingApi`: properly accesses `self._client`, resolves target MAC from current device, and calls `client.live_jobs_stop_for(target_mac)`.
    - Wired `self._stop_live_widgets()` into `display_wall_image`, `push_text`, and `set_clock_rich`.
    - Fixed client method lookup in `gallery_sync.py:play_gallery_art`, calling `client.live_jobs_stop_for(mac)` before pushing artwork and safely reusing `client` for downloading uncached previews.
  - **Frontend DisplayPreview Job Unbinding & Poller Containment (`preview_controller.js`, `app_globals.js`, `gallery.js`, `widgets.js`, `custom_art.js`)**:
    - In `preview_controller.js`: updated `DisplayPreview.prototype.setActivity` so that switching away from a streaming widget channel or setting artwork (`opts.fileId`) automatically unbinds the active streaming job (`this.unbindJob()`), while preserving the binding during normal widget streaming ticks (`{ src: src }`).
    - In `app_globals.js`: updated `markActiveDeviceFrame(src, specificMac, kind)` so that when `kind` is provided and no displays are bound to that widget, it returns early and never clobbers the active display with stale frames.
    - In `gallery.js` and `custom_art.js`: explicitly unbinds the target display's active job upon artwork tile selection.
    - In `widgets.js`: added `divoom:activity-updated` listener that clears local timers (`sysmonTimer`, `stockTimer`, weather polling) and unmarks active widget cards whenever a non-widget activity is displayed.
  - **Automated Verification**:
    - Rust integration test `divoomd/tests/multi_device_routing.rs:test_device_call_preempts_conflicting_live_jobs` (passed).
    - Python unit tests in `tests/test_gui_api_lighting.py` (27 passed).
    - Playwright browser test in `tests/test_browser_preview_registry.py:test_browser_stats_gallery_job_preemption` (4 passed in 12.45s).
    - Full Python pytest suite: 2956 passed, 232 skipped.
    - Full local CI (`./scripts/ci_local.sh --fast`): all 25 steps passed.
    - House gates clean: 389/389 files <= 500 LOC, 744 files clean in emoji gate.

- **2026-09-12 — Virtual Wall & Main Bench Preview Unification + Two-Way Spatial Preset Synchronization.**
  - **Virtual Wall Preview Unification (`preview_controller.js`, `wall.css`, `app_globals.js`, `spatial_stage.js`, `settings_hardware.js`)**:
    - Banished divergent preview rendering between the Virtual Wall arranger (`#arranger-canvas`) and Main Bench (`#spatial-bench`).
    - Fixed `preview_controller.js`: previously `if (this.wallSlot)` unconditionally rendered an orange dashed "W" glyph on the Main Bench whenever a device had an assigned wall slot, suppressing live procedural channels (Clock, EQ visualizer, Ambient). Changed condition to `if (this.channel === "wall")`, ensuring procedural channels display their authentic pixel art on the Main Bench.
    - Replaced static `<img>` tags in `.arranger-node-screen` (`app_globals.js:renderArrangerCanvas`) with dynamic `<canvas class="arranger-node-canvas arranger-node-preview">` elements backed directly by `DisplayPreviewRegistry.get(mac).renderTo(cvs, 0)`.
    - Concurrently ticked and blitted active frames to both `#stage-canvas-${mac}` and `#arranger-canvas-${mac}` in `spatial_stage.js:startAnimationLoop`, ensuring real-time multi-canvas synchronization for clocks, EQ spectrums, ambient modes, and art slices with identical pixel fidelity.
  - **Two-Way Spatial Preset Synchronization (`app_init.js`, `app_globals.js`, `spatial_rooms.js`, `spatial_stage.js`)**:
    - Synchronized Virtual Wall presets (`#presets-select`) with the `SpatialRooms` engine.
    - Loading a layout preset or dragging nodes in the Virtual Wall Arranger now updates `SpatialRooms` room assignment (`devRooms[mac] = 'Wall'`), updates spatial coordinates (`pos[mac] = { x, y }`), saves via `SpatialRooms.savePositions()`, and re-renders the Spatial Stage.
    - Dragging nodes on the Spatial Stage updates assigned wall slot coordinates and refreshes the Arranger canvas via `syncArrangerToPython()`.
  - **Automated Verification**:
    - Dynamic browser test suite `tests/test_virtual_wall_preview_sync.py` (3 passed): Clock preview sync on both canvases with 0 orange glyph pixels, Frame and EQ spectrum sync on both canvases, and preset load synchronization with `SpatialRooms`.
    - Full browser suite: 13 passed in 35.11s.
    - Full Python suite: 2953 passed, 231 skipped.
    - Rust suite: 205 unit tests, 51 integration tests passed.
    - Local CI (`./scripts/ci_local.sh --fast`): all 25 steps passed.
    - House gates clean: 389/389 source files <= 500 LOC, 743 files clean in emoji gate.

- **2026-09-11 — v0.35.2 RELEASED & INSTALLED LOCALLY: Unified Multi-Device Architecture, Per-Device Command Queues, Streamer Job Isolation & Native Menubar Event-Driven Streaming.**
  - **Release & Local Verification**: GitHub CI all green (5/5 jobs), release `v0.35.2` published with DMG and Homebrew cask updated; installed to `/Applications/Divoom.app` via `scripts/install_local.sh`, verified running daemon inode (`539489682`, PID 8041). Development BLE-free debug binary restored.
  - **Unified DisplayPreview Class & Registry (`preview_controller.js`, `index.html`)**:
    - Replaced fragmented ad-hoc preview dictionaries across 8+ frontend modules with an object-oriented architecture (`DisplayPreview` + `DisplayPreviewRegistry`).
    - Encapsulates per-display screen specs (`16x16`, `32x32`, `64x64`), active channel, image/SVG caching, authentic 1-bit bitmap digit rendering, and direct-to-canvas blitting.
    - Multi-display isolation: updates to screen A never mutate or contaminate screen B.
  - **Phase 1: Two-Way Inspector Binding & Spatial Consolidation (`channel_preview.js`, `channels_grids.js`, `spatial_stage.js`, `spatial_rooms.js`)**:
    - Added `window.syncChannelControlsToDisplay(mac)`: switching screens on the Spatial Stage or Hardware Deck syncs inspector channel controls (clock style, color, ambient mode, EQ style) to the target display's current options.
    - Unified spatial room layout calculations into `SpatialRooms.getWallSlots(devices)` as the single source of truth across all views.
  - **Phase 2: Per-Device Streamer Job Binding & Fleet State (`preview_controller.js`, `app_globals.js`, `widgets_sysmon.js`, `widgets_music.js`, `widgets.js`)**:
    - Added `bindJob(kind, params)`, `unbindJob()`, and `isBoundTo(kind)` to `DisplayPreview`.
    - Live background widget streamers (Sysmon, Music, Stocks) dispatch frames strictly to displays bound to their kind via `window.markActiveDeviceFrame(src, specificMac, kind)`, eliminating cross-display frame leaks.
    - Implemented `window.getFleetStatus()` for comprehensive fleet-wide telemetry.
  - **Phase 3: Rust Daemon Multi-Device Transport Pool & Live Job Decoupling (`divoomd`)**:
    - Replaced single-device assumption with concurrent multi-device transport pool `daemon.devices: Mutex<HashMap<String, Arc<DeviceTransport>>>` and per-device command queues `get_device_queue(mac)`.
    - Decoupled `live_jobs/mod.rs` so active background streamers do not stall when the user switches active screens in the GUI.
    - Decoupled SPP connection handling from `#[cfg(feature = "ble")]`, allowing RFCOMM Bluetooth Classic connections to operate cleanly in BLE-free builds.
    - Added integration tests in `divoomd/tests/multi_device_routing.rs`.
  - **Phase 4: Native Menubar Event-Driven Snapshot Ingestion & Visual Device Controls (`divoom-menubar`)**:
    - Subscribed `divoom-menubar` to daemon broadcast stream via `subscribe`, maintaining cached `DaemonSnapshot` and eliminating polling socket churn (from 120 conn/min to 0 in steady state).
    - Built interactive per-device submenus in the macOS status menu with quick channel switcher (Clock, Visualizer, Ambient) and screen power standby toggle.
  - **Multi-Device MCP Tool Targeting (`divoomd/src/mcp_tools.rs`)**:
    - Injected optional `mac` parameter into all device tool schemas and forwarded `mac` in `dc`, `dc_kw`, `dc_result`, and `push_image_bytes`.
    - Enables AI agents to target individual displays directly in a multi-screen fleet (e.g. `set_brightness(level=30, mac=...)`) with automatic active display fallback.
  - **Hardware-Faithful Bitmap Pixel Art Clocks (`preview_controller.js`, `channel_preview.js`)**:
    - Banished blurry vector SVG `<text>` fonts. Integrated 1-bit integer LED bitmap digit tables (3x5 matrices) rendered via discrete pixel `<rect>` blocks.
    - All 6 clock styles render 100% sharp pixel art on integer coordinates.
  - **Automated Verification**:
    - `tests/test_display_preview_registry.py` (6/6 passed): unit checks on `DisplayPreview` and `play_gallery_art`.
    - `tests/test_browser_preview_registry.py` (3/3 passed): real-browser validation of multi-display isolation, two-way sync, and non-black canvas pixels.
    - `divoomd/tests/multi_device_routing.rs` (2/2 passed): concurrent multi-device command routing and live streamer job persistence across device switching.
    - `divoom-menubar` tests (19/19 passed): snapshot updates from broadcast stream and menu state resolution.
    - `divoomd` unit + integration tests (204 passed, 51 passed).
    - Full Python suite: 2953 passed, 228 skipped.
    - All house gates clean: 388/388 files <= 500 LOC, 117/117 API methods reachable, 741 files clean in emoji gate.

- **2026-09-11 — v0.35.1: Gallery Crispness, Offline Custom Art Cache & Isolated Per-Device Previews.**
  - **Gallery Crispness (`gallery.css`)**: Added `image-rendering: pixelated; crisp-edges;` to `.gallery-item-preview` ensuring thumbnail canvases render sharp pixels instead of blurred bicubic interpolation.
  - **Offline Custom Art Cache (`channels_grids.js`, `custom_art.js`, `gallery_sync.py`)**: Guaranteed offline cache loads all 142 items on launch even before `pywebviewready`, handles errors cleanly, and persists 3 pages x 12 slots to `localStorage['divoom_custom_art_slots']`.
  - **Per-Device Preview Decoupling & Virtual Wall Slicing (`channel_preview.js`, `channels_core.js`, `app_init.js`, `spatial_stage.js`)**: Decoupled `_channelPreviewSVG` from global fallbacks, added `_renderWallSlotSVG` for spatial canvas bounding boxes, isolated per-device activity parameters, and synchronized stage selection with active Control Center channel tabs.
  - **Universal Channel Switching & Hot Channel Update Verification**:
    - Restored `showChannelPanel(ch)` call and exposed `window.showChannelPanel` in `channels_core.js`, ensuring clicking channel tab buttons immediately activates that channel's configuration panel in the Control Center.
    - Synchronized `spatial_stage.js` device selection with `window.showChannelPanel`, matching the Control Center controls to the active device's channel.
    - Added support for `hot` / `cloud`, `ambient` / `lighting`, `eq`, and `custom` to `switch_channel` in both Python (`divoom_lib/display/__init__.py`) and Rust (`divoomd/src/device_call/basic/display.rs`).
    - Added automated wire frame verification suite (`tests/test_verify_all_channels_and_hot.py`, 13 passing tests) confirming all 7 channels emit valid 10-byte padded 0x45 frames with exact channel mode bytes, and text pushes 0x8B frames.
    - Verified Hot Channel full update workflow dynamically: manifest load, background update trigger, phase progression, completion toast, and last-checked timestamp persistence.
  - **Hot Channel Preview Grid & Device Preview Integration (`channel_preview.js`, `app_globals.js`, `gallery_hot.js`, `tests/test_hot_channel_device_preview.py`)**:
    - Added dedicated `cloud` / `hot` SVG preview renderer to `window._channelPreviewSVG` in `channel_preview.js` featuring a distinctive Divoom Cloud icon with glowing bolt.
    - Allowed `opts.src` in `window.setDeviceActivity` (`app_globals.js`) to provide real preview frames for any activity kind, enabling channels like `cloud` and `custom` to use real animated GIF thumbnails while preserving their semantic kind for menubar/tooltips.
    - Wired `renderHotPreview` in `gallery_hot.js` to automatically set the active device preview to the top animated GIF when viewing the Cloud/Hot channel.
    - Wired `finishProgress` in `gallery_hot.js` to immediately update the active device activity to `cloud` with the top hot thumbnail when an update completes (`phase === "done"`).
    - Added browser-driven test suite `tests/test_hot_channel_device_preview.py` covering hot grid GIF loading, hot update completion propagation to device previews, and per-device preview independence.
  - **Gate & Suite Status**: 23/23 tests passed in channel & hot preview suites (including real-browser Playwright test); file size (387 files <= 500 LOC), api reachability (116/116), and emoji gates clean.

- **2026-09-11 — v0.35.0 RELEASED & INSTALLED LOCALLY: Unified Spatial Stage, Appbar Stage Integration, Stage Center Alignment & Live Per-Device Previews.**
  - **Stage Center Alignment (`#stage-center-btn`)**:
    - Placed `#stage-center-btn` immediately to the left of `#stage-snap-btn` [Align] in `#appbar-stage-actions`, with a Susan Kare SVG icon.
    - Dynamically toggles with the stage state: visible (`inline-flex`) in expanded Bench mode, hidden (`display: none`) in compact Ribbon mode.
    - Centering algorithm: calculates collective horizontal bounding box `(maxX - minX)` across all displays on the bench, determines the offset to center within `#spatial-bench.clientWidth`, and shifts every device by uniform `deltaX`.
    - Strictly preserves Y baseline/top coordinates, relative inter-device spacing, DOM order, and stacking order. Persists coordinates to `localStorage` and `topology.json`.
  - **Live Per-Device Previews & Elimination of Orange Square Fallback (`spatial_stage.js`, `app_globals.js`, `channels_grids.js`)**:
    - Completely banished the hardcoded 6x6 orange rectangle (`#ff5a1f`) that previously rendered whenever a channel other than basic sysmon or visualizer was active.
    - Added an `HTMLImageElement` SVG/raster cache (`previewImgCache`) in `startAnimationLoop`: renders exact clock faces (Full Screen digital, Rainbow tspans, With Box borders, Analog Square with clock hands, Full Screen Neg, Analog Round), EQ visualizers, VJ stars, scoreboards, and ambient modes directly onto `stage-canvas-${addr}` from `window.DivoomState.devicePreviews` and `_channelPreviewSVG`.
    - Real-time reactivity: selecting a clock face or color in `channels_grids.js` immediately updates `window.setDeviceActivity` and `devicePreviews` for the active display without network latency.
    - Synchronized selection: clicking any device node on the stage (`highlightNode`) updates active device MAC and banner title, and calls `window.restoreDevicePreview(addr)` so the main screen overlay always mirrors the selected device.
  - **Appbar Stage Integration (`index.html`, `appbar.css`, `spatial_stage.js`, `spatial_stage.css`)**:
    - **Zero-Height Stage in Ribbon Mode**: When in compact Ribbon mode, `#spatial-stage-mount` is completely hidden (`display: none;`, 0px height), recovering 32px of vertical height across the whole application. Fleet chips (`#appbar-ribbon-view`) sit directly in the native appbar next to the window traffic lights.
    - **Headerless Canvas in Bench Mode**: When expanded to Bench mode via `#stage-toggle-btn`, only the 180px freeform 2D canvas (`#spatial-bench`) drops down beneath the appbar. The title `BENCH` and room filter pills (`#stage-room-filters`) render directly inside `#appbar-bench-view` in the appbar. Redundant nested header bars are completely eliminated.
    - **Appbar Stage Actions**: Center (`#stage-center-btn`), baseline alignment (`#stage-snap-btn`), and stage toggle (`#stage-toggle-btn`) reside in `#appbar-stage-actions` next to the settings gear.
    - **PyWebView Drag Exclusions**: Appbar stage controls and actions intercept `mousedown` event bubbling to prevent macOS window drag handlers from capturing button and chip clicks.
  - **Sidebar Bottom Clean-up & Deck Docking**:
    - Re-anchored the Active Display Hardware Deck (`#sidebar-device-deck`) to the very bottom of the sidebar (`margin-top: auto; margin-bottom: 2px;`), providing maximum breathing room for the dedicated device name row, contained room selector, and tactile sliders.
    - Retired redundant sidebar [Wall (4)] chip (`#wall-button`) to `display: none !important;` (since Virtual Wall is already a primary sidebar navigation tab), preserving DOM presence for test compatibility.
  - **Active Display Hardware Deck Refinements (`#sidebar-device-deck`)**:
    - **Dedicated Device Name Row**: Resolved text clipping (`Dito...`) by moving `#deck-device-name` to its own dedicated, unconstrained full-width row (`.deck-name-row`, `font-size: 12px; font-weight: 700; letter-spacing: -0.2px`).
    - **Meta Sub-Row**: Positioned online status diode jewel and model resolution badge (`.deck-meta-left`) opposite the tactile standby power button (`#deck-device-power`) on `.deck-meta-row`.
    - **Room Selector Containment**: Removed cramped "ROOM" text label prefix. Styled `.deck-select` to `width: 100%; box-sizing: border-box;` so it spans comfortably within the card's inner content boundaries without pushing or overflowing outside the pane.
  - **Room Device Add/Remove Management (`spatial_rooms.js`, `spatial_stage.js`)**:
    - **Device-Centric Unassignment**: `#deck-room-select` includes an `(Unassigned / No Room)` option at the top. Selecting it removes the device from its current room and deletes it from `deviceRooms`. Selecting any room assigns the device and persists immediately.
    - **Live Device Count Badges**: Room filter pills display dynamic device count badges: `All (4)`, `Desk (3)`, `Wall (1)`, `Shelf (0)`.
    - **Room-Centric Device Checklist Popover**: When a specific room is selected (e.g. `Wall`), a tactile `[Devices]` button appears. Clicking it opens a Dieter Rams / Susan Kare inspired popover (`.stage-room-devices-popover`) listing all detected displays with real-time checkboxes. Checking/unchecking instantly adds/removes devices to/from the room with live stage dimmed updates, pill count updates, and persistence across `localStorage` and `topology.json`.
  - **Gates & Verification**:
    - `cargo test -p divoomd --no-default-features` (204/204 passing).
    - `python3 -m pytest tests/test_gui_api_*.py tests/test_mcp_*.py tests/test_repo_gates.py tests/test_fonts.py tests/test_daemon_client_coverage.py` (314 passed, 2 skipped).
    - Dynamic Playwright/Camoufox verification (`verify_stage_center_and_previews.py`): verified Center button existence, placement to left of Align, Ribbon mode hidden, Bench mode inline-flex, centering cluster horizontally with 0px difference while preserving Y coordinates and relative spacing, initial canvas free of orange square, switching to Rainbow face (rendered tspans with pink/green hues, non-black pixels, 0 orange pixels), switching to Analog Square face (rendered bezel and clock hands), switching to EQ visualizer, and switching to Scoreboard. Screenshots: `gui_stage_centered.png`, `gui_clock_rainbow_preview.png`, `gui_analog_square_preview.png`.
    - File size gate: 387/387 source files <= 500 lines (`spatial_stage.js` at 484 lines, `spatial_stage.css` at 419 lines, `spatial_rooms.js` at 460 lines).
    - Emoji gate clean across 736 tracked files.
    - API reachability gate: 116/116 public API methods reachable from `web_ui/`.
    - Rebuilt release app and dmg (`dist/Divoom.app` and `dist/Divoom-v0.35.0.dmg`).
    - Installed locally to `/Applications/Divoom.app` via `scripts/install_local.sh`, verified running daemon inode (`538986299`, PID 53416).
    - Rebuilt BLE-free binary (`cargo build -p divoomd --no-default-features`) to protect against macOS TCC `SIGABRT`.

- **2026-09-07 (final session) — v0.34.0 CUT: the hardware round.** The **R12
  visual pass is CLOSED, 4/4 on real pixels** (`sysmon`, `album_art`,
  `custom_art`, `weather`), with `search_weather_city` recording XFAIL by
  design. It had been filed for rounds as "needs a device".

  **The defect it existed to find**: `run_weather` sent the 0x5F weather data
  and never selected the face that draws it, so after any job that took the
  Design channel it updated something invisible. The GUI's `toggle_weather_sync`
  had the identical gap. Fixed by sending a `ClockPacket` at job start and on
  re-acquisition, not on every refresh.

  **The bigger finding**: `hw_verify` had been UNRUNNABLE for rounds — it named
  `live_jobs.start`, `media.push_album_art` and `display.show_weather`, none of
  which the daemon has ever answered. The pass would have failed identically
  with no device attached. `--self-test` could not catch it, because proving a
  packet reports FAILURE for a bogus method says nothing about whether its own
  names exist. `tools/check_hw_verify_methods.py` now compares the packet to the
  daemon's match arms with no hardware.

  **Three of the round's defects were the reviewer's own**, all made while
  fixing the first two, and each got a structural fix rather than a patch:
  `channel_switch(Channel::Clock)` sent an inactive black clock (now
  uncompilable — `channel_switch` takes `BareChannel`); the regression test
  passed against ten zero bytes (now asserts active + panel + non-black); and
  the operator instruction named the wrong screen twice (hardware says
  `weather=1` drives a TEMPERATURE panel, `humidity` draws the icon face).

  **The `0x32` is gone on evidence.** A four-step probe with a control
  eliminated every variable except that send. It was a dead opcode on both sides
  of the port and its only effect was dropping brightness 80 -> 66 on every
  weather push. Pinned by a test.

  **`scripts/install_local.sh` is new and should be used for every hardware
  round.** Installing by hand failed silently twice today: the GUI respawns the
  daemon before the copy lands, and `open` on a running app only activates it. A
  measurement was taken against the previous build and recorded as a disproven
  hypothesis before the inode check caught it.

  **`/Applications/Divoom.app` carries divoomd 0.34.0**, installed and verified
  by that script (running-image inode matched the file it wrote), and the device
  confirmed the weather fix against it.

- **2026-09-07 (end of session) — v0.33.0 released and INSTALLED.** All six
  repos in the estate were released and installed locally: divoom-control
  v0.33.0, routines v0.41.0, monitor v0.47.0, ztools v2.3.0, app_updates
  v1.32.0 (its first tag ever), gates_of_heck v0.10.0.

  **The stale-daemon note below is now resolved**: `/Applications/Divoom.app`
  was brought up to date here, and to 0.34.0 later the same day via
  `scripts/install_local.sh`.

  **Open threads are unchanged:** D5 (connection census in `get_status`) and D6
  (client heartbeat + in-process self-watchdog).

- **2026-09-07 (later still) — Estate-wide gate work; three findings here.**
  The no-BLE build had never been linted (21 warnings, default build at zero) —
  clippy only reports on the cfg it compiled for. Fixed and wired into `.gatesrc`
  + CI, calibrated both directions. `cargo machete` added for unused
  dependencies (`md-5` recorded as a false positive: package `md-5`, lib `md5`).
  `GOH_LINE_UNBOUNDED` states why `docs/divoom_docs/` needs no ceiling.

  **Open threads unchanged:** D5 (connection census in `get_status`) and D6
  (heartbeat + self-watchdog). The running daemon is still installed v0.31.0.

- **2026-09-07 (later) — The write deadline covered 2 of 12 writes.** A post-fix
  audit of the daemon (D1-D6 in `docs/ROADMAP.md`) found D1-D3 already fixed in
  the tree and **D4 live**: `WRITE_TIMEOUT` had been applied by hand to the two
  `write_all` calls inside the subscriber `select!`, leaving the request/reply
  path and the eviction notice unbounded. A request client that pipelines and
  never reads pinned its connection permit forever — the deafness class again,
  one client at a time. Every write now goes through a `write_line` seam;
  `tools/check_bounded_writes.py` (in `.gatesrc` + CI) fails the build on any
  `write_all` beside it. Proven red both ways. Full `cargo test --locked` green.

  **Open threads:** D5 (connection census in `get_status`) and D6 (client
  heartbeat + in-process self-watchdog) are unstarted — see the "Daemon audit
  residuals" section in `docs/ROADMAP.md`. (The stale-installed-daemon warning
  that stood here is resolved: v0.33.0 is installed.)

- **2026-09-07 — The daemon could go completely deaf; fixed at the design level.**
  A divoomd ran five days holding 64 connections and answering nobody. Every
  attempt to start a replacement said `/tmp/divoom.sock is in use by another
  program`. There was no other program.

  Two independent defects, both design-level rather than local:

  1. **The connection cap and reachability were the same resource.** `serve()`
     waited for a semaphore permit around `accept()`, so a full cap stopped the
     accept loop and the daemon answered nothing at all — not even `get_status`.
     It now accepts unconditionally and refuses the overflow in one reply line
     (carrying `daemon_version`, so a busy daemon is still identifiable). A cap
     must bound WORK, never REACHABILITY.
  2. **The subscription TTL was reset by the daemon's own output.** The watchdog
     pushed its deadline out on every event DELIVERED, so it could only ever
     reap a subscriber on a silent channel. Subscriptions are the only
     connections that accumulate (request clients close immediately), so nothing
     bounded the one thing that grows. Subscriptions are now a bounded,
     self-cleaning LRU registry (`divoomd/src/subscriptions.rs`): nothing is
     disturbed until a slot is needed, then the least-recently-active one is
     reclaimed — and only if quiet for 10 minutes — with a
     `{"type":"resubscribe"}` notice. Activity means bytes FROM the client,
     because deliveries are a broadcast and separate nobody. Their budget is
     capped at half the connection budget so they can never starve requests.

  **The instrument that hid it for five days:** the back-pressure test asserted
  that an over-cap client gets NO REPLY within 300ms. That reading is identical
  for correct back-pressure and for a daemon that will never answer again, so
  the suite stayed green throughout. Its replacement asserts the opposite.
  The `ForeignListener` test had the same shape in its FIXTURE: it drove a
  silent listener and called it foreign, so silence was the only case ever
  exercised and it was labelled with the wrong remedy.

  **Live state:** the wedged pid was terminated and a fresh daemon answers in
  0ms with 3 fds instead of 66. (The "installed daemon is v0.31.0, reinstall to
  pick these up" note that stood here is long superseded — see Current state for
  what `/Applications` carries now.)

- **2026-09-07 — Crash fix: the GUI focused itself by LaunchServices app name.**
  A user crash report (`org.python.python` 3.9.10, `EXC_CRASH`/DYLD "Library not
  loaded: @rpath/Versions/3.9/Python") was OURS. `gui_main.main()`, on finding
  another Control Center already running, ran
  `osascript -e 'tell application "Python" to activate'`. That does not address
  our GUI — it asks LaunchServices to resolve the NAME "Python" and LAUNCH
  whatever answers. On this machine that is TeX Live Utility's embedded
  `Python.framework/.../Resources/Python.app` (UUID matched against the crash
  report). Gatekeeper app-translocates that nested bundle into `$TMPDIR`, which
  breaks its `@rpath`, so it SIGABRTs in dyld before `main`. Four crash reports
  on 2026-09-07 (01:05:11/19, 01:07:11/19 — a user clicking the menu bar's
  Launch Dashboard while an instance was up), and the window never came forward.

  Chased in the unified log, not guessed: `osascript` asks CSUI to launch, `lsd`
  translocates 96ms later, `launchd` reports `OS_REASON_DYLD`.

  Focus now goes through System Events addressed by `unix id` — it can only
  front an existing process and cannot launch anything. With no pid we do
  nothing; there is no safe name-based fallback. The pid comes from the
  single-instance lock, which had a second defect: opened `"w"`, it truncated
  BEFORE `flock` decided anything, so the losing contender erased the
  incumbent's pid. Fixing the focus alone would have produced a focus path that
  silently never focused. Both are in the new `divoom_gui/single_instance.py`
  (`gui_main.py` was exactly at the 500-line cap).

  **Class closed, not the instance:** `tools/check_applescript_launch.py` fails
  any tracked source addressing an app by name in AppleScript without an
  `is running` guard; System Events is the one allowed target. It is in
  `GOH_CI_STEPS`. Its limits are documented rather than papered over: per-file
  guard scope, and computed app names — a first cut there could not tell
  AppleScript from a log line (it tripped on the gate's own diagnostic, then
  passed again only because the help text contains the words it looks for), so
  that rule was removed instead of shipped.

- **2026-09-01 — v0.31.0 SHIPPED (R73).** Tag `1ebe3b9` on a green CI (all five
  jobs: test, rust-core, rust-ble, rust-ble-linux, no-emoji), GitHub release +
  `Divoom-v0.31.0.dmg`, cask bumped and verified by DOWNLOADING the published
  asset and re-hashing it (`493325c0...`), not by trusting the local file.

  Verified INSIDE the DMG rather than the source tree: both binaries report
  0.31.0, `CFBundleShortVersionString` is 0.31.0, zero APK/`references` leaks,
  no `bleak`, and `divoomd mcp` serves 13 tools.

  **The round in one line: three API methods that nothing had ever called were
  taken to real hardware, and two of them were broken.** The allowlist that
  excused them is now EMPTY — all 114 shipped API methods have a real caller.

  * `set_temperature_channel` DELETED. There is no temperature channel; `0x01`
    is Lighting, so `temp_type` was eaten as the red byte. White rendered cyan,
    red rendered bright green — both predicted from the layout before testing.
    `docs/CHANNEL_ARCHITECTURE.md` had recorded that exact cyan screen years
    earlier and explained it away as device state. It now carries the rule that
    cost: **a decode is confirmed by the panel, not by concordance between
    documents.**
  * `set_timeplan` DELETED (GUI only; the daemon's 0x56/0x57 are faithful
    ports). It fabricated an `index` the packet has no field for, put `channel`
    in the `mode` byte, and defaulted `week` to 0 = never.
  * `set_clock_rich` WORKS and is wired in. It CYCLES separate panels rather
    than drawing one combined face — `hw_verify.py` had been telling testers to
    look for the wrong thing.
  * `sync_time` confirmed: the clock moved 18:41 -> 21:42.

  **Two long-standing documents were wrong and are corrected.** The R12 audit
  said 0x35 had no APK entry; it is `SPP_SCROLL(53)`, and the audit file making
  the claim had been pruned to git history, so the code cited something nobody
  could open. And R32's "device-side text is impossible" was the wrong command,
  not a missing feature — scrolling text is now fully decoded and implemented
  (see below).

  **I corrupted `docs/ROADMAP.md` this round and committed it** (373 lines ->
  370,588). `s[s.index(A):s.index(B)]` with A after B yields `""`, and
  `str.replace("", new)` inserts between every character. Restored, and gated:
  `tests/test_no_runaway_file_growth.py` puts a 15,000-line ceiling on all
  tracked text, because the 500-line structural cap excludes `docs/`.

### Scrolling text — decoded, implemented, daemon-only

`text.show_scrolling_text` ports the APK's full marquee sequence: 0x6E start
(FIRST — the order is load-bearing), 0x7C glyph packets of 5 characters
(`[cp_lo, cp_hi, glyph[32]]`), 0x86 string, 0x86 rate. The glyphs come from the
`divoom_fond16_*` blob the daemon already embeds at 32 bytes each.

**The Tivoo-Max does not implement it.** Controlled A/B in one
`DIVOOMD_BLE_DEBUG` window: it acked `0x45` and returned nothing for
`0x6E`/`0x7C`/`0x86`, while the same trace confirmed our bytes were correct —
a firmware gap, not an encoding bug. No GUI surface, deliberately. The other
three devices are the same 16x16 class but untested; if one acks `0x7C`,
wiring a button is small work on top of what exists.

## Open threads / next up

### Architectural Unification Tracks (Next Up)

1. **Track 1: Virtual Wall Simplification & Spatial Stage Bench Consolidation (SHIPPED 2026-09-12)**:
   - Completely retired redundant 2D `.arranger-card` from Tab 2 in favor of the full-fidelity Spatial Stage Bench.
   - Virtual Wall Tab simplified to "Split & Sync Wall Art" querying `SpatialRooms.getWallSlots()` directly.
   - Pruned dead code from web UI and deleted obsolete API methods (`save_preset`, `load_preset_names`, `load_preset_by_name`).
   - Automated tests: `tests/test_virtual_wall_preview_sync.py` (3 passed).

2. **Track 2: Per-Device Live Widget & Background Streamer Binding (`DisplayJobBinding`)**:
   - Decouple background streamers (Sysmon, Music, Stocks/Crypto, Weather) from the global `selectedWidget` singleton and the active UI tab.
   - Bind streamers to explicit target display IDs (`displayA.bindJob("sysmon")`, `displayB.bindJob("stocks", "BTC")`), preventing frames from leaking to whatever screen is selected in the UI.
   - *Verification*: Verify running Sysmon on display A while switching GUI focus to display B leaves display A streaming sysmon and display B on its own channel.

3. **Track 3: Multi-Device Fleet State & Transport Lifecycle (`DeviceNode` Architecture)**:
   - Modernize `window.DivoomState.appConnected` (single boolean) and `#banner-device-mac` to a true multi-device registry mirroring `divoomd`'s topology.
   - Each physical screen independently manages its connection lifecycle (`connected`, `reconnecting`, `offline`), transport (`BLE`, `LAN`, `Mock`), battery, brightness, and volume.
   - *Verification*: Verify disconnecting screen 1 does not mark screen 2 offline or disable global controls.

4. **Track 4: Channel Configuration Two-Way Binding & Persistence (SHIPPED 2026-09-12)**:
   - Saved active channel choices and options per-MAC in `localStorage['divoom_device_channels']`.
   - Rehydrates active channel on device selection and bench refresh (`refreshBenchNodes`), updating `DisplayPreviewRegistry`, active tab buttons, and channel panels.
   - Connected daemon `"activity"` event broadcast to `gui_main.py` and `window.Divoom.onActivity` for instant cross-surface synchronization.
   - Automated tests: `tests/test_channel_persistence.py` (3 passed).

5. **Track 5: Rust Daemon Multi-Device Registry & Per-Device Queuing (`DeviceRegistry`) (SHIPPED 2026-09-12)**:
   - Serialized `cmd_device_call` device dispatch via RAII `QueuePermit` on `CommandQueue`, strictly serializing concurrent RPC callers against live streamers and firmware updates.
   - Fixed ghost live streamer leaks on disconnect: `cmd_disconnect` stops all live jobs and disconnects all transports in `daemon.devices`.
   - Virtual Wall coordinate-task invariance: `DivoomWall::connect` binds `WallConfig` directly to connection tasks, eliminating positional indexing shifts.
   - Unified Virtual Wall transport pool with `daemon.devices`, preventing duplicate BLE connections and preserving active fleet transports on wall teardown.
   - Enabled multi-device MAC targeting in `cmd_custom_art_push` and `cmd_custom_art_query_page`.
   - Verified via `divoomd/tests/multi_device_routing.rs` (7/7 passed in 1.51s).

6. **Track 6: Native Menubar Architecture Upgrades (`divoom-menubar`)**:
   - Event-driven snapshot ingestion via `subscribe` (shipped in v0.35.2).
   - Visual device tiles with graphical previews.
   - Actionable per-device controls.

7. **Track 7: Animated Image Previews (`DisplayPreview` GIF Playback)**:
   - Render animated GIF pixel art (from Community Gallery, Custom Art, Hot Channel, or uploads) animated in the preview nodes on the Spatial Stage Bench, Ribbon, and Virtual Wall.
   - WebKit canvas 2D `drawImage` from an in-memory `Image` freezes GIF playback at frame 0. Resolve via dual-mode DOM `<img>` overlay or lightweight client-side GIF frame demuxer advancing frames based on animation `tick` timestamps.

8. **Track 8: Prevent Out-of-Band Preview Mutations & Enforce Channel Reconciliation**:
   - Resolve bugs where a display's preview changes spontaneously without user intent or channel switch.
   - Remove unscoped `window._activeDeviceMac()` fallback in `markActiveDeviceFrame` so unbound widgets cannot overwrite active previews with `"image"`.
   - Stop static `_channelPreviewSVG` from setting `display.mode = "frame"`, keeping procedural channels strictly in `"glyph"` mode.
   - Reconcile `DisplayPreview` channel state with hardware daemon broadcast events.

9. **Track 9: Fix Gallery Artwork Double-Click Requirement**:
   - Fix bug where clicking an artwork tile in the Community Gallery (`#gallery-container`) often does nothing on the first click and requires a second press.
   - Root cause in `divoom_gui/gallery_sync.py:113`: `client = self._client` captured the method rather than invoking `self._client()`, causing uncached preview downloads to fail with `AttributeError` on click 1.
   - Provide immediate visual loading state (tactile press + spinner) and add regression tests.

**0. Two environment problems that cost this release ~an hour.** Neither is a
repo defect, but both will recur.

* **`sccache` wedges the build.** A `cargo build` sat for **51 minutes with
  0:00.00 CPU time** — `sccache --show-stats` showed 444 compile requests
  accepted, 40 executed, 0 hits and 0 misses. Its server was hung. The same
  build finished in **4 seconds** with `RUSTC_WRAPPER=""`. If a build appears
  to hang, check CPU time before assuming it is slow.
* **The shared `CARGO_TARGET_DIR` sits at the disk gate's ceiling.**
  `~/.cache/cargo-target` is ~45-50GB against a 50GB limit, so any substantial
  build pushes it over, and disk hygiene aborts `structural.sh` BEFORE layer 3
  — which fails `test_gate_full_reaches_layer_three` and blocks every push with
  a message about the gate rather than about disk. It blocked this release
  twice. `debug/build` is the bulk (~57GB measured, shared with other repos);
  `debug/incremental` and `llvm-cov-target` are the safe things to clear.


Three things, and only the FIRST needs you at a keyboard with a device — the other two are desk work.

**1. The hardware packet — five checks, one command** (R73 closed and removed
the `pic_scan` and `clock_rich` entries; 2026-09-07 rewrote the surviving five
against the daemon's real API — see below).

    python3 scripts/hw_verify.py --self-test        # calibrate FIRST
    python3 scripts/hw_verify.py --out report.json

Start the GUI first: it owns the Bluetooth TCC grant, and the packet REFUSES to
spawn its own daemon because a shell-launched one dies on its first scan with
SIGABRT and an empty stderr. `--self-test` exits **3 = PARTIAL** until a device
is connected, which is honest rather than broken: with nothing attached the
daemon refuses at the no-device precondition before it ever reads the method
name, so the invalid-method branch stays untested.

What the packet decides — **all five entries, as of 2026-09-07**:

* **R12 visual pass — DONE 2026-09-07, 4/4 on real pixels.** `sysmon`,
  `album_art`, `custom_art`, `weather`. Re-run it after any change to the live
  widgets; what is left of the original item is a light/dark-surroundings
  photograph, not a code change.
* **`search_weather_city`** — kept as a **canary**, not a test. R73 disproved
  its success path on the real account (`RC=1 Failed`), so it is EXPECTED to
  fail; a non-empty list would mean the server changed.

**Read this before running it: the packet was BROKEN until 2026-09-07 and the
breakage looked exactly like a hardware fault.** Run against a connected device
it failed 5/5, and three of those never reached the panel — it named
`live_jobs.start`, `media.push_album_art` and `display.show_weather`, none of
which the daemon has ever answered. They were pre-port Python spellings; the
widget jobs are the `live_job_start` socket command with kinds
`sysmon`/`stocks`/`weather`/`music` (`music` is album art). The R12 pass was
therefore never blocked on hardware — it would have failed identically with
nothing attached.

`--self-test` did not catch it and could not: it proves the packet reports
FAILURE for a bogus method, which is a claim about error handling, not about
whether the packet's own names exist. **`tools/check_hw_verify_methods.py`** is
now a gate (`GOH_CI_STEPS`) that compares the packet to the daemon's match arms
with no hardware, so this class fails a push instead of a device session.

**Play something before running `album_art`** — with no track the music job has
nothing to push, and a dark panel then means "nothing playing", not "broken".

**Rebuilding the daemon for a hardware run: QUIT THE GUI FIRST, then verify the
inode.** The GUI respawns the daemon the instant one shuts down, so the sequence
"shutdown daemon, copy binary, `open`" restarts it from the OLD binary before
the copy lands, and `open` on an already-running app only activates it. This
cost a wrong conclusion on 2026-09-07 ("removed the 0x32, brightness still
drops" -- it did not, that was the previous build). The check that catches it:

    osascript -e 'tell application id "com.divoom.control" to quit'
    pkill -f 'dist/Divoom.app'; sleep 2      # nothing left
    cp target/release/divoomd dist/Divoom.app/Contents/Frameworks/bin/divoomd
    codesign --force --deep --sign - dist/Divoom.app
    open dist/Divoom.app
    # then PROVE it is the one running:
    PID=$(pgrep -f 'dist/Divoom.app/.*divoomd' | head -1)
    lsof -p "$PID" | awk '$4=="txt" && $NF ~ /divoomd/ {print $(NF-1)}'
    stat -f '%i' dist/Divoom.app/Contents/Frameworks/bin/divoomd
    # the two inodes MUST match

The device also does not always come back on its own after a daemon restart:
`scan` times out, while `connect` with the saved identifier succeeds.

**2. The browser e2e suite fails randomly at NORMAL machine load.** Two full
runs on one commit failed different, non-overlapping sets of camoufox tests; all
pass in isolation. Since R71 P0 made `pre-push` run the whole CI, a randomly-red
gate teaches `--no-verify` — precisely what P0 existed to prevent. Detail in
`docs/ROADMAP.md` under the OPEN heading. **Do not "fix" it by raising a
timeout**: that threshold was chosen on an idle machine, and the fix is to
measure browser + daemon startup under controlled load.

**3. `config.ini` stores the Divoom account password in PLAINTEXT.** Out of
scope for R71/R72 and never in their ledgers, recorded here so it is not lost.
R72 moved credential writes to the daemon's `cloud_store`, which is now the one
place that would have to change.

### What is NOT open any more

R70's twelve findings, R71's twenty allowlist entries (bar the three above) and
R72's F1-F7 are all closed. Their durable output is
**`docs/CAPABILITY_MAP.md`** — 26 census rows, each with a verdict, plus the
F1-F7 closure table and the three blind spots the census cannot see. Read that
before re-auditing anything; two of R72's seven findings turned out to be
misdescribed by the audit that raised them, and the map records which and why.

## Earlier history

`CHANGELOG.md` is the durable record of what shipped, and `docs/ROADMAP.md` of
what is open. Round-by-round handoff prose is recoverable from
`git log -p -- docs/SESSION_HANDOFF.md` and, for R3–R64, from the archive file
deleted on 2026-08-30:
`git log --diff-filter=D -- 'docs/archive/*'`.

## Hardware note

macOS Bluetooth TCC is granted per RESPONSIBLE PROCESS. A daemon started from a
shell has no grant, so the first BLE scan kills it with **SIGABRT and an empty
stderr** — no panic, no message, nothing in the log. Confirmed 2026-08-30 by
differential: a BLE-linked build dies on the GUI's `scan_devices`, a
`--no-default-features` build drives the same flow cleanly. Users are unaffected
(the GUI launches the daemon and owns the grant); it only bites terminal work.

`scripts/gui_pov.py` warns when the binary it picked links CoreBluetooth, and
names TCC as the likely cause if the daemon aborts silently after a scan.

**To drive a LOCALLY BUILT daemon on hardware (verified R73):** the grant
follows the app bundle (`com.divoom.control`), not the binary, so install into
the bundle and let the app be the responsible process. Back up the original
binary first — adhoc signing is deterministic over content, so restoring the
exact bytes restores the old cdhash and its grant.

```bash
cargo build --manifest-path divoomd/Cargo.toml
cp target/debug/divoomd dist/Divoom.app/Contents/Resources/bin/divoomd
cp target/debug/divoomd dist/Divoom.app/Contents/Frameworks/bin/divoomd
codesign --force --deep --sign - dist/Divoom.app
pkill -f Divoom.app; rm -f /tmp/divoom.sock; open dist/Divoom.app
```

Then drive `/tmp/divoom.sock`. `connect_device(mac=...)` works directly; `scan`
often reports "already in progress" because the GUI is scanning. For a wire
trace, `launchctl setenv DIVOOMD_BLE_DEBUG 1` BEFORE `open` (the env has to
reach a GUI-launched app); the daemon logs to `/private/tmp/divoom_client.log`.

**Reading that trace:** a device ECHOES `basic frame cmd=0xNN` for opcodes its
firmware implements. A silence proves nothing on its own — an idle window looks
identical — so always send a known-good command (0x45) first in the SAME window
and compare.

Watch out: `cargo test` rebuilds `target/debug/divoomd` WITH default features,
so a BLE-free build does not stay BLE-free across a test run.
