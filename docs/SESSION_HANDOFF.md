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

- **2026-09-07 — v0.32.0 (R74) CUT.** Two user-reported failures, both ours,
  both the same shape: a system that could not describe its own state, and
  instruments that read identically for "fine" and "broken". Full detail in the
  CHANGELOG stanza and `docs/release_notes_v0.32.0.md`; the durable lessons are
  in the new `daemon-liveness-design` skill.

  Round contents: the deaf-daemon redesign (accept always, shed with an
  identifiable refusal, LRU subscription registry keyed on client-produced
  activity), the AppleScript app-name crash + its repo-wide gate, and the
  empty-scope guard that unblocked `pre-push` for the first time in weeks.

- **2026-09-07 (end of session) — v0.33.0 released and INSTALLED.** All six
  repos in the estate were released and installed locally: divoom-control
  v0.33.0, routines v0.41.0, monitor v0.47.0, ztools v2.3.0, app_updates
  v1.32.0 (its first tag ever), gates_of_heck v0.10.0.

  **The stale-daemon note below is now resolved**: `/Applications/Divoom.app`
  carries divoomd 0.33.0, so the running daemon finally contains the R74 wedge
  fixes and today's write-seam work.

  Two instruments broke during the release and neither was a code defect —
  `check_hotchannel_parity.py` and `test_the_daemon_maps_every_size...` both
  grep Rust SOURCE, and `clippy::unreadable_literal` / `match_same_arms`
  legitimately rewrote the text they matched. Both now read the VALUE rather
  than the spelling, and both are calibrated. The pattern is written up in
  `calibrate-the-instrument/references/gate-discipline.md`.

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
  0ms with 3 fds instead of 66. NOTE the running daemon is
  `/Applications/Divoom.app/Contents/Frameworks/bin/divoomd` (installed v0.31.0)
  and does NOT contain these fixes — reinstall to pick them up.

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


Three things, and the first two need you at a keyboard with a device.

**1. The hardware packet — five checks, one command** (R73 closed and removed
the `pic_scan` and `clock_rich` entries).

    python3 scripts/hw_verify.py --self-test        # calibrate FIRST
    python3 scripts/hw_verify.py --out report.json

Start the GUI first: it owns the Bluetooth TCC grant, and the packet REFUSES to
spawn its own daemon because a shell-launched one dies on its first scan with
SIGABRT and an empty stderr. `--self-test` exits **3 = PARTIAL** until a device
is connected, which is honest rather than broken: with nothing attached the
daemon refuses at the no-device precondition before it ever reads the method
name, so the invalid-method branch stays untested.

What the packet decides:

* **Three UNEXPOSED methods** — `set_clock_rich`, `set_temperature_channel`,
  `set_timeplan`. The last three entries in `check_gui_api_reachable.py`'s
  allowlist. Not dead, not superseded: the daemon implements them and the UI
  never offers them, so wire-or-delete depends on whether the device renders
  them.
* **`sync_time`** — R72 routed it to the daemon and the Python path it replaced
  was BROKEN (an `AttributeError` swallowed into a silent `False`). "It returns
  True now" proves nothing; the clock has to be seen to change.
* **R12 visual pass**, **`pic_scan_ctrl` 0x35**, **`search_weather_city`** on a
  configured account.

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
