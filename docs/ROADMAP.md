# Roadmap — divoom-control

Consolidated view of shipped rounds, current state, and future work.
Per-round plans are pruned to git history once shipped; this file is the
forward-looking one. Recover a round plan with
`git log --diff-filter=D -- 'docs/PLANNING_*'`.

---

## Shipped

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

- **Gates**: 20 steps, run by `pre-push` since R71 P0 — they used to run only
  when someone typed the command. Local and CI are kept identical on purpose.
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
- **`search_weather_city`** — implemented but not GUI-wired (weather uses system location).

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

### Deferred — all of it now needs a device

Closed entries pruned to git history (`Cloud browse cannot say WHY it is empty`,
closed by R70; `Cloud/ToDevice`, closed WONTFIX by R71 P4). What is left is
exactly the work `scripts/hw_verify.py` was written to collect:

- **~~Three UNEXPOSED API methods~~ — RESOLVED on hardware, R73 (2026-08-31).**
  Two of the three were broken; being never-called was the shared property, not
  a coincidence.
  - `set_clock_rich` — **WORKS. Wire it.** It does not draw one combined face
    as assumed: it makes the panel CYCLE separate weather / date / temperature /
    clock screens. Still the only allowlist entry left.
  - `set_temperature_channel` — **DELETED.** There is no temperature channel;
    `0x01` is LIGHTING (this repo's own `Channel::Lighting`). The payload put
    `temp_type` in the red byte, shifting the colour: white rendered cyan, red
    rendered bright green, both predicted from the layout before the test and
    both confirmed on the panel. `docs/CHANNEL_ARCHITECTURE.md` had recorded
    this exact cyan screen years earlier and explained it away as "a
    device-state issue... the APK is ground truth". Doc corrected.
  - `set_timeplan` — **DELETED.** Four defects: `index` accepted and silently
    discarded (the 0x56 packet carries no index), `channel` written into the
    `mode` byte (no channel field exists), `type` hardcoded to 0 = Animation
    with an empty animation, and `week=0` meaning no days. Never fired on
    hardware. The daemon primitives 0x56/0x57 are faithful ports of the
    reference and were kept.

  **Class:** *a method whose parameters do not correspond to the fields of the
  packet it sends.* Both instances were reachable-but-uncalled code.

- **~~`sync_time` on hardware~~ — DONE, R73.** The device clock moved
  18:41 -> 21:42 on command. The Python path R72 replaced had been swallowing
  an `AttributeError` into a silent `False`.

- **R12 visual pass** — album cover, custom art, weather on a real device, at
  real scale, light and dark surroundings.
- **`pic_scan_ctrl` 0x35** — accepted by the BLE stack since 2026-07-13 with no
  visual confirmation. If the packet shows no observable effect, that IS the
  finding: mark it unsupported rather than ship it as working.
- **`search_weather_city` — the success path is DISPROVEN, not just unproven
  (R73).** Run against the real, logged-in account it returns
  `Weather/SearchCity failed (RC=1): Failed` for every keyword tried.

  This is no longer the "we only ever saw the RC=10 guest branch" problem. The
  session is valid and the transport is fine, isolated by elimination on the
  same daemon, same credentials, same HTTP client, in the same minute:

  | Call | URL shape | Result |
  |---|---|---|
  | `GetCategoryFileListV2` | `{BASE}/GetCategoryFileListV2` | 6 items |
  | `Channel/GetDialType` | `{BASE}/Channel/GetDialType` | full type list |
  | `Weather/SearchCity` | `{BASE}/Weather/SearchCity` | **RC=1 Failed** |

  So the server rejects this one endpoint. Either it has been retired, or it
  wants a field we do not send (our body is `Command/Token/UserId/DeviceId/
  KeyWord`). **Do not guess at field names** -- the next step is a capture of
  the official app issuing a city search, or dropping the feature. The GUI
  already surfaces the failure honestly ("no results" WITH the reason), so
  nothing is silently broken for the user meanwhile.

The remaining two need a person watching the panel:

    python3 scripts/hw_verify.py --self-test        # calibrate first
    python3 scripts/hw_verify.py --out report.json

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



