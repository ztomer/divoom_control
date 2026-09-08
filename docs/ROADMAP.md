# Roadmap — divoom-control

Consolidated view of shipped rounds, current state, and future work.
Per-round plans are pruned to git history once shipped; this file is the
forward-looking one. Recover a round plan with
`git log --diff-filter=D -- 'docs/PLANNING_*'`.

---

## Shipped

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

### OPEN — expose the custom-image surface over MCP, so any app can draw on the panels

_Raised 2026-09-07. The intent: every app the user runs should be able to put
its own information on a Divoom panel, with the daemon owning the device._

**It makes sense, and most of the machinery exists.** MCP already exposes
`show_image` and `push_animation`; `render_widget` already composes frames;
`image_proc::process_image_bytes` already sniffs the container (macOS reports
`image/jpeg` for TIFF bytes, so the declared MIME may never be trusted) and
scales NEAREST. What is missing is everything AROUND the pixels.

The three things named in the request, and where they already live:

- **Relative positions** — `wall.rs` already has `DeviceSlot { mac, x, y, size,
  width, height }` and `DivoomWall { total_width, total_height, min_x, min_y,
  grid_unit_size, is_free_form }`. This is internal; it needs to be QUERYABLE,
  as metadata the caller reads and reasons about — see item 6 on why the daemon
  must not turn it into an implicit composition.
- **Available image size** — per device, not global. `get_capabilities` exists
  and should carry the panel size and device class rather than a caller
  assuming 16x16.
- **Whether to resize** — a policy the caller states (`fit` / `fill` / `none`,
  and reject-vs-scale when the image does not match), because the daemon
  scaling silently is how a caller ships a smeared panel and never learns.

**What the request does not yet cover, and needs:**

1. **Arbitration.** The daemon's live jobs already overwrite each other — the
   hardware harness has to call `live_jobs_stop_for` between checks or album art
   bleeds into the next widget. Add N external apps and "who owns this panel"
   becomes the whole problem. There is a seam already: `exclusive_start` /
   `exclusive_end` with a token. Needs a lease model with an owner, a priority,
   and a defined loser.
2. **A lease EXPIRY, and what the panel shows when a client dies.** Today the
   last frame stays lit forever; that is exactly the "still seeing album art"
   symptom from this round. A crashed app must not own a panel indefinitely.
3. **Rate limiting by conflation, not queueing.** BLE is slow and two apps at
   10fps will saturate it. Keep the LATEST frame per device and drop the
   intermediates — the same conclusion the status fan-out reached (a lagging
   consumer wants the CURRENT truth, not a backlog).
4. **Authentication is a DECISION, not a default.** R72 found an
   unauthenticated control surface handing every GUI API method to any local
   process. "Any app can draw on the panel" is that surface again, deliberately.
   Whether it is unauthenticated, token-gated, or allowlisted must be chosen and
   written down, not inherited.
5. **Honest failure.** A push to a disconnected device must say so. The device
   is frequently absent and a silent success would leave callers rendering into
   nothing.
6. **Targeting is the caller's choice, and the virtual wall is NOT the
   default.** _(Settled 2026-09-07.)_ A caller addresses **one screen, several,
   or all of them**, and picks. The geometry and per-screen size are exposed as
   DESCRIPTIVE metadata — here is what exists, here is where each one sits
   relative to the others, here is how big each is — so a caller that wants to
   spread content across screens can compute that itself.

   The daemon does **not** slice a single image across the wall by default, and
   an external caller does not inherit the wall layout the GUI happens to have
   configured. Composite-canvas mode, if it is ever built, is an explicit opt-in
   and is out of scope for the first version: the wall is a GUI concept the user
   arranges for themselves, and silently applying it to somebody else's push
   would make the same image behave differently on two machines for reasons the
   caller cannot see.

   So "relative positions" is worth exposing as INFORMATION, not as an implicit
   composition. Broadcast-to-all is the simple case and should be one call.
7. **Text without rasterizing.** `font.rs` and the `text` widget kind already
   exist; callers will want "show this string" rather than shipping pixels.

**The shape that follows from all of the above**, as a sketch rather than a
spec: a `list_screens` returning one entry per device (id, size, position
relative to the others, connected or not, what it is currently showing), and a
push that takes a target of one id, a list of ids, or all — plus the resize
policy and the frame. Geometry in, targeting explicit, no implicit composition.

**Sequencing:** the render-the-weather-widget item above is the natural first
consumer — do it first and the custom-image path gets a real user inside the
daemon before any external app depends on it.

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



