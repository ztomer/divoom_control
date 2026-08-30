# Roadmap — divoom-control

Consolidated view of shipped rounds, current state, and future work.
Per-round plans are pruned to git history once shipped; this file is the
forward-looking one. Recover a round plan with
`git log --diff-filter=D -- 'docs/PLANNING_*'`.

---

## Shipped

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

- **500-LOC rule**: fully enforced, ALLOWLIST empty (R23).
- **Font**: APK bitmap font extracted (ASCII + CJK via `from_apk_asset()`), half-size variant with majority-rule downsampling.
- **Tests**: hardware tests gated/skip by default; 60 native-downscaler parity tests; alarms editor JS guard; 18 E2E mock-device.
- **C module**: `libdivoom` (LANCZOS downsampler) compiled via `build_libdivoom.sh`; normalize-then-quantize kernel matches PIL byte-for-byte (60/60 parity tests).

---

## Open workstreams

### Near-term (next round)

_Actual state as of 2026-08-30, after R67._

**The Python layer is OBSOLETE and kept for REFERENCE ONLY.** `divoomd` (Rust)
is the shipping implementation; `divoom_lib/` is the protocol ground truth the
port was derived from, not a live second path. This matters for how findings are
read: "X exists in both Python and Rust" is NOT automatically drift to unify —
the Rust one is the product and the Python one is documentation. Two things are
still true and not contradicted by it:

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

### Earlier shipped workstreams — pruned to git history

The camoufox pin raised to latest (R68), the GUI e2e migration off Playwright
(R66), and the R60-R61 short-to-medium-term list were all complete and were
being carried here as narrative. CHANGELOG is the durable record of what
shipped; this file is for what has not. Recover any of them with
`git log -p -- docs/ROADMAP.md`.

### R69 — SHIPPED in v0.28.3 (2026-08-30)

Four phases, all done; the plan itself is pruned to git history per the
one-forward-looking-doc rule. What it produced and the traps it hit are in the
CHANGELOG's v0.28.3 stanza — including the two the plan did NOT anticipate: an
audit that stopped three of its own steps from being built, and a green e2e
suite describing a panel that was visibly open on screen.

Recover the plan and its step ledger with
`git log -p -- docs/ROADMAP.md` (search for "R69 plan").

### R70 — GUI/daemon boundary audit (2026-08-30, findings OPEN)

**The question asked:** is there anything left in the Python GUI that should
live in the daemon? **Answer: yes, twelve things.** R67/C2 fixed this class for
now-playing, weather and sysmon and stopped there; the audit swept the rest of
`divoom_gui/` for the same shape. Verified against a LIVE daemon
(`/tmp/divoom.sock`, the installed v0.28.3 bundle), not read off the source.

The rule this measures against is already written above: _where the GUI
EXECUTES Python that duplicates a daemon job, that IS a real defect._ Python
being reference-only does not make a GUI-side second implementation harmless —
it makes it a second implementation of documentation.

**Live duplicates — the daemon already answers, the GUI does the work anyway:**

| # | GUI code | Daemon command that already exists | Evidence |
|---|----------|-----------------------------------|----------|
| 1 | `clock_faces.py`, `playlists.py`, `aid_sleep.py`, `photo_albums.py`, `weather_city.py` build a Python `CloudClient` in-process | `get_dial_types`, `get_dial_list`, `get_my_playlists`, `get_playlist_images`, `get_aid_sleep_list`, `get_my_aid_sleep_list`, `get_photo_albums`, `search_weather_city` — all wired at `dispatch.rs:282-295` | `get_dial_types` over the socket returned 8+ real categories |
| 2 | `gallery_hot_api.get_animated_preview` (CDN download + magic-43 decode) | `get_animated_preview`, `dispatch.rs:71` — whose own comment at `sync_artwork.rs:68` says it is "parity with the Python GUI's `gallery_hot_api.get_animated_preview`" | returned a valid 2.9 KB `data:image/gif;base64` for a real `file_id` |
| 3 | `gallery_sync.py:150-194` hand-rolls the POST to `appin.divoom-gz.com/GetCategoryFileListV2` — own credential cache, own `config.ini` read, own RC 9/10/11 retry, own okhttp UA; `gallery_download.py` downloads from `fin.divoom-gz.com` and decodes | `fetch_gallery`, `get_category_file_list`, `get_credentials`, `get_cached_credentials`; decode in `art_codec.rs`/`media.rs` | source |
| 4 | `hot_update_preview` → Python `fetch_hot_manifest` | `art_hot.rs:100 fetch_hot_manifest`, same `HOT_FILE_BASE` | source |
| 5 | `media_sync.py:176/193` fetches Yahoo + `render_stock_ticker_frame()` draws with PIL | `live_jobs/render.rs:266 render_stock()` off the same Yahoo endpoint (`mod.rs:226`) | source |
| 6 | `media_sync.py:84-106` album-art preview resizes `Image.LANCZOS` | music job pushes via `image_proc::process_image_bytes` → `FilterType::Nearest` | source |
| 7 | `mcp_control.py:118` spawns `[sys.executable, "-m", "divoom_lib.cli", "mcp-server"]` | `divoomd mcp` (`mcp.rs`, a documented port of the Python server) | bundled `divoomd mcp` served `tools/list` = 13 tools |

**Two of these are worse than redundancy.**

**#6 is a docstring that is false about its own function.** It states "Uses the
same renderer path the device frame comes from, so the card and the panel
cannot drift (house rule: previews mirror live state through the shared
renderer, never a parallel pipeline)" — and then resizes LANCZOS while the
device gets NEAREST, which `image_proc.rs` documents as deliberate ("keeps
pixel art crisp"). The preview is smoothed, the matrix is not. The comment
asserts exactly the invariant the code breaks.

**#7 is broken in the bundle, not merely duplicated.** `mcp_control.py` has no
`sys.frozen` branch, so in the `.app` `sys.executable` is
`Contents/MacOS/Divoom` and `-m divoom_lib.cli mcp-server` is handed to
`gui_main.main()`, which uses `parse_known_args()` — unknown args silently
ignored — and then exits on the single-instance guard. The MCP card would show
a server that starts and immediately dies. `divoomd` is bundled two directories
away and answers today. (Read from the code path; not yet reproduced in the
bundle — do that first.)

**#1 also closes a Deferred item below for free.** "Cloud browse cannot say WHY
it is empty" is not a missing feature — the daemon already answers
`Photo/GetAlbumList failed (RC=3): Request data is incomplete` while the GUI's
`except → []` renders "nothing found". The reason exists; the GUI throws it
away by not asking. Routing the panels through the daemon IS the fix for both.

**Dead weight that should not be in the GUI at all:**

8. `gui_main.py:33-35` — `Divoom`, `DivoomWall`, `BleakScanner` imported, none
   used. `bleak` is not a cosmetic import: it is the BLE stack, loaded into the
   one process that must never own BLE, and its TCC surface with it.
9. `audio_visualizer.py` (150 LOC, pyaudio + numpy + a capture thread) plus
   `toggle_audio_visualizer`/`get_audio_levels` — no JS calls any of them. Dead,
   and it drags pyaudio and numpy into the bundle.
10. `api/widgets.py:97-118` — unreachable code after `get_weather` returns, left
    behind by the R67/C2 migration.
11. `api/widgets.py:20-35 push_weather` — GUI-side weather fetch, raw `0x45`
    channel switch, `Weather(d).set()`. No JS caller; a test at
    `test_widgets_weather.py:219` even asserts the JS handler was removed. The
    pre-R67 weather path, alive only because its own tests still call it.
12. `media_sync.py:267 trigger_notification` — no JS caller; renders its own
    frame and sends raw `0x60` with a hardcoded app-code/colour map duplicating
    `notification_routing.rs`.

**What is already correct** (so the list is not read as "the GUI is all wrong"):
now-playing, the weather card, sysmon, the wall (`DaemonDeviceProxy`),
`sync_artwork`, `custom_art_push`, `hot_update`/`hot_update_progress`, and
scan/connect/`device_call` are all proper daemon clients.
`divoom_gui/sysmon_widget.py` is the reference for the shape a fix should take.

**Borderline, deliberately NOT on the list:** config read/write (weather city,
lifecycle, presets, `tickers.json`) is GUI preference storage and belongs where
it is; constants imported from `divoom_lib.models` are reference data, not a
second implementation. `api/lighting.py:_render_text_png` duplicates
`render.rs`'s `BitmapFont` over the same font binary, but no daemon command
exists to call — same class as #5, without a seam yet.

**The missing seam, which is why this accumulated.** `divoom_client/
daemon_protocol.py` has NO wrapper for a single one of the twelve-plus cloud
commands. Every panel that needed one found it easier to import `CloudClient`
than to add a method. Fix the class: add the wrappers first, then route the
panels, then delete the Python paths — not one panel at a time.

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

### Deferred

- **Cloud browse cannot say WHY it is empty** (found 2026-08-30 exercising the
  real backend). `search_weather_city`, `get_dial_list`, `get_my_playlists`,
  `get_aid_sleep_list` and the photo-album browse all catch their exception and
  return `[]`, so every panel shows "nothing found" whether the result is
  genuinely empty, the cloud is unreachable, or the account is unauthenticated.
  A failed state must say why. **R70 found the reason already exists** — the
  daemon returns it and the GUI never asks (see R70 #1); this item is subsumed
  by that fix, not separate work. Fix as a CLASS in the shared shape — five
  features and their tests — not one panel at a time.
- **`search_weather_city` success path unverified.** The pre-release check ran
  under a throwaway HOME, so it exercised the no-credentials branch
  (`UserNewGuest RC=10`) and proved only the error path. Needs one manual search
  on a configured account.

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



