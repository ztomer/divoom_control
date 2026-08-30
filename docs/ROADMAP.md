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

### R69 plan — what can be built without the user in the loop

_Written 2026-08-30. Everything still open at the end of R68 was blocked on
hardware or on someone watching a matrix. That is a real constraint on
CONFIRMING a render; it is not a constraint on WRITING the thing. The work below
is ordered so each phase is independently shippable, and each ends in a state the
user can exercise whenever they feel like it and report back._

**The standing division of labour.** Code, tests and gates are ours. "Does the
overlay actually scroll on a 32×32 matrix" is the user's, and no amount of green
suite substitutes for it (v0.28.1 is the standing proof: 2961 tests, five green
CI jobs, and a daemon-killing crash that launching the app found in twenty
minutes). So phases 2 and 3 land the plumbing and say plainly, in the UI, that
the render is unconfirmed — rather than either blocking on hardware or pretending
the feature is verified.

#### Step ledger — the resumable state

Each step is one commit. **Update the status column in the same commit as the
step**, so this table and the git history cannot drift: a session that resumes
here reads the first non-DONE row and starts there, and that only works if the
table is written by the step rather than by a tidy-up pass afterwards.

| Step | What | Status |
|------|------|--------|
| P1.1 | Every exit from `_IsolatedStack.__init__` goes through `close()` | DONE |
| P1.2 | Socket path keyed on per-stack identity, not the pytest PID | DONE |
| P1.3 | Regression test: no surviving PIDs on each failure path | DONE |
| P1.4 | Sweep the sibling harnesses for the same shape | DONE |
| P2.1 | Audit the five LAN commands' arg + reply shapes against the daemon | TODO |
| P2.2 | GUI API methods forwarding to the daemon (client, never a 2nd impl) | TODO |
| P2.3 | Voice/SendText UI + e2e | TODO |
| P2.4 | Danmaku UI (send text, random face) + e2e | TODO |
| P2.5 | 5-LCD UI, gated on the negotiated capability + e2e | TODO |
| P3.1 | `search_weather_city` UI + e2e | TODO |
| P4.1 | Raise the Rust coverage floor off 29%, in steps | TODO |

#### Phase 1 — the e2e harness leaks the processes it spawns

Found while auditing on 2026-08-30: **ten orphaned processes** from earlier
sessions — four `divoomd` and six `e2e_gui_bridge.py`, some days old, four of
them sharing one socket path.

Two defects, and the second is why the first was survivable long enough to pile
up:

* `_IsolatedStack.__init__` has three failure paths and only one cleans up.
  `_assert_daemon_is_current` correctly passes `on_mismatch=self.close`, but
  `_wait_for_socket` calls `pytest.fail` with the daemon still running, and
  `_wait_for_http` kills the bridge and leaves the daemon. Raising from a
  constructor means the fixture never receives the object, so its
  `finally: stack.close()` never runs — the teardown is bypassed precisely when
  something has already gone wrong. This is the bypassed-funnel class: every
  exit from `__init__` must go through `close()`, structurally, not by
  remembering to.
* the socket path is keyed on `os.getpid()` — the *pytest process* PID, which is
  constant for the whole run. Every stack in that process therefore shares one
  path, so a single leaked daemon makes the next test collide with it. Key on
  per-stack identity instead.

Acceptance: a test that spawns a stack, forces each failure path in turn, and
asserts no surviving PIDs. Prove it red first by reverting one cleanup.

#### Phase 2 — GUI-wire the four backend-only LAN clusters

All five commands exist in `divoomd/src/device_call/lan.rs` and are reachable
over the socket today. None has any GUI surface — confirmed by grep, no hit for
any of them anywhere in `divoom_gui/`:

| Command | Cluster |
|---|---|
| `lan.send_voice_text` | Voice/SendText |
| `lan.send_danmaku_text`, `lan.danmaku_random_face` | Danmaku overlay |
| `lan.set_5lcd_channel_type`, `lan.set_5lcd_whole_clock_id` | 5-LCD channel extras |

Each is the same shape and can be done independently: a `divoom_gui` API method
that forwards to the daemon (a client, never a second implementation — R67/C2),
a control in the panel it belongs to, and a camoufox e2e test driving it through
the real bridge.

Two things to get right rather than discover later:

* **The 5-LCD controls must not appear on devices that have no 5-LCD.** Gate on
  the capability the daemon already negotiates (R67), not on a device-name
  match.
* **Say the render is unconfirmed, in the UI.** These four shipped as
  backend-only precisely because nobody has watched them draw. A control that
  silently does nothing on the user's hardware is worse than one that says it is
  unverified — honest placeholders, and it tells the user exactly what to report
  back on.

#### Phase 3 — `search_weather_city`

Implemented in `divoomd/src/cloud_category.rs`, wired to the `search_weather_city`
RPC, and unreachable from the GUI. Weather currently uses the system location,
which is the right default and should stay the default; this is the manual
override for when it is wrong. Small enough to fold into phase 2 if it lands
first.

#### Phase 4 — raise the Rust coverage floor

`scripts/rust_coverage.sh` pins divoomd at **29%**, measured 2026-08-25 when no
floor existed at all. 29% is a ratchet against regression, not a standard — the
Python side holds 95%. Raise it in steps, each step closing pure-logic gaps
first (seam-and-cover), and never by loosening what is measured.

#### Explicitly NOT in this plan

* **`Cloud/ToDevice`** — semantics unconfirmed and no live caller to infer them
  from. Implementing it blind would be guessing at a wire format, which is the
  one thing this project has consistently refused to do.
* **`pic_scan_ctrl` 0x35, sysmon-on-a-matrix, the R12 visual pass** — these are
  not unbuilt, they are unwatched. There is no code to write.

- **Ambient preview tiles** were listed here as static CSS colour blocks. They
  were not: `0869425` had already replaced them with the picked colour for Plain
  and an honest "drawn by the device" placeholder for the four modes the device
  generates from a palette we do not have. This entry was stale from the moment
  it was written — the same commit shipped the fix and left the item open.
- **sysmon preview** — CLOSED (R68). The GUI is now a client: the `sysmon` RPC
  returns the stats and the exact frame `live_jobs/render.rs` would push, and
  the tile and the device draw the same bytes. This was the last widget the GUI
  still rendered itself.

### camoufox pin raised to latest — SHIPPED (R68)

CI pins the browser BUILD (`camoufox set official/stable/152.0.4-beta.29`, the
current channel latest) with the pip package at 0.5.5. The pin stays because
"latest" is a moving target: it is what makes a red run mean a code change, and
`tools/check_camoufox_installed.py` verifies it rather than trusting `fetch`'s
exit code.

From beta.29 page scripting runs in an isolated world. The suite reaches the
main world explicitly through `tests/support/browser.py` — `eval_js` (the `mw:`
prefix plus `main_world_eval=True`), `wait_js` (polling, because
`wait_for_function` has NO main-world form), and `add_init_js` (a `<script>`
element appended from the isolated world, because `add_init_script` has none
either). The deferral note here predicted only the first of those three.

Rationale, probe results and the reasoning behind each live in that module.

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

All round plans (R3 onward) and superseded workstream plans are pruned to git
history; `docs/archive/` no longer exists at all. This ROADMAP is the one
forward-looking document, and CHANGELOG is the record of what shipped.

Recover a pruned plan with
`git log --diff-filter=D -- 'docs/**/PLANNING_*'`.



