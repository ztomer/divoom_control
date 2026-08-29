# Roadmap — divoom-control

Consolidated view of shipped rounds, current state, and future work.
See `docs/PLANNING_ROUND*.md` for detailed scope per round.

---

## Shipped

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

Suite: Rust 63+ passed / Python 3197 passed / 97 skipped (see `CHANGELOG.md` + CI).

---

## Current debt & quality

- **500-LOC rule**: fully enforced, ALLOWLIST empty (R23).
- **Font**: APK bitmap font extracted (ASCII + CJK via `from_apk_asset()`), half-size variant with majority-rule downsampling.
- **Tests**: hardware tests gated/skip by default; 60 native-downscaler parity tests; alarms editor JS guard; 18 E2E mock-device.
- **C module**: `libdivoom` (LANCZOS downsampler) compiled via `build_libdivoom.sh`; normalize-then-quantize kernel matches PIL byte-for-byte (60/60 parity tests).

---

## Open workstreams

### Near-term (next round)

**Feishin — RESOLVED 2026-08-29. Root cause found; no further work needed here.**

Feishin never appeared in now-playing because **its own `mediaSession` setting
is OFF** (`~/Library/Application Support/Feishin/config.json` reads
`"mediaSession": false`). With it off, Feishin does not register as a macOS Now
Playing client at all, so MediaRemote cannot see it however loudly it plays —
and the Subsonic fallback could not see it either, because `getNowPlaying` asks
the SERVER, which depends on scrobble pings.

This was settled by enumerating the Now Playing client registry rather than by
asking the user to quit apps: the registry listed Kaset twice (the app and its
WebKit GPU helper) and Feishin not at all.

**The fix is one setting in Feishin, not code here.** Turning Media Session on
gives MediaRemote the track AND the real cover-art bytes, with no credential
scraping and no dependency on the server. The daemon now says so: `players`
returns a `hint` naming the setting and where to find it.

What shipped as a result:

* `nowplaying/src/discovery.rs` + the helper's `np_players` — enumerate every
  registered Now Playing client, separating *registered* from *playing*. This
  is the fix for the reported problem that a PAUSED Kaset masked a playing
  Feishin: registration and playback are now different questions.
* The `players` daemon RPC and `DaemonClient.players()`.
* `nowplaying/src/feishin.rs` (Subsonic path) is kept as a fallback for a user
  who leaves Media Session off, but it is the WEAKER path and is documented as
  such. If Media Session becomes reliably on, this module can be deleted.

**Known limitation, deliberately not guessed around:** when SEVERAL apps are
registered, the active session cannot be attributed to one of them — the info
dictionary carries no app identity, and the APIs that would supply it
(`MRMediaRemoteGetNowPlayingApplicationDisplayName`, `...ApplicationPID`,
`MRNowPlayingClientGetParentApplicationBundleIdentifier`) either segfault or do
not exist on macOS 26.6.2. `is_playing` is reported as `null` (unknown) in that
case rather than blamed on the wrong app.

### Short-to-medium term (all shipped)

The following workstreams from earlier rounds are complete:

- **`show_clock()` overlay reorder (R60)** — realigned to APK C2() canonical format.
- **`get_*` read-back timeouts (R60)** — bounded + cached in both Python and Rust.
- **R12 visual pass (2026-07-14)** — Gemini design critique, 2 real CSS fixes applied.
- **Menubar connection-feedback (v0.22.10)** — hardware-verified on real Pixoo-1.
- **Daemon-down banner / reconnect (v0.22.10)** — hardware-verified, auto-heal confirmed.
- **Inline-style → CSS-token migration batches 3-5 (v0.22.11)** — all three files completed.
- **R12 hardware verification** — user-driven (album cover, custom art, weather on real device).

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
- **`Cloud/ToDevice`** — unimplemented (unconfirmed semantics, no live caller).
- **`search_weather_city`** — implemented but not GUI-wired (weather uses system location).

### WiFi/LAN command completeness — 45 total, all implemented

Counted from `HttpCommand.java`'s `DeviceAndServerCmd` (43) + `ForceDeviceHttp` (2).
All 4 clusters implemented:
1. **Photo album management** (DONE, live, GUI-wired).
2. **LAN-getter completeness** (DONE, 8 read-back counterparts).
3. **Channel extras + Voice/SendText** (DONE, backend only, NOT GUI-wired — needs hardware).
4. **Danmaku scrolling overlay** (DONE, backend only, NOT GUI-wired — unconfirmed render).

Bonus fix: device-selector "not in range" badge now counts consecutive scan misses
(downgrades after 2), not a one-shot startup flag. 5 new e2e tests.

### GUI e2e suite migrated to camoufox — SHIPPED (R66, v0.23.0)

All 15 modules moved off Playwright/Chromium behind one seam
(`tests/support/browser.py`); no `p.chromium` references remain in `tests/`.
CI installs camoufox instead of chromium.

The guard defect that motivated this is fixed and pinned by
`tests/test_e2e_browser_guard.py`: `pytest.importorskip` only proved the Python
*module* imported, so a missing browser **binary** produced 69 failures that
read as real regressions. `require_browser()` now probes the binary.

Acceptance met, with one honest note on how: the criterion said "proven by
deleting the browser". It is instead proven by driving camoufox's own
not-installed path (`get_active_path() -> None`, which makes `installed_verstr()`
raise `CamoufoxNotInstalled`) rather than deleting a ~150 MB install per run.
That is stronger than the first attempt, which stubbed `installed_verstr` to
return `""` — a value the library never actually produces, so it proved our
branch worked without proving reality reaches it. The suite also asserts the
guard does NOT over-skip, since a guard that always skipped would silently
disable all 15 suites while looking green.

Two latent test races surfaced during the move (both waited on a proxy DOM
signal and asserted on a different one — a Chromium timing coincidence) and were
fixed as a class.

### Deferred

- **`pic_scan_ctrl` 0x35** — partially resolved (2026-07-13, real hardware).
  Accepted without error by BLE stack; no visual confirmation (no camera).
  See `divoom_lib/display/drawing.py` / `divoomd/src/device_call/drawing.rs`.
- **`Cloud/ToDevice`** — unimplemented, unconfirmed semantics.
- **R12 hardware verification** — user-driven (album cover, custom art, weather on real device).

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
(the native-egui-UI effort was explored and retired). `cargo test` 63/63 both
feature matrices.

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

Historical round plans (R3–R61) and superseded workstream plans were pruned to
git history — `docs/archive/rounds/` and `docs/archive/superseded/` no longer
exist. Recover any of them with `git log --diff-filter=D -- 'docs/**/PLANNING_*'`.
`PLANNING_ROUND62.md` and later shipped rounds also archived there.



