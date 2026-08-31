# Roadmap — divoom-control

Consolidated view of shipped rounds, current state, and future work.
Per-round plans are pruned to git history once shipped; this file is the
forward-looking one. Recover a round plan with
`git log --diff-filter=D -- 'docs/PLANNING_*'`.

---

## Shipped

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

### R71 plan — close every open item, six phases

**What this round is for.** After v0.29.0 nothing is half-built, but eight
things are half-*decided*: 20 API methods nobody has ruled on, four hardware
checks nobody has watched, a LAN cluster with no device, a cloud endpoint with
no semantics, and a coverage floor whose only enforcement is somebody
remembering to type a command. This round converts every one of them into
shipped, gated-with-a-named-blocker, or closed-with-a-reason. **No item is
allowed to survive the round in the state "unreviewed" or "unwatched".**

**Completion criterion, mechanical again (the R70 discipline).** Two ratchets,
both machine-checked, not judged:

1. `check_gui_api_reachable.py`'s allowlist reaches **EMPTY**, and the reason
   string `unreviewed` becomes ILLEGAL — the gate fails on it. Today's honest
   placeholder must not survive as tomorrow's rubber stamp.
2. Every entry under "Deferred" and "Open workstreams" in this file is either
   deleted (done) or rewritten to name its BLOCKER and the capability gate that
   makes it honest to the user. An item with no blocker and no owner is not
   deferred, it is forgotten.

**Order is forced, and P0 is not negotiable.** The keystone finding of this
plan was found while writing it: **`tools/gate.sh --full` runs four structural
checks — emoji, conflict markers, file length, disk hygiene — and nothing
else.** The rust and python layers are commented out, so `pre-push` runs no
clippy, no tests, neither coverage floor, and none of the nine
`tools/check_*.py` gates. The 17-step list in `.gatesrc` and both coverage
floors execute ONLY when a human types `./scripts/ci_local.sh`. That is house
rule #3 violated at the top of the stack, and R70's own process failure is the
receipt: *"CI was red from P3.3 to P6.3 and I did not look — I ran the gates I
remembered instead of `scripts/ci_local.sh`."* The gate did not fail him; it was
never wired to run. Every later phase in this plan reports "done" through those
gates, so fixing them first is the difference between a round that is verified
and a round that merely feels verified.

**P0 — the local gate becomes a gate.**

The decision "local CI is the way to go" is adopted, and adopting it means
making it structural. A local gate that is stricter than CI is the safe
direction; a local gate nobody runs is not a direction at all.

- **P0.1** `tools/repo_gates.sh` → `./scripts/ci_local.sh`, and uncomment
  layer 3 in `tools/gate.sh --full`. `pre-push` then runs the real list.
- **P0.2** Prove it bites, once per CLASS of gate, each seen RED (rule #2): a
  clippy error, a failing Rust test, a failing Python test, a coverage floor
  breach, and one of the nine `check_*.py`. Five sabotages, five reds, then a
  clean tree pushes. A gate suite proven only in the green direction is
  `calibrate-the-instrument`'s exact failure.
- **P0.3** Measure the wall-clock and **state it out loud**. If a full run is
  too slow to sit in front of every push, the escape hatch is an explicit
  env var that PRINTS what it skipped and why. Never a silent fast path —
  that is how the current hole was dug.
- **P0.4** Settle the CI-coverage question in the chosen direction: **no GitHub
  macOS coverage job.** Rewrite `.gatesrc`'s comment from "adding the CI job is
  an open question" to the decision and its reason (`nowplaying` is macOS-only,
  so a Linux job would measure a different denominator and enforce a floor that
  does not match). Delete the item from "Open threads". A decision recorded as
  a decision stops being re-litigated every round.
- **P0.5** ~~Reap stray test daemons; the harness leaks the processes it
  starts.~~ **The premise was WRONG, and the investigation is the deliverable.**
  The stray was real and is now reaped, but the harness did not create it:
  `IsolatedStack` gives every stack its own
  `/tmp/divoomd_e2e_<pid>_<seq>_<uuid>.sock`, kills only its own PIDs, and
  calls `close()` even on a half-built object. The stray was on
  `/tmp/divoom_r70_text.sock`, a path that appears **nowhere in the tree** —
  started by hand from the repo root during R70's P3.3 text work. The
  `divoom_cov_*` fixed paths that looked like a collision risk never spawn a
  daemon; they only construct a `DaemonClient`.
  **No gate was added, deliberately.** The obvious ratchet — fail if a
  `divoomd` is alive on a `/tmp/divoom_*` socket — would fire on the project's
  own documented BLE-debug workflow, which runs a standalone daemon on
  `/tmp/divoom.sock` on purpose. A gate that reddens on legitimate work trains
  people to ignore gates, and this class is a one-off human artifact rather
  than something the code does. Recording why no gate is worth more than a bad
  one.

**P1 — the 20 unreviewed methods, to an EMPTY allowlist.**

- **P1.0 (harness before the bug).** The gate asks "does JS call this", which
  cannot distinguish *reachable from nowhere* from *reachable only from
  Python* — and those need opposite fixes. Teach it three buckets:
  JS-reachable, Python-only, unreachable. **Careful: Python-only is not an
  exemption.** `DivoomGuiAPI` is the pywebview bridge surface; a method only
  Python calls does not belong on it and should move to a plain module. The
  Python bucket is a work marker, not a pass. Prove-red in both directions.
- **P1.1 Symmetric pairs** — `save_preset_file`/`load_preset_file`,
  `export_settings_to_path`/`import_settings_from_path`. Two matched pairs with
  no JS caller read like a file-dialog surface that was never wired. **Check
  git history for a caller that once existed before deciding** (`port-parity`:
  the removed code is part of the spec). Wire or delete, no third option.
- **P1.2 Superseded status-getters** — `hot_update_status` vs
  `hot_update_progress`, `is_mcp_server_running`, `is_notification_listener_running`.
  Prove the surviving sibling actually covers the caller before deleting; the
  trap is deleting the one the UI polls and keeping the one it does not.
- **P1.3 Device commands** — `set_clock_rich`, `set_temperature_channel`,
  `set_timeplan`, `display_custom_art`, `custom_art_query_page`,
  `apply_system_stats`. These are FEATURES, not plumbing, and the wire-or-delete
  call cannot be made from source: it needs the device. Feeds P2.5, and is the
  one cluster in P1 that blocks on the hardware packet.
- **P1.4 LAN pair** — `probe_lan`, `save_lan_config`. Resolved by P3, not here.
- **P1.5 Remainder** — `get_scoreboard_state`, `get_transport_status`,
  `live_job_stop`, `batch_sync_artwork`, `load_cached_gallery`.
- **P1.6 Delete the tests pinning whatever dies.** Every one of the 20 has
  tests — `probe_lan` has 20, `set_clock_rich` 19, `load_preset_file` 14. That
  is not coverage, it is Hole D: the tests are WHY these survived unnoticed.
  A test pinning a dead method is part of the defect (rule #8). Re-baseline the
  floor and **state the number**.
- **P1.7 Allowlist EMPTY**, and `unreviewed` added to a forbidden-reasons list
  the gate rejects. Enforced, not asserted.

**P2 — the hardware packet: built here, run by the user, non-blocking.**

Hardware is available (Ditoo, Tivoo-Max, Timoo, Pixoo-1 — all BLE). The user
runs the packet when they want and reports; nothing in this plan waits on it
except P1.3 and P2.5.

- **P2.0** `scripts/hw_verify.py` — drives each check against a **user-started**
  daemon over the socket, prompts for a LOOK at the device, records verdict and
  notes to a report file. It must **refuse to spawn its own daemon**: a
  shell-launched daemon has no Bluetooth TCC grant and dies on the first scan
  with SIGABRT and an empty stderr, which reads as a product crash and is not
  one. Assert a daemon is already reachable, or stop with that explanation.
- **P2.1** Prove the packet can report FAILURE before trusting a pass
  (`calibrate-the-instrument`): point a check at a disconnected device and
  require ✗. A checklist that cannot fail is a form, not an instrument.
- **P2.2** sysmon gauges on a matrix — the RPC and the frame are verified over
  the socket; nobody has watched the gauges.
- **P2.3** R12 visual pass: album cover, custom art, weather on a real device.
  Light and dark surroundings, real scale (rule #4).
- **P2.4** `pic_scan_ctrl` 0x35. The BLE stack accepts it and no one has seen it
  do anything. **If the packet shows no observable effect, that is the finding**
  — an unobservable command gets marked unsupported rather than shipped as
  though it works (rule #9). Not another round of "accepted without error".
- **P2.5** The P1.3 device-command decisions, answered by looking at the device.
- **P2.6** `search_weather_city` on the **configured** account — the one check
  in the packet that is cloud, not BLE. The pre-release check ran under a
  throwaway HOME and proved only the `UserNewGuest RC=10` error path. Live
  Widgets → Weather → click the location line → search a city.

**P3 — LAN: an honest capability gate, not a standing open workstream.**

There is no WiFi-capable device and none is expected this round, so the LAN
HTTP cluster cannot be verified. The fix is not to keep listing it as pending
hardware — it is to make the product honest about it (rule #9).

- **P3.1** A capability probe: every LAN-requiring surface asks the device and
  says **"needs a WiFi-capable device"** — a state distinguishable from
  "failed" and from silence. Same shared shape as R70's `_cloud_list`; fix the
  CLASS, not one panel.
- **P3.2** `probe_lan` / `save_lan_config` take their verdict from this. Either
  they are the configuration path for that capability and get wired into it, or
  they are leftovers and go. This closes P1.4.
- **P3.3** 5-LCD (`Set5LcdChannelType`, `Set5LcdWholeClockId`) and
  `Voice/SendText` stop being "backend-only, needs hardware" open items and
  become documented gated capabilities naming their blocker: a Times Gate and a
  WiFi Pixoo respectively.
- **P3.4** Danmaku is already GUI-wired — confirm it sits behind the SAME gate
  rather than a private one. A second capability check is the class re-opening.

**P4 — `Cloud/ToDevice`: decide, stop carrying.**

- **P4.1** `probe-first`: one recorded live call on the configured account. The
  endpoint has been "unconfirmed semantics" for many rounds while the cost of
  finding out is a single request.
- **P4.2** Decide on that evidence — implement it, or close it WONTFIX with the
  reason written down. Either outcome removes it from this file.

**P5 — close the round.**

- **P5.1** Both ratchets checked: allowlist empty with `unreviewed` illegal, and
  no "Deferred"/"Open" entry left without a blocker or a closure reason.
- **P5.2** `scripts/gui_pov.py` plus a real-app pass over every touched panel.
  Green tests are not a shipped feature and this project has its own v0.28.1
  proof.
- **P5.3** CHANGELOG stanza, version bump, release, verified INSIDE the DMG.

**Traps, named up front.**

- **Commit before you sabotage.** A `git checkout` after a prove-red wiped an
  uncommitted fix twice in R70, once leaving a BLIND parity test in the tree for
  four phases. The project's own note warns about this and it still happened.
- **Run the whole list, not the gates you remember.** P0 exists to make this
  structural; until P0.1 lands, it is still discipline, which is to say it is
  still going to fail.
- **BLE and TCC.** The user starts the daemon; a shell-launched one dies on its
  first scan with an empty stderr. And `cargo test` rebuilds
  `target/debug/divoomd` WITH default features, so a `--no-default-features`
  build does not stay BLE-free across a test run.
- **An unwired command is often a DECISION** (R69/P2.1), and the reasons sit in
  the handler comments. Read them before undoing anything. This presumption is
  what makes P1's per-cluster investigation necessary rather than a bulk delete.
- **Deleting code moves coverage.** Say the number out loud. A floor lowered
  quietly is a floor that stops meaning anything.
- **"Accepted without error" is not verification.** It is what `pic_scan_ctrl`
  has had since 2026-07-13.

**P0.2 found a defect it was not looking for: the Python coverage floor passes
by ROUNDING, and is sitting exactly on the boundary.**

Measured on a clean tree: **89.50%** over `divoom_gui + divoom_client`, with the
floor set to 90. It passes. Verified against the installed coverage.py 7.14.1
rather than assumed -- `should_fail_under` is `round(total, precision) < fail_under`
with precision 0, so:

| total | floor | precision | result |
|-------|-------|-----------|--------|
| 89.50 | 90 | 0 (default) | **passes** |
| 89.49 | 90 | 0 | fails |
| 89.50 | 90 | 2 | fails |

So the floor this repo calls 90 is really **">= 89.5"**, and today's coverage is
89.50 -- a **0.01 point** margin. The R70 stanza that says "coverage 89% -> 90%,
floor raised to match" is describing a number the gate never actually enforced.

**This is the same class as the finding that created P0 in the first place**: a
gate that is believed to be stricter than it is. There it was a hook that never
ran the checks; here it is a threshold that rounds its way to green. Settled in
P0.4, which is where coverage policy is decided -- not left as a note, because a
recorded-but-unfixed threshold is how the first one survived.

**P0.3 measurement (2026-08-31, this machine, warm cache).**

| Run | Steps | Wall-clock |
|-----|-------|------------|
| `ci_local.sh` (full) | 18 | **9m22s** |
| `pre-push` with `DIVOOM_GATE_FAST=1` | 17 | **1m50s** |

**`py_ci.sh` is ~7.5 min of the 9m22s — roughly 80% of the gate.** Everything
else together costs under two minutes.

**The default stays FULL, and that is a deliberate trade.** Nine minutes in
front of every push is real friction, and friction is how a gate turns into
`--no-verify` — which would recreate exactly the hole P0 closed, only with the
bypass now invisible in the reflog instead of in a commented-out line. The
mitigation is NOT to make skipping easy; it is that the hatch announces itself
every single time, so a fast run can never be mistaken for a full one.

**The real lever is that the Python suite is serial, and that is a fix, not a
skip.** ~3000 tests plus 15 camoufox e2e suites run one after another. Making
them parallel would attack the cost instead of the coverage, and is the right
next move if nine minutes proves intolerable in practice. **Not attempted here,
and it is not free:** this suite spawns daemons on fixed socket paths under
`/tmp/divoom_*`, so parallel workers would collide unless each gets its own
socket namespace — the same shared-state problem `IsolatedStack` already solves
for the e2e suites. Recorded as a candidate with its known obstacle rather than
as an easy win.

### R71 test plan — the holes, and which phase closes each

R70 closed four holes (A-D). This round's items survived those, so naming the
NEW hole each phase closes is the only way to avoid adding tests of a shape
that has already been proven blind.

- **Hole E — the gate suite is not run by the hook that claims to gate.**
  `pre-push` → `tools/gate.sh --full` → four structural checks. Everything this
  repo thinks of as "the gates" is opt-in. Closed by **P0.1**, and P0.2 proves
  it by pushing five separately-sabotaged trees and watching each be refused.
- **Hole F — no instrument reports what the DEVICE shows.** Every test here
  stops at the socket: the daemon's reply is checked, the pixels are not. That
  is why sysmon, album cover and `pic_scan_ctrl` have all been "verified" and
  simultaneously unwatched. Closed by **P2**, whose output is a report from a
  human looking at hardware — and P2.1 makes it an instrument rather than a
  form by proving it can say ✗.
- **Hole G — "unavailable" and "broken" are indistinguishable.** A user with a
  BLE-only device who opens a LAN surface gets silence, exactly the shape R70
  fixed for cloud browse and did not generalize to LAN. Closed by **P3.1**,
  pinned by a test per cause and an e2e that the text reaches the screen.
- **Hole D, still open in a second population.** R70 found tests pinning dead
  code and fixed the four it had confirmed. The other 20 came with 156 tests
  between them and no caller. **P1.6** treats deleting those tests as part of
  the fix; **P1.0** makes the "Python-only" bucket visible so the next
  population is smaller.

**Step ledger** — each step updates its own row in the commit that does the
work, so the table and git history cannot disagree. A row goes DONE only once
its proof has been SEEN, and for anything testable that means seen RED first.

| Step | State | Proof required |
|------|-------|----------------|
| P0.1 pre-push runs local CI | **DONE** | `tools/repo_gates.sh` -> `ci_local.sh`; `gate.sh --full` layer 3 uncommented. `tests/test_repo_gates.py`, 7 tests, **5 sabotages each seen RED**: layer-3 line commented out, guard disabled, fast-mode announcing a skip it did not perform, `--staged` widened to layer 3, and a silent `DIVOOM_GATE_SKIP` bypass. Wiring is probed via the recursion guard, so it costs ms, not a CI run |
| P0.2 prove it bites | **DONE** | All 5 classes seen RED through the REAL `.githooks/pre-push`. Four at once in one 9m11s pass (`local_ci.sh` never stops on a failure): `check_no_allow` (3), clippy (11), Rust test (13+15), Python test (18), plus `rust_coverage` (17) as collateral -> **HOOK_EXIT=1**. Coverage floor proven separately at `DIVOOM_PY_COV_MIN=99` (3003 passed, failed on the FLOOR alone, exit 1). Clean tree accepted: exit 0 |
| P0.3 wall-clock stated | **DONE** | **full 9m22s** (18 steps, warm) / **fast 1m50s** (17 steps) on this machine, so `py_ci.sh` alone is **~7.5 min — 80% of the gate**. Default stays FULL; `DIVOOM_GATE_FAST=1` is the only hatch and announces itself. See "P0.3 measurement" below |
| P0.4 CI-coverage decided | TODO | `.gatesrc` comment states the decision; item deleted from Open threads |
| P0.5 stray daemons reaped | **DONE (premise corrected)** | Stray PID 21632 killed, production daemon on `/tmp/divoom.sock` untouched. The harness does NOT leak: `IsolatedStack` uses per-stack `divoomd_e2e_*` sockets and kills its own PIDs; the stray was hand-started on a path referenced nowhere in the tree. No gate added, on purpose — it would fire on the documented BLE-debug workflow |
| P1.0 gate sees 3 buckets | **DONE** | AST scan, delegation excluded. **4 python-only / 16 no-caller** (a naive scan said 13/7 — `probe_lan` forwarding to `self.connection.probe_lan()` counted as its own caller). 7 tests, 6 sabotages red. Also found: allowlist REASONS are unverified — `batch_sync_artwork`'s "called from Python (gallery_sync)" was a docstring hit; it has no production caller, only tests |
| P1.1 preset + settings pairs | **DONE** | The two pairs needed OPPOSITE treatment. `save_preset_file`/`load_preset_file` **deleted**: R43 added them + their buttons, R44 deleted the handlers AND buttons (no orphaned dead button), and named presets superseded them. `export_settings_to_path`/`import_settings_from_path` **kept, made private**: JS calls `*_dialog()` which delegates to them — a test seam, not dead. Allowlist 20 -> 16 |
| P1.2 status-getters | **DONE** | All three superseded, each verified against its survivor rather than assumed. `is_mcp_server_running` -> `mcp_server_status()` (dict carries `running`); `is_notification_listener_running` -> `get_notification_listener_status()` (same); `hot_update_status` -> R59's `hot_progress` daemon broadcast, which `gallery_hot.js:129` records as having replaced the 600ms poll. Allowlist 16 -> 13 |
| P1.3 device commands | **IN PROGRESS** | P1.3a done: fixed two gate false positives (JS comments credited a caller; `client.X` credited the bridge) and deleted the confirmed-dead `live_job_start`/`live_job_stop`. The six device commands still need device evidence -> P2.5. Allowlist 13 -> 12 |
| P1.4 LAN pair | TODO | closed by P3.2 |
| P1.5 remainder | TODO | each named, decided, no `unreviewed` left |
| P1.6 tests + floor rebaseline | TODO | dead tests deleted; before/after counts and coverage delta stated. **Owed: the floor was dropped 89.5 -> 89.0 as a working margin for the deletion phase and MUST be re-baselined UP to the final measured value here.** A ratchet that only goes down is not a ratchet |
| P1.7 allowlist EMPTY | TODO | 20 → 0; `unreviewed` rejected as a reason string |
| P2.0 hardware packet built | TODO | `scripts/hw_verify.py`; refuses to spawn its own daemon |
| P2.1 packet can fail | TODO | disconnected device → ✗, not a silent pass |
| P2.2 sysmon on a matrix | TODO | user report + capture |
| P2.3 R12 visual pass | TODO | album cover, custom art, weather; real scale, both surrounds |
| P2.4 `pic_scan_ctrl` 0x35 | TODO | observable effect, or marked unsupported |
| P2.5 device-command verdicts | TODO | feeds P1.3 |
| P2.6 `search_weather_city` live | TODO | success path on the configured account |
| P3.1 LAN capability gate | TODO | "needs a WiFi-capable device", distinct from failed and from silence; one shared shape |
| P3.2 `probe_lan`/`save_lan_config` | TODO | wired into the gate or deleted |
| P3.3 5-LCD + Voice/SendText | TODO | gated capabilities naming their blocker |
| P3.4 danmaku same gate | TODO | one capability check, not two |
| P4.1 `Cloud/ToDevice` probed | TODO | recorded live response |
| P4.2 decided | TODO | implemented or WONTFIX with the reason |
| P5.1 both ratchets | TODO | allowlist empty; no blocker-less open item |
| P5.2 user-POV pass | TODO | `gui_pov.py` + real app over touched panels |
| P5.3 release | TODO | CHANGELOG, tag, DMG verified from INSIDE the DMG |

### R72 plan — does everything that belongs in the daemon live in the daemon

**R70 answered a narrower question than its empty allowlist suggests.** It
asked *"does the GUI contain a second implementation?"* and closed it with
`check_gui_is_a_client.py`: a DENYLIST of five module names
(`divoom_lib.cloud`, `bleak`, `urllib.request`, `pyaudio`, `psutil`) plus four
PIL construction patterns, scoped to `divoom_gui/`. That allowlist is EMPTY,
and the class is **not** closed. A denylist enumerates forbidden MEANS; the
invariant is about ownership of ENDS, and it cannot catch a duplicate that
arrives through a module nobody thought to ban.

R72 asks the inverse and larger question: **is everything that belongs to the
daemon actually in the daemon?**

**The invariant, stated once so it can be enforced rather than remembered.**
`divoomd` owns every RESOURCE: device I/O (BLE/SPP/LAN), cloud HTTP and
credentials, host data (the notification database, now-playing, system stats,
the wall clock), rendering to device frames, and the persistence of
device-facing state. Clients own presentation, user intent, and their own local
preferences. **Each capability has exactly one implementation, and it lives
where its resource lives.**

#### R72 findings — F1-F7, each owned by a step

**All seven were verified against source while writing this plan** (line numbers
current at `8a49301`), and **none of them is visible to the R70 gate**. They are
the SEED of P0.3's census, not the whole of it: the two previous passes at this
class both used hand-written lists and both missed things a machine would not.
A finding is closed when its owning step is DONE **and** the census (P0)
independently reports it clean — a fix confirmed only by the person who made it
is the shape this round exists to stop.

| ID | Finding | Evidence | Daemon already has | Class | Closed by |
|----|---------|----------|--------------------|-------|-----------|
| **F1** | **Cloud auth is a live second implementation, and the seam is already built.** Three GUI sites call `divoom_lib.divoom_auth` directly instead of the wrapper that exists | `gui_api.py:59`, `api/connection.py:97`, `presets_manager.py:59` + `:61`; wrapper at `daemon_cloud.py:172` | `cloud.rs` — `login_email`, `login_guest`, md5 + hmac-md5, credential cooldown; socket commands at `cloud_cmds.rs:34`/`:55`/`:73` | duplicate (R70's exact shape, seam present and bypassed) | P1.1 |
| **F2** | **`sync_time` is reimplemented in Python AND the Python one was broken** — `AttributeError` swallowed into a silent `False`, so the feature never worked | `api/tools.py:157-158` → `divoom_lib/system/date_time.py:36-37` (the comment records the defect) | `device_call/system.rs:29` — `sync_time` / `system.set_date_time` / `set_date_time` / `time.set_date_time` | duplicate that is also a defect | P1.2 |
| **F3** | **`DeviceSettings` has the same hybrid shape** — Python logic wrapping the daemon proxy, so transport is correct and the logic is not | `api/tools.py:175-176` (`set_auto_power_off`), `:179-180` (`set_low_power_switch`) | `device_call/system.rs` equivalents — confirm per method | duplicate (hybrid; see the proxy trap below) | P1.3 |
| **F4** | **Weather is a TOLERATED duplicate maintained by a parity gate**, with a documented double-fetch and two callers of a PRIVATE library function | `media_sync.py:298-299`, `api/widgets.py:41-42` (`_resolve_location`); double-fetch documented at `api/widgets.py:24`; gate is `tools/check_weather_parity.py` | `weather.rs` | tolerated duplicate — a DECISION to re-make, not an oversight | P2.1, P2.2 |
| **F5** | **A third control surface runs inside the GUI process** — reflection-dispatch HTTP over every public bridge method, alongside the daemon socket and `divoomd mcp` | `control_server.py:31`, `:32`, `:34`, and `http.client` at `:241`/`:264` | daemon socket server + `divoomd mcp` (13 tools) | scope/ownership — and a denylist blind spot: `http.client` is unbanned, `urllib.request` is banned | P3.2 |
| **F6** | **The notification stack exists twice, and the Python half is outside the gate's scope entirely** — 581 LOC of Python against 361 of Rust, imported live at three sites | `gui_api.py:288`, `:327`, `:375` → `divoom_client/macos_notifications.py` (404) + `notification_router.py` (177) | `macos_notifications.rs` (361) — SQLite poll, binary-plist parse, slot routing, ANCS `0x50` | mixed: routing-table PRESENTATION is a client job, SQLite/plist access is not | P2.3 |
| **F7** | **The doctrine is false as written.** "`divoom_lib` is reference-only" — the GUI imports it at **35 runtime import statements across 13 files**, 9 distinct modules | `lifecycle_config` (7), `utils.atomic_io` (6), `models` (4), `weather_provider` (3), `system.device_settings` (2), `system.date_time`, `utils.converters`, `utils.media_players`, bare `divoom_lib` (10) | n/a — this is the sentence that hides F1-F6 | `stated-vs-implemented` at the level of project doctrine | P4.1, P4.2 |

**Read the table by CLASS, not row by row** (rule #6). F1 and F5 are one class —
the denylist names specific modules, so `divoom_auth` and `http.client` walk
past a gate that stops `divoom_lib.cloud` and `urllib.request`. F2 and F3 are
one class — `divoom_lib` helper objects constructed over the daemon proxy, which
is why they read as client code at the call site. F6 is a scope class, not a
code class: nothing was ever wrong with `divoom_client/`, it was simply never
looked at. Fixing seven instances and leaving those three classes alive is the
unfinished-fix shape this project has already been bitten by.

**F7 is the keystone and should be fixed EARLY, not last.** It is placed in P4
because rewriting doctrine is cheap once the evidence is in, but it is the
sentence that would end this round prematurely if a future session reads it and
concludes there is nothing to look for. If P4 slips, the round is not finished —
it has left the mechanism that hid the class fully intact.

**Completion criterion, mechanical.** Not "we looked and it seems fine":

1. The **capability census** (P0) runs as a gate. Every capability the daemon
   owns is either absent from the Python surface, or carries an entry naming
   WHY the client-side code is presentation rather than a second
   implementation. `unreviewed` is illegal from day one — R71 earns that word's
   retirement and R72 does not get to re-borrow it.
2. `divoom_lib` is reference-only **or the sentence is deleted**. If the GUI
   still imports it at runtime when the round ends, the docs say so plainly and
   name each surviving import and its reason.
3. **Every F-row above is CLOSED**, and closed means two independent things:
   its owning step is DONE, and P0's census reports it clean without being
   told to look. A finding whose only witness is the person who fixed it is
   not closed — that is the `verify-the-effect` rule, and F2 is this round's
   proof of why it matters (a feature that returned `False` for months while
   its caller reported success).

**P0 — the census, and proof that it can find a duplicate.**

The two previous attempts at this class used hand-written lists and both missed
things a machine would not. The deliverable is an instrument, not an audit.

- **P0.1** Machine-generate the OWNED list: every socket command from the
  daemon's dispatch plus every `device_call` method path, read out of the Rust
  source. Never hand-maintained — it goes stale the first week.
- **P0.2** Machine-generate the PYTHON EXECUTION list: every runtime site in
  `divoom_gui/`, `divoom_client/`, `scripts/` and the packaged entry points that
  touches an owned resource. **Scope is the whole shipped Python surface**, not
  `divoom_gui/` — **F6** is invisible from R70's scope.
- **P0.3** Join them into `docs/CAPABILITY_MAP.md`: capability → daemon impl →
  Python impl → verdict (duplicate / presentation / client-local / unknown).
  Seed with **F1-F7**; the census must produce the rest. A census that
  returns exactly the seven it was seeded with has not been calibrated, it
  has been transcribed.
- **P0.4** **Calibrate it** (`calibrate-the-instrument`). The census must
  independently rediscover **F2** (`sync_time`) and **F1** (`divoom_auth`),
  both known BEFORE it runs. A census that cannot find the duplicates you already have is not
  measuring what you think it is measuring, and its silence about everything
  else means nothing.

**P1 — the confirmed duplicates. Closes F1, F2, F3.**

- **P1.1** Auth through `daemon_cloud`; `divoom_lib.divoom_auth` loses its GUI
  callers. Careful: `gui_api.py:59` and `connection.py:97` are deliberately
  CACHE-ONLY so a status poll never blocks on a cloud login — the daemon wrapper
  must preserve that, and a test must pin it. Re-routing it into a blocking call
  would trade a duplicate for a hang.
- **P1.2** `sync_time` through the daemon. **Verify it works on hardware first**
  (R71's P2 packet) — this is a feature that has been silently returning False,
  so "it now returns True" is not evidence the device's clock changed.
- **P1.3** `DeviceSettings` per method, against `system.rs`.
- **P1.4** Delete the Python paths and the tests pinning them; state the
  coverage delta.

**P2 — the tolerated duplicates. Closes F4, F6.** The category matters
more than the two instances: a duplicate kept in step by a parity gate is a
DECISION, and it needs to be re-made deliberately rather than inherited.

- **P2.1** Weather: decide whether `check_weather_parity.py` is buying
  something (a reference oracle for the port) or is maintenance debt for a
  second implementation. R67's "Python was right every time" is about WIRE
  FORMATS and is not a reason to keep executing Python in the GUI.
- **P2.2** Kill the double-fetch documented at `api/widgets.py:24` either way
  (**F4**, second half — P2.1 can be answered without this one moving).
- **P2.3** Notifications: separate presentation (the routing table the user
  edits) from host-data access (the SQLite DB, plist parsing). The first is a
  client job; the second is the daemon's and already exists there.

**P3 — the unscoped surfaces. Closes F5**, and removes the scope hole that
made F6 invisible in the first place.

- **P3.1** Bring `divoom_client/`, `scripts/` and the packaged entry points into
  the census's scope permanently. This is `polyglot-gate-parity`: a second
  package inherits none of the first one's gates and the suite still reports
  green because it never claimed to cover it.
- **P3.2** `control_server.py`: decide whether headless drive belongs in the GUI
  process at all, given the daemon socket and `divoomd mcp` already exist. If it
  stays, it is a test harness and says so; if it goes, the e2e harness moves to
  the daemon surface. Either way its auth story gets stated, not left optional.
- **P3.3** The Rust menubar is a client too. Check it against the same
  invariant — it is small (1155 LOC) and was never audited for this.

**P4 — make the doctrine true, or delete it. Closes F7.**

- **P4.1** Every surviving `divoom_lib` runtime import is listed with its reason
  in AGENTS.md. Config/atomic-write helpers are plausibly client-local; protocol
  builders and transports are not.
- **P4.2** Rewrite the "reference-only" claim to match the code. A doctrine that
  is false in the direction of "stop looking" is worse than none, because it is
  precisely what would have suppressed F1-F6.

**P5 — replace the denylist with the invariant.**

- **P5.1** The census becomes the gate; `check_gui_is_a_client.py` folds into it
  or stays as a cheap fast-path pre-check, but it is no longer the thing that
  claims the class is closed.
- **P5.2** Prove it bites: reintroduce **F1-F7** one at a time and watch the
  census go red on each. Seven sabotages, seven reds. F3 and F5 are the two
  that will be tempting to skip — F3 because the proxy makes it look like
  client code, F5 because it is a scope rule rather than an import. Those
  are exactly the two whose absence let the class survive R70.

**P6 — close.** Census clean, all seven F-rows closed under both witnesses,
`CAPABILITY_MAP.md` current, CHANGELOG, release.

**Traps, named up front.**

- **An empty allowlist is not a closed class.** It is a closed class *with
  respect to the rule that was written down*. R70's gate is correct and its
  allowlist is honestly empty; the rule was narrower than the invariant. Do not
  read this round as a criticism of that gate — read it as the reason a
  denylist can never be the last gate for an ownership invariant.
- **"Reference-only" is the sentence that hides this class.** It is TRUE as a
  caution against false positives (a Python module that merely exists alongside
  a Rust one is not drift) and FALSE as currently written (the GUI executes it).
  Both halves must survive the rewrite or P4 will just invert the error.
- **The proxy makes duplicates look like clients.** `current_divoom` is a
  `DaemonDeviceProxy`, so `d.timer.set_timer(flag)` really does travel to the
  daemon and is FINE. But `DateTimeCommand(d)` wraps that same proxy in Python
  logic, and reads almost identically at the call site. The census must
  distinguish *transport through the daemon* from *logic in the client*, or it
  will drown P1 in false positives and miss finding 2.
- **Routing to the daemon can expose a weaker port** (R70's trap, still live).
  Verify live before deleting any Python path; a gap found that way is a port
  bug to fix, never a reason to keep the second implementation.
- **Do not re-borrow `unreviewed`.** R71 makes it an illegal reason string. A
  census that ships with 40 unreviewed rows has recreated the thing R71 spent a
  phase retiring.

**Step ledger** — each step updates its own row in the commit that does the
work. A row goes DONE only once its proof has been SEEN, and for anything
testable that means seen RED first.

| Step | Closes | State | Proof required |
|------|--------|-------|----------------|
| P0.1 owned-capability list | — | TODO | generated from Rust dispatch, not hand-written |
| P0.2 python execution list | — | TODO | scope covers `divoom_gui` + `divoom_client` + `scripts` + entry points |
| P0.3 `CAPABILITY_MAP.md` | seeds F1-F7 | TODO | every capability has a verdict; no `unreviewed`; finds rows beyond the seven |
| P0.4 census calibrated | F1, F2 | TODO | rediscovers both WITHOUT being told to look |
| P1.1 auth through the seam | **F1** | TODO | cache-only startup behaviour preserved and pinned (a blocking call trades a duplicate for a hang) |
| P1.2 `sync_time` via daemon | **F2** | TODO | verified on hardware — the device's clock actually changes, not "returns True" |
| P1.3 `DeviceSettings` | **F3** | TODO | per method, against `system.rs` |
| P1.4 delete + rebaseline | F1-F3 | TODO | dead Python and its tests gone; coverage delta stated |
| P2.1 weather duplicate decided | **F4** | TODO | parity gate justified as an oracle, or retired with the duplicate |
| P2.2 double-fetch killed | F4 | TODO | one fetch, whichever side wins |
| P2.3 notifications split | **F6** | TODO | presentation stays, host-data access moves |
| P3.1 scope widened | F6 (class) | TODO | census covers the whole shipped Python surface, permanently |
| P3.2 `control_server` decided | **F5** | TODO | kept as a stated test harness, or removed; auth story stated either way |
| P3.3 menubar audited | — | TODO | checked against the same invariant |
| P4.1 imports listed | F7 | TODO | each of the 35 sites is client-local with a reason, or gone |
| P4.2 doctrine rewritten | **F7** | TODO | the sentence matches the code, both halves intact |
| P5.1 census is the gate | — | TODO | wired into `.gatesrc`; denylist demoted to fast-path |
| P5.2 prove it bites | F1-F7 | TODO | 7 reintroduced, 7 reds — F3 and F5 included, not skipped |
| P6 close | all | TODO | every F-row closed under BOTH witnesses; CHANGELOG, release, map current |

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

**Two of these are worse than redundancy** (both carry their fix in P3/P4 below).

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

### R70 plan — seven phases, allowlist-ratcheted

**Completion criterion is mechanical, not a judgement call:** the P0 gate ships
with an allowlist seeded to exactly today's violations, each phase deletes the
entries it earned, and the class is closed when the allowlist is EMPTY. A phase
that cannot delete its entries did not finish, whatever its tests say.

**Order is forced by two house rules, not by convenience.** The harness comes
before the bug (#1), so the gate that would have caught all twelve is P0 — built
while the tree is still dirty, which is the only time its ability to fail can be
observed. And the seam comes before the panels: every one of these twelve chose
`CloudClient` over a wrapper that did not exist, so routing panels first would
just re-run the decision that caused it.

**P0 — the gate, before anything moves.**

- **P0.1** `tools/check_gui_is_a_client.py`: fail if `divoom_gui/` imports
  `divoom_lib.cloud`, `bleak`, `urllib.request`, `pyaudio` or `psutil`, or
  CONSTRUCTS pixels (`Image.new`, `ImageDraw`, `font.render`, `.resize(`).
  Decoding daemon bytes (`Image.frombytes`) stays legal — that is the
  `sysmon_widget.py` shape. Seed `ALLOWLIST` with today's violations.
- **P0.2** Prove it bites, in BOTH directions (rule #2): a violation off the
  allowlist must fail, AND an allowlist entry that no longer matches must fail.
  An allowlist that silently tolerates its own rot is a hole, not a ratchet.
- **P0.3** Wire into `.gatesrc` `GOH_CI_STEPS` and
  `.github/workflows/tests.yml`. Local and CI identical (rule #14 corollary).
- **P0.4** Turn the Python coverage floor ON. `GOH_PY_COV_MIN` is commented out
  in `.gatesrc` and `scripts/py_ci.sh` runs a bare `pytest -q`, so the "≥95%
  coverage gate" this file credits to R61 is enforced by NOBODY — the exact
  R69/P4.1 finding, still live on the Python side. Baseline it here so P5's
  deletions are judgeable instead of merely green.

**P1 — the seam (pure addition, nothing rerouted yet).**

- **P1.1** `daemon_protocol.py` wrappers for all 12 cloud commands +
  `get_animated_preview`.
- **P1.2** Daemon `render_widget {kind, size, params}` → `{frame_rgb_b64, ...}`,
  generalizing `cmd_sysmon` (kinds: `sysmon`, `stocks`, `notification`, `text`,
  `album_art`). ONE command, not four more — four bespoke siblings would leave
  the class alive for widget #6. `sysmon` stays as a thin alias: the working
  path is not churned to prove a point.
- **P1.3** ONE GUI helper `_widget_frame(kind, params)` that every panel calls.
  A single funnel, so "render it here instead" has nowhere to live.
- **P1.4** Parity fixtures per kind against the Python renderer it replaces, so
  the port is CHECKED rather than assumed (every R67 packet bug was found this
  way, and Python was right every time).

**P2 — cloud browse moves.** Findings #1, #2, #3, #4.

- **P2.1** Route the five panels through the wrappers; drop `CloudClient` from
  `divoom_gui/`.
- **P2.2** `fetch_gallery` + asset download/decode → daemon; delete
  `gallery_download.py` and the `urllib` in `gallery_sync.py`.
- **P2.3** `hot_update_preview` → the daemon's manifest.
- **P2.4** Every panel says WHY it is empty. **Closes the Deferred item** — the
  reason already exists daemon-side and the GUI discards it.
- **P2.5** Verify all 8 commands round-trip LIVE before deleting their Python
  twins. **Done early, during P1.1, on a configured account**: six returned real
  data. Two did not, and both are daemon-side gaps to close here, not reasons to
  keep the Python twin — `get_photo_albums` answers
  `Photo/GetAlbumList failed (RC=3): Request data is incomplete` (the R61 note
  below says RC=3 is a missing `BlueDevice/NewDevice` registration) and
  `search_weather_city` answers `Weather/SearchCity failed (RC=1): Failed`.
- Allowlist: `divoom_lib.cloud` and `urllib.request` entries deleted.

**P3 — the renderers move.** Findings #5, #6, and `_render_text_png`.

- **P3.1** Stocks → `render_widget`; delete the GUI's Yahoo fetch and PIL draw.
- **P3.2** Album art → `render_widget`; the LANCZOS/NEAREST drift ends. The
  false docstring is fixed by making it TRUE. **P1.4 measured the change this
  makes: 100% of pixels**, on hard-edged input — the preview has not been a
  drifted version of the device frame, it has been a different picture. Ship
  that as a stated change, not a silent one.
- **P3.3** Text → `render_widget` over `render.rs`'s `BitmapFont`; delete
  `_render_text_png`. One bitmap font in the product, not two.
- **P3.4** A CLASS-level regression test: for EVERY widget kind, the preview
  bytes and the pushed bytes come from one call. Per-widget assertions are what
  let stocks survive the sysmon fix.
- Allowlist: the PIL-construction entries deleted.

**P4 — MCP.** Finding #7.

- **P4.1** REPRODUCE the bundle failure first. The prediction is read off the
  code path; it may fail differently, and a fix aimed at a predicted symptom is
  a guess.
- **P4.2** Spawn `divoomd mcp`, resolved through
  `divoom_client.binary_resolver.resolve()`. Never a second resolver — that IS
  the R69 class.
- **P4.3** Test both shapes. R69 "careful here (1)": a bundle and a dev tree get
  DIFFERENT rules, and flattening them is wrong in a way unit tests miss.
- **P4.4** The Python MCP server stays as reference; it loses its GUI caller.

**P5 — delete the dead weight.** Findings #8-#12.

- **P5.1** `gui_main.py` — the `bleak`/`Divoom`/`DivoomWall` imports.
- **P5.2** `audio_visualizer.py` + `toggle_audio_visualizer`/`get_audio_levels`.
  Note `pyaudio` is not in `requirements.txt` at all — an undeclared dependency
  in dead code — while CI brew-installs PortAudio on every macOS run for it.
- **P5.3** `api/widgets.py` unreachable block + `push_weather`.
- **P5.4** `trigger_notification`.
- **P5.5** Delete the tests pinning all of the above. A test pinning a dead
  second implementation is PART of the defect (rule #8), not coverage worth
  keeping. Re-baseline P0.4's floor deliberately and state the number.
- **P5.6** `divoom.spec`: drop `collect_submodules("bleak")` and remeasure the
  bundle. If the GUI truly cannot reach BLE, the bundle proves it by working
  without it.

**P6 — close the class.**

- **P6.1** Allowlist empty. Enforced, not asserted.
- **P6.2** User-POV run of the REAL app (rule #4) across every touched panel —
  green tests are not a shipped feature, and v0.28.1 is this project's own
  proof.
- **P6.3** CHANGELOG stanza, version bump, release.

**Traps, named up front.**

- **An unwired daemon command is normally a DECISION** (R69/P2.1), and that
  presumption still holds for everything NOT in the findings table. These twelve
  were checked individually: `get_animated_preview`'s own comment names the
  Python GUI as its parity target, and the cloud commands lost their client when
  the native egui UI was retired. Orphaned, not declined.
- **Routing to the daemon can expose a WEAKER port.** Verify live before
  deleting any Python twin; a gap found that way is a port bug to fix, never a
  reason to keep the second implementation.
- **When two renderers disagree, the DEVICE-FACING one wins** (P1.4). Not the
  newer one and not the more convenient one: the invariant being restored is
  preview == device, so whatever actually pushes pixels is correct by
  definition. This does NOT reverse R67's "Python was right every time" —
  that finding is about WIRE FORMATS and still holds. Rendered CONTENT has a
  different authority from protocol bytes.
- **Deleting code moves coverage.** Say the number out loud; a floor lowered
  quietly is a floor that stops meaning anything.
- **The bundle and the dev tree behave differently.** Every spawn/resolve change
  gets tested in both shapes.

### R70 test plan — close the holes, do not just add tests

**Start from the fact that matters: all twelve findings passed a 2935-test
Python suite and 291 Rust tests.** More tests of the same shape would have
caught none of them. Each phase's testing is therefore specified as _which hole
it closes_, and every new test is proven RED before it is trusted green (rule
#2 — and commit the fix BEFORE breaking it, or `git checkout` takes the fix
with it).

**The four holes, named:**

- **Hole A — the e2e suites stub `window.pywebview.api` in JS, so the Python
  backend never executes.** `test_e2e_clock_faces.py`, `_playlists`,
  `_photo_albums`, `_aid_sleep` all do this. They are good tests OF THE PANEL
  and are blind by construction to what Python does underneath — including
  whether it asks the daemon or does the work itself. This is the same hole
  that let v0.28.1 ship a daemon-killing crash past a green suite.
  **Instrument that closes it, already built:** `tests/e2e_gui_bridge.py`
  (real `DivoomGuiAPI` over HTTP) + `tests/support/gui_daemon_stack.py`
  (`IsolatedStack`, a real daemon subprocess on a private socket).
- **Hole B — nothing compares GUI-side output against DAEMON-side output.** The
  widget tests compare the GUI renderer to itself, which cannot see a defect
  both sides share (this is exactly why #5 and #6 survived the sysmon fix).
  **Instrument:** byte-equality with the daemon as the reference side.
- **Hole C — tests run only in the dev tree; the bundle shape is never
  exercised.** `test_mcp_control.py:84` asserts
  `cmd == ["/usr/bin/python3", "-m", "divoom_lib.cli", ...]` — it pins the
  defect AS the specification and passes in dev forever (the R69/P1.4 pattern).
  **Instrument:** parametrize over bundle-shape and dev-shape through
  `binary_resolver`'s existing seam.
- **Hole D — tests pin dead code, so "the tests pass" is WHY it survived.**
  Nothing asks "does anything call this?". `push_weather` has 4 tests and no
  caller. **Instrument:** a reachability check, new in P5.

**P0 — the gate is the instrument, so calibrate the instrument.**
`tests/test_check_gui_is_a_client.py` over a temp tree:
a violation off the allowlist exits non-zero; a clean tree exits zero (an
always-red gate is as useless as an always-green one); an allowlist entry that
no longer matches FAILS, so the ratchet cannot rot silently; and
`Image.frombytes` (decoding daemon bytes — the `sysmon_widget.py` shape) is NOT
flagged while `Image.new` is, proving it discriminates rather than banning PIL.
Then calibrate against reality: run at HEAD with an EMPTY allowlist and expect
exactly the findings-table files. That run is also the ledger's opening count.
P0.4 is proven the same way — drop a module's coverage on purpose and watch the
floor fail, because a floor that has never been seen to bite is not a floor.

**P1 — contract tests on the wire, not "it replied".**
Each wrapper round-trips against `IsolatedStack` asserting the command NAME and
args AS SENT. Prove-red by pointing a wrapper at a wrong command name: if the
test still passes it was only asserting that the daemon answered, which every
command satisfies. `render_widget` gets Rust unit tests plus P1.4's per-kind
parity fixture against the Python renderer it replaces — and where the two
differ, DECIDE which is right and record the reasoning, rather than trusting
whichever is newer (Python was right every time in R67).
**The specific regression risk of P1.2 is sysmon**, the one path that already
works: pin its output bytes BEFORE the `render_widget` refactor and assert
byte-identity after.

**P2 — assert the architecture, not the return value.** For each panel: the
command is observed on the socket AND no HTTP leaves the process (guard
`urllib.request.urlopen` and raise). The second half is the one that encodes
the rule — a panel that asks the daemon *and also* calls the cloud passes a
socket-only assertion. Prove-red by reverting one panel to `CloudClient`.
P2.4 must assert the reasons are DISTINGUISHABLE — genuinely empty, unreachable,
and unauthenticated produce different text — or "says why" collapses into one
generic sentence that is no better than `[]`.
P2.5 is not a unit test: a recorded real-backend run on a CONFIGURED account.
The v0.28.3 check ran under a throwaway HOME and proved only the error path;
repeating that would repeat the gap, not close it.

**P1.2 already produced one instance of the failure P3 is about**, and it is worth
reading before writing P3.4: the first `render_widget` sysmon parity test compared
the two REPLIES to each other. CPU load moves between the calls, so the only
assertions that survived were size and byte-count, and the test passed with the
renderer sabotaged to emit a solid block of 7s. The fix was to stop comparing two
outputs and instead close the loop — re-render the reply's OWN reported stats with
the canonical renderer and require byte equality. Prefer that shape in P3.4 wherever
the two sides cannot be held identical by construction.

**P3 — the drift test, with a fixture that can actually show drift.**
P3.4 parameterizes over the daemon's OWN list of kinds, so a new widget kind is
covered without anyone remembering to add a case. Prove-red is mandatory and
easy: flip one kind's filter from Nearest to Lanczos daemon-side and watch it go
red — if it stays green the test is comparing the GUI to itself, which is
precisely the blindness that hid #6. The album-art fixture must be hard-edged
(a 1px checkerboard), because on a smooth gradient LANCZOS and NEAREST agree and
the test would pass on a broken build.

**P4.1's reproduction beat its prediction, which is why the step exists.**
The plan said the spawned process would have its args eaten by
`parse_known_args()` and then exit on the single-instance guard. With no
instance already running it does not exit — it launches a whole second GUI
window, spawns another daemon and another menubar agent, and serves no
JSON-RPC at all. `mcp_control.is_running()` then reports the MCP server as
UP, because a process is indeed alive. A fix aimed at the predicted symptom
("it dies immediately") would have been aimed at the wrong thing.

**P4 — reproduce, then rewrite the test that pinned it.**
P4.1 drives the installed `.app`, clicks Start MCP Server, and reads
`~/.config/divoom-control/mcp-server.log`; the predicted failure is read off a
code path and may be wrong in its details. `test_mcp_control.py`'s spawn
assertion is then rewritten to name the resolved daemon binary — deleting a
test that pins a defect is part of the fix, not a loss of coverage (rule #8).
Add a real handshake test: spawn through the controller, complete
`initialize` + `tools/list`, expect 13 tools (verified by hand 2026-08-30).
Prove-red by resolving to a non-existent binary — the controller must report an
honest error, never "running".

**P5 — the reachability check is the phase's real deliverable.**
For every public `DivoomGuiAPI` method, assert a caller exists in `web_ui/` or
an explicit allowlist entry gives the reason. That check, and nothing else,
would have flagged `push_weather`, `trigger_notification`,
`toggle_audio_visualizer` and `get_audio_levels` the day they went dead.
**Careful:** `control_server.py` and the MCP surface legitimately call methods
JS never does, so the allowlist needs REASONS, not just names — an unexplained
entry is how this check would rot into a rubber stamp.
Deletion itself is judged by P0.4's floor: state the before/after test counts
and the coverage delta out loud.
P5.6 is verified in the BUILT bundle, never the source tree (the v0.28.3 rule):
build without `collect_submodules("bleak")`, then launch the `.app`, connect a
device and push art from it.

**P6 — the same command that returned twelve returns zero.**
Re-run the P0 gate with an empty allowlist. Then `scripts/gui_pov.py` and a
real-app pass over every touched panel, light and dark backdrop, because green
tests are not a shipped feature and this project has its own v0.28.1 proof.

**Step ledger** — each step updates its own row in the commit that does the
work, so the table and git history cannot disagree (the R69 discipline).

Every row carries its own proof. A row goes DONE only when its test has been
seen RED — "wrote a test, it passed" is the state this whole round exists to
correct.

| Step | State | Proven by |
|------|-------|-----------|
| P0.1 gate | **DONE** | `tools/check_gui_is_a_client.py`; 27 violations across the 12 findings' files |
| P0.2 prove it bites | **DONE** | 18 tests; 4 sabotages each went red on the property they broke |
| P0.3 wire local+CI | **DONE** | same position in `.gatesrc` and `tests.yml`; verified in the no-`GOH_DIR` CI shape |
| P0.4 Python cov floor ON | **DONE** | 89% measured (not the 95% claimed); floor 99 fails / floor 1 passes |
| P1.1 cloud wrappers | **DONE** | `daemon_cloud.py`, 14 wrappers, 22 wire tests; 3 sabotages → 3 red signatures; all 8 round-tripped live on a configured account |
| P1.2 `render_widget` | **DONE** | kinds sysmon/stocks/album_art/text. First parity test was BLIND (compared lengths, passed under sabotage). **The rewrite did not reach the tree until P3.3** — a `git checkout` after the second sabotage reverted the uncommitted fix. Restored and re-proven red |
| P1.3 `_widget_frame` funnel | **DONE** | `widget_frames.py`; sysmon migrated first; 11 tests. Pixel test verified against a REAL pixel change — a 16→16 resize is a no-op and would have looked green |
| P1.4 parity fixtures | **DONE** | album art: GUI LANCZOS vs device NEAREST differ on **100% of pixels**; daemon proven byte-identical to PIL NEAREST. Flipping the Rust filter turns both tests red |
| P2.1 five panels | **DONE** | `cloud_panels.py` funnel; 17 tests incl. a no-HTTP guard; half-migrated panel → red. Allowlist 26 → 21 |
| P2.2 gallery fetch+assets | **DONE** | `gallery_download.py` deleted; daemon decodes magic 9/18/26/0xAA the GUI could NOT — blank tiles fixed, not just relocated. Allowlist 21 → 17 |
| P2.3 hot manifest | **DONE** | new `hot_manifest` command; preview 86 → 25 lines. **Found a u128 shift-overflow panic in `art_codec.rs` that also breaks the shipped hot-channel PUSH** — fixed, 13-width regression test |
| P2.4 failures say why | **DONE** (with P2.1) | three causes → three texts, pinned; e2e asserts the reason reaches the SCREEN. Closes the Deferred item |
| P2.5 live round-trip + RC=3 | **PARTIAL** | 8 cloud commands verified live on a configured account (P1.1); hot manifest + previews verified (P2.3). Still open: the `get_photo_albums` RC=3 and `search_weather_city` RC=1 daemon-side gaps |
| P3.1 stocks | **DONE** | one call feeds preview and push; its test had started hitting the LIVE Yahoo API |
| P3.2 album art | **DONE** | verified live: preview now byte-identical to the device frame, and no longer equal to the old LANCZOS one. The false docstring is true |
| P3.3 text | **DONE** | one bitmap font in the product, not two. Deferred decision settled on rendered evidence: scaling turned "HELLO WORLD" into two rows of noise, clipping keeps glyphs intact. Text is vertically centred now |
| P3.4 class-level drift test | **DONE** | kinds read from `render_widget::KINDS`; a new daemon kind was auto-covered by 2 tests with no test edit; a resample turns 7/9 red |
| P4.1 reproduce in bundle | **DONE** | WORSE than predicted: it does not exit, it launches a SECOND GUI + daemon + menubar and never answers JSON-RPC, so `is_running()` reports success. Also surfaced the every-launch daemon kill (fixed) |
| P4.2 spawn `divoomd mcp` | **DONE** | verified in the BUNDLE shape: resolves to `Contents/Frameworks/bin/divoomd`, answers initialize + 13 tools |
| P4.3 both shapes tested | **DONE** | resolution goes through `binary_resolver` (one resolver, R69 class); unresolvable → honest error, never "running" |
| P4.4 Python MCP → reference | **DONE** | `test_start_uses_sys_executable_by_default` pinned the defect and passed in dev forever — Hole C exactly. Rewritten + 5 new tests |
| P5.0 reachability check | **DONE** | `check_gui_api_reachable.py`. Found **24, not 4** — the other 20 are allowlisted `unreviewed`, an honest state and a decision still owed |
| P5.1-P5.4 deletions | **DONE** | bleak/Divoom/DivoomWall imports, audio_visualizer.py, push_weather, trigger_notification, 22 unreachable lines |
| P5.5 tests + floor rebaseline | **DONE** | 2996 passed / 94 skipped; coverage 89% → **90%**, floor raised to match |
| P5.6 bleak out of the bundle | **DONE** | out of `divoom.spec`; the frozen entry point loads ZERO bleak modules (verified). Also dropped CI's `brew install portaudio` |
| P6.1 allowlist empty | **DONE** | 27 violations across 12 files → **0, with no exemptions** |
| P6.2 user-POV pass | **DONE** | `gui_pov.py`, no mocks in the chain: stocks/sysmon/album art all live, album art visibly NEAREST now. Killing the daemon still SAYS so. Found a stuttering error hint no assertion could see |
| P6.3 CHANGELOG + release | **DONE** | v0.29.0 tagged at `c3d09dd` on green CI; DMG sha256 `7550f1d3...`; verified INSIDE the DMG (both binaries 0.29.0, BUNDLE_VERSION stamp present, no bleak, `divoomd mcp` = 13 tools) |

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

- ~~**Cloud browse cannot say WHY it is empty**~~ — **CLOSED by R70 P2.1/P2.4**
  (2026-08-30). Fixed as a class, in one shared shape each side:
  `divoom_gui/cloud_panels.py::_cloud_list` produces `{ok, items, error, cause}`
  and `web_ui/cloud_result.js` unwraps it. The reason had existed the whole
  time — the daemon answers `Photo/GetAlbumList failed (RC=3): ...` — and the
  GUI discarded it at an `except`. Three causes now yield three distinguishable
  messages, pinned by tests, with an e2e asserting the text reaches the screen.
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



