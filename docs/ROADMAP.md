# Roadmap — divoom-control

Consolidated view of shipped rounds, current state, and future work.
Per-round plans are pruned to git history once shipped; this file is the
forward-looking one. Recover a round plan with
`git log --diff-filter=D -- 'docs/PLANNING_*'`.

---

## Shipped

- **v0.36.0 — One struct per panel, the six user-reported defects, prompt-free rebuilds (2026-09-12)**:
  - **Daemon per-device aggregate (`divoomd/src/device.rs`)**: `Device` (identity: one live job, activity) holds an `Option<Link>` (connection: transport + the ONE queue); `Fleet` is the single owner of which panels exist and which is current. Queued work is bound to its link and dropped if the link is retired; a job's `alive` flag is cleared before abort and checked at execution. Every pushed live frame is broadcast with its pixels. Replaces five mac-keyed maps that disagreed (ghost frame after stop, GUI calls on a different queue from live jobs, two widgets per screen, ghost frame on reconnect). Gate: `divoomd/tests/live_jobs_stress.rs` (10 scenarios, 4 red before).
  - **Six user-reported defects, all live-confirmed with the user at the keyboard**: cover art (original art, smooth; device frame, diodes), animated bench previews (`gif_frames.js` client-side decoder), channel switching (measured 0.04-0.12s; the flaky half was the connecting-state funnel), weather city, empty Clock/Custom Art panels (document-wide panel toggle), stuck "connecting".
  - **GUI fleet state**: the proxy names its panel on every call; bench selection is one funnel (`select_device`); status events are per-panel; bench/deck jewels are honest; `owned_devices` is fleet-wide and never carries a placeholder name; previews mirror the panel through the broadcast frames. Per-device `disconnect {mac}` / `device_status {mac}`.
  - **Menubar**: `DeviceView` per panel with link state; the tray word is derived.
  - **Signing**: self-signed local code-signing identity (`scripts/make_signing_identity.sh`, `scripts/codesign_identity.sh`); the Bluetooth grant survives rebuilds (proven: second different build, no prompt).
  - **Also**: tests rearranged into `tests/` with a placement gate; wall creates the BLE central lazily; BLE debug lines tagged with the peripheral id; now-playing treats an empty MediaRemote session as nothing playing.

- **v0.35.4 — Virtual Wall Simplification, Spatial Bench Alignment & Channel Persistence (2026-09-12)**:
  - **Virtual Wall Tab Simplification & Arranger Canvas Elimination**: Removed redundant `.arranger-card` (`#arranger-canvas`, preset management UI) from Tab 2; Virtual Wall now focuses on "Split & Sync Wall Art" directly using Spatial Stage Bench node positions (`SpatialRooms.getWallSlots()`); deleted dead preset methods on `DivoomGuiAPI` (`save_preset`, `load_preset_names`, `load_preset_by_name`).
  - **Per-Device Active Channel Persistence & Preview Rehydration**: Persisted active channel and options to `localStorage['divoom_device_channels']` with case-insensitive MAC resolution; on device selection and bench refresh, rehydrates `DisplayPreviewRegistry`, channel panel buttons, and inspector controls; whitelisted `"activity"` in `gui_main.py` to forward daemon channel change broadcasts to `window.Divoom.onActivity`.
  - **Separation of Concerns Formalization**: Documented architectural boundaries across Daemon (driver & hardware state authority), Native Menubar (lightweight menu & system status), and GUI (rich visual authoring & multi-screen canvas staging).
  - **Automated Verification**: Full local CI green (25/25 steps); Python test suite (2946 passed, 234 skipped); Playwright browser suite (11 passed across `test_channel_persistence.py`, `test_virtual_wall_preview_sync.py`, `test_gui_wall_canvas_drag.py`); real app verification via `scripts/gui_pov.py` passed with 0 errors.

- **v0.35.3 — Architectural Remediation, Multi-Surface State Coordination & Virtual Wall Spatial Synchronization (2026-09-12)**:
  - **Architectural Defects Remediation (`divoomd`)**: Serialized device dispatch in `cmd_device_call` using RAII `QueuePermit` on `CommandQueue`, strictly serializing concurrent RPC callers against live streamers and firmware updates; terminated zombie background streamers on disconnect via `daemon.live_jobs.stop_all(daemon).await` and drained `daemon.devices`; refactored `DivoomWall::connect` to bind `WallConfig` directly to tasks, ensuring complete coordinate invariance; unified virtual wall transport pool with `daemon.devices` and preserved active fleet connections on wall teardown; enabled multi-device MAC targeting in `cmd_custom_art_push` and `cmd_custom_art_query_page`.
  - **Multi-Surface State Coordination (`divoomd`, `divoom-menubar`)**: Unified `system.set_screen_on` across BLE and LAN; added standby and zero-brightness preemption to automatically halt active streamers; broadcasted event-driven `"activity"` updates over `daemon.tx` to menubar and subscribers; preserved device names on activity updates.
  - **Live Job Preemption & State Management Stabilization**: Preempted background streaming jobs across daemon, Python API, and frontend upon channel switch, image push, and gallery art selection; fixed gallery double-click bug.
  - **Virtual Wall & Main Bench Preview Unification + Two-Way Spatial Preset Synchronization**: Replaced static arranger images with dynamic `<canvas>` elements driven by `DisplayPreviewRegistry`; banished false-positive orange "W" glyph; two-way synchronized Virtual Wall layout presets and node dragging with the `SpatialRooms` engine.
  - **Automated Verification**: `divoomd/tests/multi_device_routing.rs` (7/7 passed), Python unit and browser tests (173 passed), local CI all 25 steps passed.

- **v0.35.2 — Unified Multi-Device Architecture, Per-Device Command Queues, Streamer Job Isolation & Native Menubar Event-Driven Streaming (2026-09-11)**:
  - **Unified DisplayPreview Object Model (`preview_controller.js`, `index.html`)**: Introduced `DisplayPreview` and `DisplayPreviewRegistry` classes encapsulating native resolution (`16x16`, `32x32`, `64x64`), active channel, image/SVG caching, authentic 1-bit bitmap digit rendering, and direct-to-canvas blitting with complete multi-display isolation.
  - **Hardware-Faithful Bitmap Pixel Art Clocks (`preview_controller.js`, `channel_preview.js`)**: Replaced blurry vector SVG fonts with authentic 1-bit integer bitmap LED matrices (3x5 and 5x7 digit tables) rendered directly via discrete pixel diodes.
  - **Two-Way Inspector Binding & Spatial Consolidation**: `window.syncChannelControlsToDisplay(mac)` synchronizes inspector controls with target display options on device switch; `SpatialRooms.getWallSlots(devices)` provides a single unified layout algorithm across all spatial views.
  - **Per-Device Streamer Job Binding & Fleet State**: Added `bindJob`/`unbindJob` to `DisplayPreview`, confining background widget frame dispatch (Sysmon, Music, Stocks) strictly to bound displays; added `window.getFleetStatus()`.
  - **Rust Daemon Multi-Device Transport Pool & Live Job Decoupling (`divoomd`)**: Replaced single-device assumption with concurrent multi-device pool `daemon.devices: Mutex<HashMap<String, Arc<DeviceTransport>>>` and per-device command queues `get_device_queue(mac)`; live background streamers continue pushing frames even when the user switches screens in the GUI; decoupled SPP from `#[cfg(feature = "ble")]` allowing RFCOMM classic Bluetooth in BLE-free builds; added integration tests in `multi_device_routing.rs`.
  - **Native Menubar Event-Driven Snapshot Ingestion (`divoom-menubar`)**: Connected `divoom-menubar` to daemon `subscribe` broadcast stream, caching `DaemonSnapshot` and eliminating polling socket churn (from 120 conn/min to 0 in steady state); built interactive per-device submenus with quick channel switcher (Clock, Visualizer, Ambient) and screen power standby toggle.
  - **Multi-Device MCP Tool Targeting (`divoomd/src/mcp_tools.rs`)**: Injected optional `mac` parameter into all device tool schemas and forwarded `mac` in `dc`, `dc_kw`, `dc_result`, and `push_image_bytes`, enabling AI agents to target individual displays directly in a multi-screen fleet with automatic active display fallback.
  - **Automated Verification**: 9/9 browser preview registry tests passed, 2/2 multi-device routing integration tests passed, 19/19 menubar tests passed, 204 unit tests passed, 2953 Python tests passed (228 skipped). All house gates clean.

- **v0.35.1 — Gallery Crispness, Offline Custom Art Cache & Isolated Per-Device Previews (2026-09-11)**:
  - **Gallery Crispness (`gallery.css`)**: Added `image-rendering: pixelated; crisp-edges;` to `.gallery-item-preview` eliminating bilinear interpolation blurriness on community pixel art thumbnails.
  - **Offline Custom Art Cache (`channels_grids.js`, `custom_art.js`, `gallery_sync.py`)**: Guaranteed offline cache loads all 142 items on launch even before `pywebviewready`, handles errors cleanly, and persists 3 pages x 12 slots to `localStorage['divoom_custom_art_slots']`.
  - **Per-Device Preview Decoupling & Virtual Wall Slicing (`channel_preview.js`, `channels_core.js`, `app_init.js`, `spatial_stage.js`)**: Decoupled `_channelPreviewSVG` from global fallbacks, added `_renderWallSlotSVG` for spatial canvas bounding boxes, isolated per-device activity parameters, and synchronized stage selection with active Control Center channel tabs.
  - **Universal Channel Switching & Hot Channel Update Verification**: Restored `showChannelPanel(ch)` call and exposed `window.showChannelPanel` in `channels_core.js`; added support for `hot` / `cloud`, `ambient` / `lighting`, `eq`, and `custom` to `switch_channel` in both Python and Rust; verified all 7 channels emit valid 10-byte padded 0x45 frames via `tests/test_verify_all_channels_and_hot.py` (13 tests passing).
  - **Hot Channel Preview Grid & Device Preview Integration**: Added dedicated `cloud` / `hot` SVG preview renderer to `window._channelPreviewSVG` (`channel_preview.js`); allowed `opts.src` for any activity kind in `window.setDeviceActivity` (`app_globals.js`); wired `renderHotPreview` and `finishProgress` in `gallery_hot.js` to propagate animated GIF previews to active device previews on the Spatial Stage and ribbon overlay; added automated browser test suite `tests/test_hot_channel_device_preview.py`.
  - **Suite**: 23/23 tests passed in channel & hot preview suites; 204 unit tests passed in cargo test; file size (387 files <= 500 LOC), api reachability (116/116), and emoji gates clean.

- **v0.35.0 — Unified Spatial Stage, Physical Scale Engine & Option 1 Layout (2026-09-11)**:
  - **Full-Width Spatial Preview Bench & Sidebar Hardware Deck (Option 1 Layout Re-architecture)**:
    - Promoted preview bench to full-width top deck spanning the window width (~1100px) above `.app-container`.
    - Decluttered bench canvas: removed nested double toolbars, keeping clean radial dot grid with header controls (`[All] [Desk] [Wall]` room filter pills, `Align` desk snapping, `Ribbon` toggle).
    - Appbar streamlined: removed duplicate brightness and volume sliders from the universal titlebar.
    - Active Display Hardware Deck (`#sidebar-device-deck`): pinned to bottom of sidebar with live identity (jewel, name, `16×16` / `64×64` tag), Kare SVG power standby toggle, room assignment, brightness slider, and contextual speaker volume slider.
    - Contextual volume control: speaker slider automatically reveals for audio displays (Ditoo, Timoo, Tivoo-Max) and hides for screen-only units (Pixoo-64, Pixoo-1).
  - **Daemon Topology Engine (`divoomd`)**: Implemented `get_topology` and `set_topology` socket dispatch commands with JSON persistence to `~/.config/divoom-control/topology.json`.
  - **MCP `list_screens`**: Registered tool #14 in `divoomd/src/mcp_tools.rs`.
  - **Canvas Drag Performance & Zero Clickthrough**: Separated visual selection from heavy IPC device connection calls; separated dragging vs clicking via movement delta tracking; zero clickthrough leaks or overlay blocks.
  - **Layout Persistence & Hardware Deck Spacing**: Persistent canvas coordinate saving across `localStorage` and daemon `topology.json` on node drag and desk align; case-insensitive MAC normalization; room management and safe Desk fallback; deck inspector spacing expanded (`padding: 12px`, `gap: 12px`, `min-height: 24px` on select, preventing cramped inputs and text clipping).
  - **Hardware Deck Layout & Room Device Management**: Dedicated full-width device name row (`.deck-name-row`), contained room dropdown (`.deck-select`) without "ROOM" label clipping, `(Unassigned / No Room)` support, live device count badges on room pills, and interactive room device checklist popover (`.stage-room-devices-popover`).
  - **Appbar Stage Integration & Clean Bottom-Docked Deck**: Moved stage/ribbon header controls directly into the native window appbar (`.integrated-appbar`), eliminating redundant top header bars and reclaiming 32px of vertical canvas; re-anchored Active Display Hardware Deck to the very bottom of the sidebar (`margin-bottom: 2px;`) and retired the redundant sidebar `#wall-button`.
  - **Suite**: 204 Rust unit tests, 314 Python pytest tests (2 skipped), 15 mock device E2E tests, 736 files clean in emoji gate, 116 API methods reachable, 387 source files <= 500 lines.

- **v0.34.0 — the hardware round (2026-09-07)**: the R12 visual pass, open
  since R12, closed **4/4 on real pixels**. It found one real defect —
  `run_weather` set weather DATA and never selected the face that draws it, so
  after any job that took the Design channel it updated something invisible, and
  the GUI's own weather toggle had the same gap. On the way it established that
  `hw_verify` had been **unrunnable for rounds**, naming a pre-port API
  (`live_jobs.start`, `media.push_album_art`, `display.show_weather`) the daemon
  has never answered — so the pass would have failed identically with no device
  attached. `--self-test` could not have caught that: it proves the packet
  reports FAILURE for a bogus method, which says nothing about whether its own
  names exist. Three further defects were the reviewer's own, made while fixing
  the first two. New gates: `check_hw_verify_methods.py`, a `BareChannel` type
  that makes the bad clock switch uncompilable, and `scripts/install_local.sh`,
  which proves the daemon that comes back is the binary it just wrote.

- **v0.30.0 — R71 + R72 (2026-08-31)**: the gates got real, and the daemon got
  its jobs back. **R71**: `pre-push` ran four structural checks while appearing
  to run eighteen — the rust and python layers were commented out, so the whole
  local CI and both coverage floors ran only when someone typed the command. All
  five gate classes are now proven to REFUSE a push. The API allowlist went
  **20 -> 3**, and three of its stated reasons were false. The Python coverage
  floor was passing by ROUNDING (advertised 90, enforced ">= 89.5", actual
  89.50). LAN failures now say why instead of failing blankly.
  **R72**: `tools/capability_census.py` — 443 daemon commands from the Rust
  match arms against an AST walk of the whole shipped Python surface — is now a
  gate reporting 0 DIRECT, 0 WRAPPED. On the way it found a credential store
  that would have **destroyed the user's config.ini** the first time anything
  routed to it, a `sync_time` that set the device clock to **the year 2000** and
  reported success, an **unauthenticated** control surface handing every GUI API
  method to any local process, 292 lines of dead notification polling, and a
  verification harness checking a path the product no longer takes. Two of the
  seven findings turned out to be misdescribed by the audit that raised them.

- **v0.29.0 — R70 (SHIPPED 2026-08-30)**: the GUI is a client, not a second implementation. Twelve
  findings moved to `divoomd` and the class closed structurally — the
  `check_gui_is_a_client.py` allowlist went from 27 violations across twelve
  files to EMPTY. Found five defects on the way that nobody was looking for: a
  `u128` overflow that panicked the daemon and silently broke the shipped
  hot-channel push, an app that killed its own healthy daemon on every launch,
  an MCP button that launched a second GUI, an album-art preview differing from
  the device on 100% of pixels, and gallery containers that never decoded.
- **v0.28.3 — R69**: version parity made structural. Binary selection goes by
  VERSION rather than by location or mtime, `divoomd --version` answers without
  starting a daemon (it used to start one), both binaries refuse unknown
  arguments instead of ignoring them, and `tools/check_built_binaries.py` fails
  the build when a compiled artifact disagrees with the tree.
- **v0.28.2**: tooling and docs only; the app is byte-for-byte the behaviour of
  v0.28.1. `scripts/gui_pov.py` promoted out of a scratchpad, macOS Bluetooth
  TCC written down, 14 dead scripts and `docs/archive/` pruned.
- **v0.28.1**: the GUI killed the daemon. `now_playing`/`players` built a
  `reqwest::blocking::Client` inside an async context, and dropping its private
  tokio runtime aborted the process — so opening the app with music paused took
  down the background service. Found by launching the app, not by the 2961
  passing tests.
- **v0.28.0 — R68**: two gates that were wrong about their own subject; the
  socket "hold it open" rule made structural (`HeldSocket`, enforced by Rust's
  drop order rather than by three comments); camoufox raised to the latest build
  through a main-world bridge; sysmon made a daemon client so the preview and
  the device draw the same bytes.

_"Key files" are the paths as they stood in that round. Several no longer exist
(`divoom_lib/device.py`, `models.py`, `hotchannel.py`, `display/clock.py`,
`tools/calendar.py`, `notification.py` were refactored away, and the whole
Python layer is reference-only now — `divoomd` is the product). They are left as
written rather than retro-mapped: a historical record guessed at is worse than
one that is plainly of its time._

| Round | Summary | Suite | Key files |
|-------|---------|-------|-----------|
| **R3** | BLE connection scaffolding + first commands | — | `divoom_lib/connection.py`, `divoom_lib/divoom.py` |
| **R4** | Extended command set (0xBD system cmds) + models | — | `divoom_lib/models.py`, `divoom_lib/display/` |
| **R5** | Image rendering pipeline + GIF animation | — | `divoom_lib/renderer/`, `divoom_lib/encoder/` |
| **R7** | Digital clock command + time sync + BLE stability | — | `divoom_lib/display/clock.py` |
| **R8** | Layout framework + PyWebView GUI + sidebar | — | `divoom_gui/` (greenfield) |
| **R9** | Screen orientation, system brightness, factory reset | — | `divoom_lib/display/design.py`, `divoom_lib/device.py` |
| **R10** | Notification mirroring (macOS → device) | — | `divoom_lib/notification.py` |
| **R11** | Weather + scoreboard + noise meter + stopwatch | — | `divoom_lib/tools/` |
| **R12** | GUI polish: glass tabs, appbar, hardware verification plan | — | `divoom_gui/web_ui/` |
| **R13** | Calendar + memorial countdown + time-plan | — | `divoom_lib/tools/calendar.py` |
| **R14** | Hot-channel scheduling + notification preferences | — | `divoom_lib/hotchannel.py` |
| **R15** | MCP server (stdio JSON-RPC, tools/list + tools/call) | — | `divoom_lib/mcp_server.py` |
| **R16** | Daemon HTTP JSON-API + menubar app | — | `divoom_daemon/daemon.py`, `divoom_gui/menubar/` |
| **R17** | Daemon single-owner (R17 P5) — daemon owns BLE, GUI is client | — | `divoom_daemon/device_owner.py`, `divoom_gui/daemon_bridge.py` |
| **R19** | Timer/countdown/noise controls + cloud-connection monitor | — | `divoom_lib/tools/timer.py` |
| **R20** | `tmp`→`divoom_lib` migration + C downsampler | — | `divoom_lib/encoder/downsample.c` |
| **R23** | 500-LOC debt retired (all files <500 lines) | 994/0/75 | (many splits) |
| — | GUI crash-loop on cloud-auth failure fixed | 994/0/75 | `divoom_auth` caching |
| **R24** | connect-timeout fix, toast removal, glass tab strip | — | `divoom_daemon/device_owner.py` |
| **R26** | Daemon channel-switch API + weather push fix | 1025/75/0 | `set_temperature_channel()`, `push_weather()` |
| **R27** | Command queue (ring buffer, maxsize, item timeout) | 1055/75/0 | `divoom_daemon/command_queue.py` |
| **R28** | MCP-via-daemon, scan filter, tab layout, bitmap font | 1079/75/0 | `daemon_client.py`, `fonts/`, `tabs.css` |
| **R29** | Exclusive mode wired through daemon RPC | 1085/75/0 | `device_call(token)`, `DaemonDeviceProxy.exclusive()` |
| **R30** | Animation streaming — MCP tool + proxy exclusive context | **1090/75/0** | `push_animation()`, MCP 13th tool |
| **R31** | Font improvement + CJK infrastructure + warning fixes | **1093/75/0** | majority-rule half-font, CJK `from_apk_asset()`, coroutine cleanup |
| **R32** | Monthly Best reorg + Routines + device selector + Text fix | **1094/75/0** | gallery multi-select, per-device gallery style, 0x87→image text push |
| **R33** | Sidebar reorg + Settings polish + per-device gallery style | **1094/75/0** | Routines nav, device dots, toggle-switch settings, appbar gear |
| **R34** | Hot-channel sync fix + Routines polish + APK-aligned 0x8b upload | **1185/75/0** | `sync_read_timeout`, device-dot pulse, alarms week-table, device-driven 0x8b flow |
| **R54** | Notifications, schemas, TCP/token auth & Rust auto-spawn | **1185/75/0** | `macos_notifications.rs`, `socket_server.rs`, `daemon_client.py` |
| **R55** | Bluetooth Classic SPP subprocess bridge integration | **1185/75/0** | `spp_bridge.py`, `spp.rs`, `transport.rs`, `daemon_connect.rs` |
| **R56** | Cloud Auth, Category Gallery API & Monthly Best Loop | **1703/87/0** | `cloud.rs`, `monthly_best.rs`, `daemon.rs`, `basic.rs` |
| **R57** | Daemon connect-robustness (dead CoreBluetooth wedge) + bulletproof tests | — | `scanner_mixin.py`, `daemon_connect.rs` |
| **R58+R59** | `divoomd` rename + daemon hardening + **event-driven UI** (broadcast/subscribe: `status`/`owned_devices`/`notif_status`/`hot_progress`/`degraded`) | — | `socket_server.rs`, `daemon_connect.rs`, `connection_events.js` |
| **R60** | Open-thread verification: docstring strip, durable `device_call` parity test (caught + closed 15 key-alias gaps), `show_clock()` realigned to APK `C2()` canonical, `get_*` read-back timeouts bounded+cached, Python daemon marked REFERENCE/FALLBACK, Ditoo soak, cloud-decode push (3/4 devices) | — | `tests/test_device_call_parity.py`, `display/__init__.py`, `divoom_daemon/*` |
| **R61** | Release v0.22.9 + doc prune + **Cloud HTTP** (`UserNewGuest` RC=10 fix + clock-face store) + coverage gate (≥95%, hit 96%) + hardware-verified device detect/connect | — | `divoom_auth.py`, `cloud.py`, `cloud_cmds.rs` |
| **R61 follow-up** | Release v0.22.10 — real daemon+UI e2e connect/disconnect verification (mock-transport drop simulation, `tests/e2e_gui_bridge.py`) + **native menubar now shows device connect/disconnect/degraded** (previously only reflected the notification monitor) + device-loop thread-teardown hardening | 3197/97/0 | `divoomd/src/daemon_mock.rs`, `divoom-menubar/src/state.rs`, `tests/test_e2e_gui_daemon_connect_disconnect.py` |
| **R66** | Repo restructure: one Cargo workspace, `divoom_daemon/`->`divoom_client/`, -14,240 LOC, six silently-degraded gates repaired | Py 2910/94, Rs 119/0 | `Cargo.toml`, `divoomd/src/paths.rs` |
| **R67** | Live-defect round: 7 named classes. Typed 0x45/0x5F packets; hot-channel events; socket ownership; live-job health; MediaRemote album art + player discovery; weather unified; **the virtual wall never worked** (3 showstoppers); daemon protocol audit + capability negotiation | Py 2904/0/94, Rs 244/0 | `divoomd/src/packets.rs`, `nowplaying/`, `divoomd/src/wall/dispatch.rs` |

Suite at v0.28.3: **Rust 291 passed** (workspace, `cargo test --locked`) / **Python 2935 passed, 94 skipped**. Rust coverage 43.06%, floor 42.
These are the numbers as of the last release; `CHANGELOG.md` and CI are the
per-round record. The per-round counts in the table above are historical and
are not restated.

---

## Current debt & quality

- **Gates**: 25 steps, run by `pre-push` since R71 P0 — they used to run only
  when someone typed the command. Local and CI are kept identical on purpose.
  `check_applescript_launch.py` joined the list on 2026-09-07: no source may
  address an application by LaunchServices NAME in AppleScript without an
  `is running` guard. It exists because `tell application "Python" to activate`
  in the GUI's focus path launched a stranger's Python.app and crashed it in
  dyld, four times, for a user.
- **500-LOC rule**: enforced, allowlist empty (R23).
- **Coverage**: Python floor 89.2 (measured 89.30), and it now enforces the
  number it advertises — it was claiming 90 and enforcing ">= 89.5", because
  coverage.py rounds. Rust floor in `scripts/rust_coverage.sh`.
- **Duplication**: `tools/capability_census.py` reports 0 DIRECT, 0 WRAPPED
  against 443 daemon commands, and fails the build on a new one. Parity gates
  hold the two files that legitimately have two readers
  (`check_weather_parity.py`, `check_hotchannel_parity.py`).
- **Tests**: ~3000 Python, 198 Rust; hardware tests gated/skip by default; 60
  native-downscaler parity tests. **The browser e2e subset is flaky under normal
  load — see the OPEN item below.**
- **C module**: `libdivoom` (LANCZOS downsampler) via `build_libdivoom.sh`;
  normalize-then-quantize matches PIL byte-for-byte (60/60 parity tests).

---

## Open workstreams

### v0.37 plan: finish the fleet model, then the residuals (filed 2026-09-12; all seven SHIPPED)

Order is by leverage; 1-3 are one thread, 6 is independent, 5 is
measurement-gated. Each step shipped with its tests shown red first.

**0. The CLI is a daemon client — SHIPPED (e1b8ca7)** — user correction.
`cli_commands` attaches to the running daemon (`ensure_daemon(spawn=False)`;
a shell-spawned daemon has no Bluetooth grant and dies on its first scan,
so with nothing running the CLI says what to start, exit 3) and drives
`DaemonDeviceProxy(mac=...)`; `scan`/`identify` read the daemon's scan
(`manufacturer_data`, `service_uuids` on the reply); capabilities come
from the table by `--type` or the MAC registry; the CLI never hangs up a
panel. `--mac` names the panel; without it the daemon's resolver answers
for a single linked panel and refuses otherwise (exit 2, listing them).
bleak is out of the CLI's import path. Open question, not decided:
`examples/` documents the bleak facade -- library docs, or retire them in
favour of daemon-client examples.

**1. Retire the daemon's "current" device — SHIPPED (2bcd5b0)**
`Fleet::resolve_target(mac)`: explicit mac, else the single linked panel,
else a refusal naming the count. `Fleet::current`/`current_id`/`preset`
and the daemon `--mac` preset are gone; mac-less `device_status` returns
the fleet; `hot_update` targets the GUI's displayed address; notifications
go to every linked panel. As planned:
The mac-less daemon commands are `hot_update`, `probe_lan`, notification
routing, `exclusive_start`/`end`, `live_jobs_stop_for`, `device_status`,
`disconnect`, and MCP tools when `mac` is omitted (and the CLI after 0).
- One resolver for all of them: explicit `mac`, else the single linked
  panel when exactly one is linked, else a refusal naming the count
  ("3 panels connected; pass mac"). Kills "whichever connected last"
  without breaking the one-panel user.
- GUI passes the displayed address to `hot_update`; notifications get a
  "target panel" setting instead of the implicit current one.
- Delete `Fleet::current`, `current_id`, `preset` and the `--mac` preset
  once nothing reads them; mac-less `device_status` returns the fleet.
- Tests: stress scenario "two linked, mac-less call refused with count";
  MCP one-panel default.

**2. `appConnected` per panel — SHIPPED (b05083d)**
`panelIsLinked(mac)`, `requireDevice(mac)`, per-panel status events, fleet
counts from linked panels; `test_fleet_status_is_per_panel.py` covers the
other panel dropping. As planned: keep the name, make it DERIVED inside `setConnectionState` from the
selected panel's `daemonOwned && activityState !== "disconnected"`; no
other writer. `requireDevice()` keeps its 25 call sites and gains an
optional mac. Tests: extend `test_fleet_status_is_per_panel.py` — the
other panel drops, the selected one still passes `requireDevice`.

**3. Menubar tiles draw the frames — SHIPPED (5d4b33f)**
`tiles::TileCache` decodes each panel's PNG data URL once into the row's
`Submenu` icon (nearest-neighbour to 36pt, set in place when the row
signature is unchanged); tooltip "N of M panels online". The visual check
on the real tray is pending the next install. As planned:
`DeviceView.preview` is a PNG data URL from the frame broadcast. Decode
once per change (`image` crate) into a `muda::IconMenuItem` per panel
(tray-icon 0.24 bundles muda), cached by the URL string. Tooltip: "3 of 4
panels online". Tests: data-URL to RGBA incl. a rejected non-PNG; visual
check on the real tray with two panels streaming.

**4. Now-playing masking — SHIPPED (a2a0520, fd038e8; the "platform limit"
was a wrong signature)**
The first probe declared `MRMediaRemoteGetNowPlayingInfoForClient` as
`(client, queue, block)`, it crashed, and this item was closed as a platform
limit. Wrong: read from the framework's own code on macOS 26.6.2
(`dyld_info -exports` + in-process disassembly, see the
`private-framework-signatures` skill) it takes FIVE arguments,
`(client, origin, includeArtwork, queue, block)`, building an `MRPlayerPath`
and calling `...InfoForPlayer(path, includeArtwork, queue, block)`.
`GetPlaybackStateForClient(client, origin, queue, block(u32))`,
`GetActivePlayerPathsForOrigin`, `GetLocalOrigin()` and
`CopyPlaybackStateDescription` (0 Unknown 1 Playing 2 Paused 3 Stopped
4 Interrupted 5 Seeking) verified the same way and live through the
entitled perl host. The helper now reads every registered client's state
and reports the playing one with the richest record; the elected session
is the fallback when nothing plays. Live (Kaset playing, Music open): the
elected session was Kaset's own five-key stub with no artwork, the WebKit
GPU client carried the full record with the art, and the helper reported
the latter. Players carry their states (`Kaset (playing)`,
`Music` unknown) in the idle hint.

**5. Browser e2e flakiness under load — MEASURED and SHIPPED (2026-09-12)**
Measured: the whole browser subset (150 tests, every module that launches
camoufox) run twice under a CPU burner on half the cores plus a
`cargo check` loop, on top of the machine's own load (average 30-130):
150/150 and 150/150, 597s and 587s, against 412s unloaded. No test
failed, so nothing to attribute; what the numbers DID show is one
readiness wait (`test_e2e_widget_selection`) going from 3s unloaded to
16s under load, 3s short of the 20s budget -- the budget was the risk,
not the waits (they are already readiness observables via `wait_js`).
Shipped: `UI_TIMEOUT_MS` default 60s, sized from that 5x swing with
margin (a cap costs nothing on a green run); the browser suites run in
their own serialized CI step, which they never did before (CI installed
camoufox and then ran pytest without `--run-browser`); and the opt-in
moved to the launch seam (6d9cda6), which unhid 30-odd non-browser tests.
Gate going forward: that CI step, plus re-run this measurement if a
budget is ever raised again.

**6. Plaintext password in config.ini — SHIPPED (1830695)**
`secret_store` behind `cloud_store::load_config`/`save_config`: macOS
Keychain through the Apple-signed `security` CLI in stdin mode (service
`divoom-control`, account `divoom-cloud`; the framework would key the
item's ACL on the daemon's churning local signature), Linux `secret-tool`
when on PATH, else the 0600 file with a once-logged warning;
`DIVOOMD_SECRET_BACKEND` forces one. Migration on READ blanks the file
copy; an email-only save moves a file password first; a refused NEW
password writes nothing. Settings says "Password stored in Keychain" (one
renderer for the status box). Tests drive a `FakeBackend` against temp
files; migration proven red-then-green; the HOME-based tests pin the file
backend so nothing touches a real keychain.

**7. The active panel (user request 2026-09-12) — SHIPPED (216ce0b,
1920ec7, 1ebb6df, 1612a37)**
"It's not clear from the menubar which device is active, and there is no
way to switch." Selection is a fleet-level fact the daemon owns
(`Fleet::selected`): the first panel to link takes the slot; a bench
click, the menubar's "Active panel" item or `divoom-control select --mac`
change it through `select_device`, which broadcasts `selection` and
`owned_devices` (each device carries `selected`) so every client follows.
The resolver: explicit mac, else the active panel while linked, else the
single linked panel, else a refusal that says whether the active panel is
offline or none is active; forgetting the active panel hands the slot to
a linked one. The bench's first-render fallback is provisional (Python
proxy only) so a GUI start never overwrites a choice made elsewhere.
Live on the installed build: CLI select moved the bench; the tray's
submenu switch moved the daemon and the bench. Found on the way: the tray
said "No active devices" with two idle panels linked (its polled fallback
read the live-widget activity map); the daemon now serves `owned_devices`
on request in the broadcast's shape.

### The per-device rule (v0.36.0, read before adding any per-panel state)

**All per-device state lives on ONE struct per panel** — `Device` in the
daemon, `DeviceView` in the menubar, `discoveredDevices[mac]` in the GUI —
and each fact has ONE writer. The class this closes: two owners of one
per-panel fact drifting apart. It produced, in one day, a frame that landed
after "stop", a push on the wrong panel, a fleet renamed "Divoom", jewels
that were always green, and previews that stopped following the device.

* Anything that sends to a panel goes through `Device::link()` ->
  `Link::run` / `Link::queue.acquire`. Never hold a transport `Arc` across an
  await without the link's permit. Never key new per-device state by mac
  string — put it on `Device`.
* A queued unit of work holds the `Link` it was queued on and re-checks
  `retired` (and its job's `alive`) at execution time. Abort alone never
  cancels work already handed to the queue worker.
* The daemon's "current" device exists only for mac-less callers (CLI, MCP
  tools). The GUI names its panel on every call. Retire "current" once
  those two pass `mac` (open item).
* The GUI's selection changes through `setSelected` -> `select_device`
  only. A status event updates the panel it names; the global dot follows
  the SELECTED panel; a status naming nobody is fleet-wide.
* The gate is `divoomd/tests/live_jobs_stress.rs`; every new scenario there
  should be shown red first.

Residual, filed: MediaRemote answers for one Now Playing session, so a
playing app behind a stopped holder cannot be read; the idle reply names
the registered players and the card shows the hint.

### SHIPPED — user-reported defects filed and closed 2026-09-12

All six, live-confirmed on the installed build with the user present.
The mechanisms and commits are in the v0.36.0 CHANGELOG stanza. What the
next reader needs: #3's "slow/flaky" was two things (a healthy link
switches in 0.04-0.12s; the flakiness was the connecting-state funnel),
and #1's first fix went the wrong way (the cover is a PHOTO and scales
smoothly; only the device frame is diodes). Reopen #3 only with a
timestamped slow switch plus the link state captured alongside.

### SHIPPED — code rearrangement (2026-09-12, four phases in three commits)

Recover the plan with `git log --diff-filter=D -- docs/PLANNING_TEST_REORG.md`.
**Phase 1** (`5d92643`): 4 strays into `tests/` (all hardware-gated),
`hw_test_modes.py` → `hw_walk_modes.py`, 4 ungated `pub mod *_tests`
gated, new `tools/check_test_placement.py`. **Phase 2** (`3f37b6c`):
dead trio + 2 superseded runners deleted, `perf_*` → `scripts/`
(11 perf tests pass explicitly; never suite-collected). **Phase 3**
(`245c961`): audit found almost nothing obsolete — `examples/` × 7,
both old-path scripts, all 14 CLI subcommands KEPT with reasoning;
README stale-weather paragraph fixed; new `tools/check_examples.py`;
`scratch/` emptied (42 ignored files, regeneration proven).
**Phase 4**: full `ci_local.sh` 28/28 green, plan pruned to history.
Suite end state: 2946 passed / 236 skipped; collection 3182.

### The ownership rule (read this before calling anything a duplicate)

_Current as of 2026-08-31, after R72._

**`divoom_lib` is the protocol reference AND a live runtime dependency. Both.**
_(Rewritten R72 P4. The previous wording — "OBSOLETE and kept for REFERENCE
ONLY" — was false, and falsely reassuring: it is the sentence that let F1-F6
sit unexamined, because it told every reader that Python/Rust overlap was
documentation rather than something to check.)_

`divoomd` (Rust) is the shipping implementation of every DEVICE, CLOUD and HOST
capability. `divoom_lib` is the protocol ground truth the port was derived from.
It is ALSO imported at runtime by **21 files** in the shipped Python surface,
and after R72 every one of those falls into a category that is legitimate:

| Category | Modules | Why it is not a duplicate |
|---|---|---|
| Client-local utilities | `utils.atomic_io` (7), `lifecycle_config` (7), `utils.converters`, `utils.media_players` | atomic writes and GUI preferences the client alone reads |
| Shared protocol vocabulary | `models` (5) | constants (`WeatherType`, `STI_CTRL_FLAG_*`) — names, not an implementation |
| Client-local preference resolution | `weather_provider` (3) | `resolve_location`/`saved_location` are pure: env vars and a saved city, no network |
| The daemon's own arm | `bt_spp_transport` via `divoom_client/spp_bridge.py` | **`divoomd/src/spp.rs` SPAWNS it** — macOS IOBluetooth Classic SPP is not reachable from Rust, so the daemon delegates to a co-process. The daemon still owns the device |
| Dev tooling | `native` in `scripts/codegen/` | generates test vectors; not shipped |

**So the rule that replaces "reference-only" is:** a `divoom_lib` import is a
defect when it performs a job the daemon owns — device I/O, cloud HTTP, host
data, rendering, device-facing persistence — and is fine when it supplies a
constant, a pure helper, or a client preference. `tools/capability_census.py`
enforces exactly that distinction, and its confident set (DIRECT + WRAPPED) is
**zero** as of R72.

Two things remain true and are not contradicted by any of it:

* where the **GUI executes** Python that duplicates a daemon job, that IS a real
  defect (the GUI must be a client, not a second implementation) — this is what
  R67/C2 fixed for now-playing and weather;
* Python remains canonical for **wire formats**. Every R67 packet bug was found
  by diffing the Rust payload against the Python builder it was ported from, and
  Python was right every time. Parity gates that compare the two
  (`tools/check_weather_parity.py`) keep the port honest against its reference.

**Feishin — RESOLVED 2026-08-29.** It never appeared in now-playing because its
own `mediaSession` setting is OFF, so it does not register as a macOS Now
Playing client at all. Settled by enumerating the client registry rather than
by asking the user to quit apps. The fix is one toggle in Feishin, not code
here; the daemon's `players` reply carries a hint naming the setting. Left off
by user decision, so `nowplaying/src/feishin.rs` (Subsonic) remains its weaker
source. Detail in the v0.27.0 CHANGELOG stanza.

**Open: nothing in this workstream.** Both items closed in R68.

### OPEN — the weather widget should RENDER, not drive the device's own face

_Raised 2026-09-07, immediately after the hardware round that fixed it._

`run_weather` sends 0x5F weather data and a `ClockPacket`, i.e. it configures
the DEVICE's built-in clock face and lets the firmware draw and cycle it. That
is why it was the only widget that broke: `sysmon`, `album_art`, `stocks` and
`custom_art` all RENDER pixels here and push frames into the Design channel, so
they own what appears. Weather borrows a face it does not control, and inherits
its behaviour — the cycling, the panel semantics (`weather` draws TEMPERATURE,
`humidity` draws the icon face), and whatever the firmware decides to do next.

**It should be a rendered widget like the others**: a `weather` kind in
`render_widget::KINDS`, drawing the current condition and temperature into a
frame the daemon composes, with a layout this project controls and an update
cadence it chooses. `crate::weather::fetch` already returns the reading, and
`live_jobs/render.rs` + `font.rs` already do this job for sysmon and text.

Two things this buys beyond consistency: the widget stops being at the mercy of
a firmware face nobody here specified, and it becomes the first consumer of the
custom-image path the MCP item below wants to expose — so the two are one piece
of work, not two.

### OPEN — Multi-device display surface and custom rendering over MCP

Enable external processes and AI agents to discover, target, and display custom visuals (images, animations, text) on Divoom devices via the daemon-backed MCP server.

#### 1. Device & Screen Discovery (`list_screens`)
- **Topology & Geometry**: Expose `device_id` (MAC or identifier), model class, native resolution (`width`, `height`), connection status (`connected`/`disconnected`), and relative positioning coordinates `(x, y)` if configured in a multi-device layout.
- **Explicit Targeting**: The caller explicitly selects the target screen (`target: "<device_id>"`, `"all"`, or a list of IDs). The daemon does not implicitly slice content across devices or assume virtual-wall composition unless specifically requested.

#### 2. Media & Text Rendering Pipeline
- **Image & Animation Sizing**: Accept an explicit resize policy (`fit`, `fill`, `exact`, `none`) rather than silently downscaling to 16x16. Support arbitrary native resolutions (16x16, 32x32, 64x64). Return a descriptive error if non-matching dimensions are supplied with `none`.
- **Full Animation Streaming**: Implement multi-frame animation streaming in the native MCP server (closing the current first-frame limitation in `divoomd mcp`).
- **Native Text Rendering (`show_text`)**: Provide a high-level text tool using the daemon's internal bitmap font engine (`font.rs`), supporting font choice, color, and optional marquee/scrolling behavior without requiring the client to pre-rasterize.

#### 3. Live Jobs, Notifications & Built-in Tools
- **Live Widget Lifecycle (`live_jobs_control`)**: Expose tools to start, stop, and inspect background widgets (`sysmon`, `now_playing` / album art, rendered weather, custom art) rather than requiring direct daemon socket calls.
- **Transient Notifications (`show_notification`)**: Expose a tool to display transient visual notification alerts on the panel.
- **Hardware Tools Mapping**: Expose device tools already implemented in the daemon: scoreboard score updates (`scoreboard.set_scoreboard`), timers (`timer.set_timer`), and countdowns (`countdown.set_countdown`).
- **Rich Capabilities Introspection (`get_capabilities`)**: Upgrade the tool to return physical panel dimensions (`width`, `height`), device model, battery status, and hardware feature flags (speaker, radio, clock).

#### 4. Resource Arbitration & Session Management
- **Screen Leasing & Priority**: Prevent visual collisions between background daemon jobs (sysmon, weather, clock) and external applications. Callers acquire a timed lease (`acquire_screen` / `release_screen` or per-request lease tokens).
- **Lease Expiration & Crash Recovery**: A lease must carry a mandatory TTL (e.g. 10–60s) with renewal. If a client terminates or fails to renew, the panel reverts to its previous or default channel rather than retaining a stale frame indefinitely.
- **Link-Aware Conflation**: For continuous frame pushes over high-latency links (BLE/SPP), incoming frames for a target device are conflated (keeping only the latest frame and dropping intermediate backlogs) to avoid saturating transport queues.

#### 5. Security & Failure Semantics
- **Access Control**: Clearly define whether the MCP surface inherits the daemon's local Unix socket trust model or requires token-based authentication over TCP.
- **Fail-Fast Error Reporting**: Pushes to disconnected or unready devices must fail immediately with clear status codes (`DEVICE_DISCONNECTED`), preventing silent no-ops.

**Implementation Sequencing:**
1. Upgrade `render_widget` to support rendered weather (validates the rendering pipeline within the daemon).
2. Enhance native device capabilities/status reporting (`device_status` carrying model and panel resolution).
3. Extend `divoomd mcp` with `list_screens`, resolution-aware image/animation streaming, text rendering, and lease-based arbitration.

### SHIPPED (v0.35.0) — Unified Spatial Stage & Physical Scale Engine (Phases 1–3 + Option 1)

_Shipped in v0.35.0: Full-width top Spatial Preview Bench, physical millimeter proportions database, freeform 2D drag placement, desk baseline alignment, compact ribbon toggle, room filter pills, daemon topology persistence, MCP `list_screens` tool, decluttered titlebar, and sidebar Active Display Hardware Deck with contextual volume and independent brightness._

#### Shipped Capabilities:
1. **Daemon Topology Engine**: `get_topology` and `set_topology` socket dispatch commands with JSON persistence to `~/.config/divoom-control/topology.json`.
2. **MCP Tool `list_screens`**: Exposes physical screen coordinates, dimensions, and resolutions to MCP AI clients.
3. **Physical Scale Database**: Mapped exact physical chassis and active screen dimensions ($1\text{mm} = 0.65\text{px}$) for Ditoo, Timoo, Tivoo-Max, Pixoo, and Pixoo-64.
4. **Full-Width Top Bench (Option 1)**: Re-architected the window layout with a full-width top stage (~1100px) above `.app-container`, removing nested double toolbars.
5. **Sidebar Hardware Deck**: Pinned to bottom of the sidebar with active identity, Kare SVG power toggle, room assignment, brightness slider, and contextual volume slider (hides for screen-only Pixoo models).

### SHIPPED (v0.35.2) — Unified DisplayPreview Object Architecture & Hardware-Faithful Bitmap Rendering
- **Unified Object Architecture**: Introduced `DisplayPreview` and `DisplayPreviewRegistry` (`preview_controller.js`, `index.html`) establishing an object-oriented state and rendering controller per physical/virtual display. Completely isolates N devices, eliminating crosstalk where setting activity on screen A mutated screen B.
- **Hardware-Faithful Bitmap Pixel Art Clocks**: Replaced blurry browser vector SVG `<text>` fonts with 1-bit integer LED bitmap digit tables (3x5 matrices) rendered via discrete pixel `<rect>` blocks. All 6 clock styles (Full Screen, Rainbow, With Box, Analog Square, Full Screen Neg, Analog Round) render 100% sharp pixel art on integer coordinates.
- **Gallery Selection to Hardware Push**: Added click handler on `.gallery-item` tiles to select artwork, immediately update active `DisplayPreview` frame, and dispatch `window.pywebview.api.play_gallery_art`. Implemented `play_gallery_art(file_id)` in `GallerySyncMixin` to find/retrieve cached GIF/images and stream to the active display via `display_wall_image`.
- **Custom Art Robustness**: Fixed `init()` guard in `custom_art.js` to check `panel.dataset.initialized` so re-injected templates properly re-attach slot event listeners. Updated `assignToSlot` to immediately mirror the assigned art thumbnail to the active display preview.
- **Spatial Stage Streamlining**: Simplified stage animation loop by delegating directly to `DisplayPreviewRegistry.get(addr).renderTo(cvs, tick)`, retiring redundant local caches and bringing `spatial_stage.js` safely under the 500-LOC ceiling (460 LOC).

### OPEN — Core Architectural Unification & Multi-Display Estate

#### 1. Streamline Virtual Wall & Consolidate Presets into Spatial Rooms (SHIPPED 2026-09-12)
- **Delivered**:
  - Unified Virtual Wall arranger preview rendering with the Main Bench (`#spatial-bench`) via `DisplayPreviewRegistry`.
  - Banished false-positive orange "W" glyph on the Main Bench when wall devices are on procedural channels (`clock`, `eq`, `ambient`).
  - Rendered authentic integer pixel art canvases inside the Arranger nodes (`.arranger-node-canvas`) synchronized with the Spatial Stage loop.
  - Two-way synchronized layout presets (`presetsSelect`) and arranger node dragging with the `SpatialRooms` engine (`devRooms[mac] = 'Wall'`, `pos[mac] = { x, y }`, persistent saving, and live Spatial Stage updates).
  - Added automated test suite `tests/test_virtual_wall_preview_sync.py` (3 passed).

#### 2. Per-Device Live Widget & Background Streamer Binding (SHIPPED v0.36.0)
- Live jobs live on the daemon's `Device` (one per panel), push frames bound to that panel's `Link`, and broadcast each frame with its pixels; the GUI's previews mirror the panel from the bus, so a job on A keeps painting A's preview while the user works on B. Selecting a panel binds the Python proxy to it (`select_device`).

#### 3. Multi-Device Fleet State & Transport Lifecycle (MOSTLY SHIPPED v0.36.0)
- Shipped: the daemon `Fleet`; per-panel `activityState`/`daemonOwned` in the GUI written by per-panel status events; bench, ribbon and deck jewels derived from it; the global dot follows the selected panel; the menubar's `DeviceView.link`.
- Remaining: `window.DivoomState.appConnected` is still one boolean (it now means "the selected panel is linked"), and `requireDevice()` gates on it. Battery/brightness/volume are not yet per-panel in the GUI model.

#### 4. Channel Configuration Two-Way Binding (`DisplayPreview.opts`)
- **Finding**: Channel configuration controls (clock style selector, color picker, ambient mode palette) currently operate on global singletons (`selectedClockStyle`, `#clock-color-input`), causing Display 1's clock style to overwrite Display 2's upon selection.
- **Plan**: Two-way bind the Control Center / Inspector controls to `DisplayPreviewRegistry.getActive().opts`. When switching screens, the controls automatically load that display's saved settings without mutating other screens.

#### 5. Unified Spatial Stage: Multi-Panel Virtual Wall Slicing (Phase 4)
- Interactive snapping of adjacent tiles into a contiguous multi-panel composite surface.
- Pushing an image or animation to a wall group automatically slices the canvas across contiguous physical panels according to their relative `(x, y)` coordinates.

### SHIPPED — Preview Animation Fidelity, Channel Decoupling & Gallery Push Reliability

#### 1. Animated Image Previews — SHIPPED v0.36.0 (`gif_frames.js`)
- WebKit never advances a GIF drawn through `drawImage`; a client-side decoder (LZW, local tables, interlace, disposal) hands the canvas the frame for "now", so the canvas stays the one renderer. Validated against PIL over 287 cached gallery GIFs (285 byte-exact; the 2 differ where PIL rounds a two-entry palette).

#### 2. Prevent Out-of-Band Preview Mutations & Live Job Preemption (SHIPPED 2026-09-12)
- **Problem**: Selecting System Monitor (stats) and subsequently pushing an image or gallery artwork caused the device and preview to revert back to stats after 5 seconds due to persistent background streaming loops.
- **Resolution**:
  - *Rust Daemon Preemption*: In `Daemon::cmd_device_call` (`divoomd/src/daemon.rs`) and `art.rs:cmd_custom_art_push`, added `preempt_conflicting_live_jobs` to automatically stop any running live streaming tasks (`sysmon`, `music`, `stocks`, `weather`) on the target device whenever an image, channel, clock, or custom art is pushed.
  - *Python API Preemption*: Fixed `_stop_live_widgets(self, mac)` in `LightingApi` to properly resolve target MAC and call `client.live_jobs_stop_for(target_mac)`; wired into `display_wall_image`, `push_text`, and `set_clock_rich`.
  - *Frontend Job Unbinding*: Updated `DisplayPreview.setActivity` in `preview_controller.js` to automatically unbind active streamer jobs on channel switches and artwork takeovers (`opts.fileId`), while preserving bindings during normal live frame ticks (`{ src: src }`).
  - *Unscoped Fallback Removal*: Removed the unscoped `_activeDeviceMac()` fallback in `app_globals.js:markActiveDeviceFrame` so that when `kind` is specified, it never clobbers active displays when no displays are bound to that streamer.
  - *Timer Containment*: Wired `widgets.js` to listen for `divoom:activity-updated` and clear local timers and active cards on non-widget activities.
  - *Automated Tests*: Verified via Rust integration test `multi_device_routing.rs:test_device_call_preempts_conflicting_live_jobs`, Python unit tests in `test_gui_api_lighting.py`, and Playwright browser test `test_browser_preview_registry.py:test_browser_stats_gallery_job_preemption`.

#### 3. Fix Gallery Artwork Double-Click Requirement (SHIPPED 2026-09-12)
- **Problem**: Clicking an artwork tile in the Community Gallery (`#gallery-container`) failed on the first click when uncached, requiring the user to press the image a second time.
- **Resolution**:
  - *Bound Method vs Instance in Python Backend (`divoom_gui/gallery_sync.py:113`)*: In `play_gallery_art(file_id)`, fixed `client = self._client()` method lookup and resolved `cur = getattr(self, "current_divoom", None)` so that uncached previews are reliably fetched, cached, and streamed on the very first invocation without throwing swallowed `AttributeError`s.
  - Added preemption `client.live_jobs_stop_for(mac)` in `play_gallery_art` before pushing the artwork.
  - Verified via unit test `test_play_gallery_art_stops_live_widgets` in `tests/test_gui_api_lighting.py`.

### SHIPPED (2026-09-12) — Rust Daemon Architectural Remediation & Fleet Transport Pool Unification
- **Per-Device Queue Serialization (`command_queue.rs`, `daemon.rs`)**: Added RAII `QueuePermit` with oneshot channel completion. Wrapped `cmd_device_call` in `q.acquire(token).await`, guaranteeing strict FIFO command ordering and mutual exclusion between RPC callers, live streamers (`run_sysmon`, `run_stocks`), and multi-packet firmware updates (`art_hot.rs`).
- **Ghost Live Streamer Cleanup & Multi-Device Disconnect (`daemon_connect.rs`)**: In `cmd_disconnect`, cleanly halts all active streamers (`daemon.live_jobs.stop_all`) and disconnects all `daemon.devices` transports, preventing zombie tasks and phantom channel reversion.
- **Virtual Wall Coordinate-Task Invariance (`wall.rs`)**: Bound `WallConfig` directly to spawned connection tasks in `DivoomWall::connect`, eliminating positional index correlation shifts when any panel fails or panics.
- **Transport Pool Unification & Fleet Preservation (`wall/cmds.rs`, `wall.rs`)**: Unified `daemon.devices` and `daemon.device` into `existing_by_mac` in `cmd_wall_configure`, eliminating duplicate BLE connection attempts, enabling mock device walls in testing, and preserving active fleet connections on wall teardown.
- **Fleet MAC Targeting in Custom Art (`art.rs`)**: Updated `cmd_custom_art_push` and `cmd_custom_art_query_page` to resolve target display via `daemon.resolve_target_device(mac).await`.
- **Automated Verification**: `divoomd/tests/multi_device_routing.rs` (7/7 passed), local CI all 25 steps passed, house gates clean.

### OPEN — Native Menubar Architecture Upgrades (`divoom-menubar`)

#### 1. Event-Driven State Ingestion via `subscribe` (SHIPPED & WIRED)
- **Completed**: `divoom-menubar` consumes event-driven state over persistent `subscribe` stream with zero socket churn in steady state. `divoomd` now broadcasts `"activity"` events on `set_device_activity` and channel switches, updating menubar device labels and channels in real time.

#### 2. Visual Device Tiles with Graphical Previews (data SHIPPED v0.36.0, rendering open)
- `DeviceView.preview` now carries real frames: the daemon broadcasts every live frame as a PNG data URL and keeps it on the panel's activity record. Remaining: hand it to `tray-icon` / `NSMenuItem` as an image instead of text.

#### 3. Actionable Per-Device Controls (SHIPPED & WIRED)
- **Completed**: Device rows in the tray menu feature interactive submenus with quick channel switcher (Clock, Visualizer, Ambient) and screen power standby toggle ("Turn Off Screen" / "Turn On Screen"). Wired to `system.set_screen_on` in `divoomd` with automatic streamer job preemption on standby.

#### 4. Fleet Connection State Aggregation (SHIPPED v0.36.0)
- `DeviceView.link` per panel; `DaemonSnapshot::connection_state()` derives the tray word (any degraded panel wins, else any active). A per-panel status event moves only that panel. Remaining polish: a count in the tooltip ("3 of 4 online").

#### 5. Non-Destructive In-Place Menu Updates
- **Finding**: When `last_sig` changes, `tray.rebuild()` constructs a brand new `Menu` instance and resets it on the tray icon, which can cause UI jitter or dismiss the menu while the user has it open.
- **Plan**: Update menu item labels, icons, and checkmarks in-place rather than rebuilding and re-installing the root `Menu` container on transient activity ticks.

### OPEN — why did 64 subscriptions accumulate in the first place?

The 2026-09-07 wedge is now structurally impossible (a bounded, self-cleaning
subscription registry reclaims the least-recently-active slot, and subscriptions
cannot take more than half the connection budget), but
the ORIGINAL accumulation was never explained, and killing the daemon destroyed
the evidence. Request/reply clients close immediately, so the 64 were
subscriptions; what is not known is whether they were live clients, peers whose
fd outlived them, or connections parked in `handler.handle().await` — which has
no timeout and does not read the socket while it runs, so a peer closing is
invisible to it.

Worth knowing, because the fix bounds the symptom rather than the cause. The
cheap next step is a connection census in `get_status` (count by kind, with
ages), so the next occurrence identifies itself instead of needing `lsof` and a
`sample`.

### Daemon audit residuals (D1-D6, surveyed 2026-09-07)

A post-fix read of the daemon against the four failure classes it had just been
hardened against. Shipped: **D1** (a `write_all` inside the `rx.recv()` select
arm made the evict / idle / read arms unreachable), **D2** (`Lagged(n)` silently
dropped events; the client is now told and disconnected past a budget), **D3**
(`evict.notify_one()` ran under the registry `MutexGuard`), and **D4** (only two
of twelve client writes were bounded — now one `write_line` seam plus
`tools/check_bounded_writes.py`).

Still open:

- **D5 — no connection census in `get_status`.** The next occurrence still needs
  `lsof` and `sample` to identify itself. Same item as the OPEN section above;
  count by kind, with ages.
- **D6 — no client heartbeat in the protocol, and no self-watchdog.** launchd has
  no watchdog (verified as an absence), so on macOS a wedge detector has to be
  in-process and pinged from INSIDE the serving loop — a side-channel self-check
  is exactly the differential observability Gray Failure names. Nothing currently
  notices that the daemon has stopped serving.

Two design findings from the same survey that are worth acting on and are not
bugs: identity-keyed takeover should run BEFORE staleness eviction (MQTT 5.0
reason 0x8E), since a client that crashed and reconnected must replace its OWN
entry immediately; and conflation rather than a lossy ring is the method of
record for status fan-out (a lagging subscriber wants the CURRENT truth, not a
hole).

### OPEN — estate-wide, carried here from the 2026-09-07 campaign scratchpad

This repo shares its gate layer with routines, ztools, monitor and app_updates,
so these outlive any one repo's plan file. Recorded here because the campaign's
own planning file is scratch and will not survive the session.

- **Restriction lints are adopted NOWHERE.** `unwrap_used`, `expect_used` and
  `panic` are `clippy::restriction`, not `pedantic`; routines alone has 931
  unwraps. That is a correctness campaign with its own review, not a switch to
  flip, and each repo's `Cargo.toml` says so in a comment rather than leaving
  the absence implicit.
- **~~No repo has been released since the campaign.~~ DONE 2026-09-07.** All
  six released and installed: divoom-control v0.33.0, routines v0.41.0, monitor
  v0.47.0, ztools v2.3.0, app_updates v1.32.0 (first tag the repo has ever
  had), gates_of_heck v0.10.0. Four of the six had a changelog that did not
  describe what shipped, and two had no changelog at all; each now has one, and
  the release-kit requires a stanza matching the version so the two cannot
  disagree again.

  **Installing revealed the class that matters more than the releases**: an
  installer reports what it WROTE, PATH decides what RUNS, and nothing compared
  them. `ztools` had three copies with the OLDEST winning; `routines` resolves
  through a `.zshrc` entry that puts a checkout's `target/release` ahead of
  everything, so the tool is whatever that build directory happens to hold. See
  the note below.
- **OPEN — PATH decides which build of a tool actually runs, and no installer
  checks.** Found while installing everything on 2026-09-07. Every installer
  copied the right binary into `/opt/homebrew/bin` and said so truthfully; then
  `command -v ztools` ran `~/.cargo/bin/ztools` at 2.1.15, and removing that
  revealed a third copy at `~/bin/ztools` (2.1.8). Worse, `~/.zshrc` line 265
  puts `$HOME/Projects/routines/target/release` ahead of everything on PATH, so
  `routines` is whatever that CHECKOUT'S build directory currently holds — a
  debug build, an abandoned branch, or nothing after a `cargo clean`. It reads
  as correct today only because the same version was just built there.

  The stale `~/.cargo/bin` copies were moved aside (`.shadowed-<date>`), so they
  are recoverable. **The `.zshrc` PATH entry is deliberately NOT changed — that
  is the user's shell config, not this repo's.** The durable fix is the one
  `app_updates/install.sh` now demonstrates: after copying, ask each installed
  binary its identity AND check that `command -v` resolves to the copy just
  written, warning by name when it does not. Worth adding to the other four
  installers.

- **`routines` needs a self-watchdog too**, for the same reason divoom does
  (D6): launchd has no watchdog, so detection must be in-process.

### OPEN — the browser e2e suite is LOAD-SENSITIVE, and it undermines the gate

**Found 2026-08-31 while validating R72.** Two consecutive full-suite runs on
the same commit failed **different, non-overlapping sets** of tests:

| Run | Failures | Tests |
|-----|----------|-------|
| 1 | 4 | `e2e_gui_daemon_connect_disconnect` x2, `e2e_hot_channel_sync_button`, `e2e_sync_now` |
| 2 | 5 | `e2e_device_status_dot`, `e2e_photo_albums`, `e2e_ux_feedback`, `gui_wall_canvas_drag` x2 |

**Overlap: zero.** Every one of the nine is a camoufox/browser test, and every
one passes in isolation — re-run together afterwards, 28 passed in 6m03s.

**And the load is NOT an artefact of this session, which makes it worse.** The
first reading was 9.19 while full suites, `gate.sh --full` and cargo rebuilds
overlapped. But with all of that finished the machine still sits at **6.85**,
entirely from the developer's own processes (an MCP server, a TUI under test).
That is the NORMAL condition this suite runs in. The flakiness is not something
you have to provoke; it is the default on a working machine.

**Why this is not just "flaky tests".** R71 P0 made `pre-push` run the full
local CI, which was the right call and is already earning its keep. But a gate
that fails randomly is a gate people learn to bypass, and `--no-verify` is
exactly the invisible escape hatch P0 was written to avoid. A ~0.15% random
failure rate across ~3000 tests is enough to redden most pushes.

**The likely mechanism**, not yet confirmed: these tests `wait_js` on a
condition with a fixed timeout while a real daemon and a real browser start.
Under load, startup crosses the timeout. That is a threshold chosen on an idle
machine, which is the classic `measure-one-thing` failure.

**Not fixed here** — it is a suite-wide timing property, not an R72 finding, and
diagnosing it properly means measuring browser+daemon startup under controlled
load rather than guessing at a bigger number. Recorded with its evidence so the
next session does not rediscover it, or worse, "fix" it by loosening a threshold
without measuring.

### Earlier shipped workstreams — pruned to git history

The camoufox pin raised to latest (R68), the GUI e2e migration off Playwright
(R66), and the R60-R61 short-to-medium-term list were all complete and were
being carried here as narrative. CHANGELOG is the durable record of what
shipped; this file is for what has not. Recover any of them with
`git log -p -- docs/ROADMAP.md`.

### Cloud HTTP — 533/533 endpoints cataloged

Full catalog at `docs/cloud_api/` (all 16 batches complete). Key shipped features:

- **Clock-face store** — public `Channel/GetDialType`+`GetDialList` API found via
  `r12f/divoom` crate. Wired into GUI as "Cloud Clock Faces" browser in Clock panel.
  Tests: 4 Playwright e2e.
- **Playlist browse+push** — `Playlist/GetMyList`/`SendDevice` confirmed RC=0. Wired
  into GUI as "Playlists" sub-tab in Pixel Art panel. Tests: 3 Playwright e2e.
- **AidSleep browse+play** — `RC=3` was a missing server-side device registration.
  `BlueDevice/NewDevice` lazy-registers on first use. Wired into GUI as "Sleep Sounds"
  sub-tab in Schedule panel. Tests: 4 Playwright e2e.
- **Photo album management** — `Photo/GetAlbumList` (cloud browse) + `Photo/PlayAlbum`
  (LAN apply). Wired into GUI as "Photo Albums" sub-tab.
- **LAN-getter completeness** — 8 read-back counterparts of BLE Set commands.
- **Channel extras** — 5-LCD commands, Voice/SendText, Danmaku: backend-only, not GUI-wired
  (need hardware or render confirmation).
- **`Cloud/ToDevice`** — CLOSED WONTFIX in R71 P4 (see Deferred).
- **`search_weather_city`** — GUI-wired in R70 P3.1; the endpoint itself is
  broken server-side (RC=1 on a valid account, R73 — see Deferred).

### WiFi/LAN command completeness — 45 total, all implemented

Counted from `HttpCommand.java`'s `DeviceAndServerCmd` (43) + `ForceDeviceHttp` (2).
All 4 clusters implemented:
1. **Photo album management** (DONE, live, GUI-wired).
2. **LAN-getter completeness** (DONE, 8 read-back counterparts).
3. **Channel extras + Voice/SendText** — **GATED CAPABILITIES, not open work**
   (R71 P3.3). Backend-only by DECISION, with the reason in the code:
   5-LCD (`Set5LcdChannelType`/`Set5LcdWholeClockId`) is blocked on **a Times
   Gate**, which this project has no reason to own; `Voice/SendText` is blocked
   on **real-hardware render confirmation**, because R32 §D already burned this
   project once — a superficially similar "set light phone word" command ACKed
   cleanly and rendered nothing, and `push_text`'s bitmap path gets the same
   result without the risk. Neither is a gap to close; both are decisions to
   leave alone until their blocker changes.
4. **Danmaku scrolling overlay** — GUI-wired, render still unconfirmed, and now
   behind the P3.1 capability gate: on a Bluetooth-only device it says so
   instead of reporting a generic failure.

Bonus fix: device-selector "not in range" badge now counts consecutive scan misses
(downgrades after 2), not a one-shot startup flag. 5 new e2e tests.

### Deferred — what is left, and what each one is waiting on

Everything R73 and the 2026-09-07 hardware round CLOSED is pruned to git
history: the three unexposed API methods, `sync_time`, `pic_scan_ctrl` 0x35 and
the R12 visual pass. Recover any of them with `git log -p -- docs/ROADMAP.md`;
the reasoning lives in the CHANGELOG stanzas that shipped them.

- **R12 light/dark surroundings** — the only residue of the visual pass. The
  four widgets are verified on the panel; what was never done is judging them
  against a light AND a dark backdrop. That is a photograph, not a code change.

- **Scrolling text — implemented, daemon-only, unsupported by THIS device.** The
  APK marquee sequence is fully ported as `text.show_scrolling_text` (0x6E start,
  0x7C glyph upload, 0x86 string, 0x86 rate). In a `DIVOOMD_BLE_DEBUG` window the
  Tivoo-Max acked `0x45` and returned nothing for `0x6E`/`0x7C`/`0x86`, while the
  same trace showed our bytes were correct. No GUI surface, deliberately. The
  other three devices are the same 16x16 class and untested — **if one acks
  `0x7C`, wiring a button is small work on top of what exists.**

- **`search_weather_city` — the success path is DISPROVEN, not unproven.**
  Against the real, logged-in account it returns `Weather/SearchCity failed
  (RC=1): Failed` for every keyword. Isolated by elimination on the same daemon,
  credentials and HTTP client, in the same minute:

  | Call | Result |
  |---|---|
  | `GetCategoryFileListV2` | 6 items |
  | `Channel/GetDialType` | full type list |
  | `Weather/SearchCity` | **RC=1 Failed** |

  So the server rejects this one endpoint: retired, or it wants a field we do not
  send (our body is `Command/Token/UserId/DeviceId/KeyWord`). **Do not guess at
  field names** — the next step is a capture of the official app issuing a city
  search, or dropping the feature. The GUI already surfaces the failure with its
  reason, and `hw_verify` carries it as an XFAIL canary that will report XPASS if
  the server ever starts answering.

- **The device does not always reconnect after a daemon restart.** Seen
  repeatedly on 2026-09-07: `scan` times out while `connect` with the saved
  identifier succeeds immediately. Unexplained, and a nuisance for any hardware
  round. Nothing is known about whether it affects normal use, where the daemon
  is not being restarted every few minutes.

Running the packet:

    python3 scripts/hw_verify.py --self-test        # calibrate first
    python3 scripts/hw_verify.py --out report.json

`album_art` needs something PLAYING — with no track the music job has nothing to
push, and a dark panel then means "nothing playing", not "broken". Rebuilding the
daemon between runs: use `scripts/install_local.sh`, which refuses to install
over a running bundle and proves the daemon that comes back is the one it wrote.

---

## Native Rust daemon (`divoomd/`) — DONE

**Goal: ACHIEVED.** The Python daemon backend was deprecated in favor of
`divoomd` (Rust, built on `btleplug` + `tokio` + `serde`) at 100% socket +
hardware parity (2026-06-29). Python daemon server archived 2026-07-13 (13
server-side modules archived, then removed from the tree in R66, client-side infra stays
active in `divoom_client/` (renamed from `divoom_daemon/` in R66) —
`daemon_client.py`, `daemon_protocol.py`,
`macos_notifications.py`). Full device parity (54 → 0 gaps), cloud decode,
hardware-verified on Pixoo/Timoo/Ditoo/Tivoo Max. Menubar is a standalone Rust
agent (`divoom-menubar/`); the GUI stays the Python pywebview UI
(the native-egui-UI effort was explored and retired). `cargo test` is green on
both feature matrices (291 workspace tests at v0.28.3).

Key: `divoomd` is now the **sole shipping daemon** — no `DIVOOM_USE_RUST_DAEMON`
opt-out. The archived server and its 469 tests were removed from the tree in
R66 (2026-08-17); recover from git history if ever needed.

## Architecture summary

- **UI**: Python pywebview GUI (unchanged, 9k-LOC static `web_ui/` frontend).
- **Daemon**: Rust `divoomd` (unix-socket NDJSON, sole BLE/LAN owner).
- **Menubar**: Rust `divoom-menubar` (standalone agent, replaces pyobjc).
- **Encoders**: C `libdivoom` (LANCZOS downsampler, reused via FFI).
- **Transport**: BLE (CoreBluetooth via `btleplug`) + LAN (HTTP to device) + Cloud (HTTP to Divoom).

## Planning docs by round

All round plans (R3 onward) and superseded workstream plans are pruned to git
history; `docs/archive/` no longer exists at all. This ROADMAP is the one
forward-looking document, and CHANGELOG is the record of what shipped.

Recover a pruned plan with
`git log --diff-filter=D -- 'docs/**/PLANNING_*'`.



