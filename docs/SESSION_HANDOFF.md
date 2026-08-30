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

- **2026-08-30 (v0.28.3) — SHIPPED.** Tag `1a4a273` on a green CI (all five
  checks), GitHub release + `Divoom-v0.28.3.dmg` (sha256 `52550f48...`), cask
  verified to carry that sha. Verified inside the DMG, not just the source tree:
  both binaries report 0.28.3 and the bundled daemon survives the
  `get_status`/`players`/`now_playing`/`sysmon` sequence that killed v0.28.0's.
  `brew install --cask ztomer/tap/divoom-control`.

  **The rule, now enforced rather than remembered: `divoomd` and
  `divoom-menubar` always report the app version. Anything else is stale, and
  stale means rebuild.**

  v0.28.2 left a note saying `target/release/divoomd` was 0.27.0 on this machine
  and "the harness handles it". It was hiding a live defect. `spawn_daemon`
  picked the binary by walking `["release", "debug"]`, so the stale one won
  unconditionally — and `ensure_daemon` stops a daemon whose version does not
  match, then respawns from that same path. Spawn stale, notice, kill, repeat.
  The user would see a daemon that will not stay up, with nothing naming the
  version.

  * **Selection goes by VERSION now**, in `divoom_client/binary_resolver.py`,
    shared by the app and the test suite so the two cannot disagree about which
    daemon is "the" daemon. Location, mtime and assert-afterwards were all
    proxies for the binary's own version.
  * **`divoomd --version` used to START A DAEMON.** The parser had no such
    branch and silently ignored anything unrecognised, so the flag fell through
    to the default socket — and so did every typo. Parsing is now
    `divoomd/src/cli_args.rs`, a pure function with 11 tests; unknown arguments
    and missing values are hard errors. `divoom-menubar` had the same hole and
    no CLI at all; 5 tests.
  * **`tools/check_built_binaries.py`** checks artifacts, not manifests. It runs
    AFTER the cargo steps in `.gatesrc` and both Rust CI jobs — reading
    `target/` before anything is built would pass on the absence of its own
    subject.

  **Careful here (1):** a bundle and a dev tree get DIFFERENT rules in
  `resolve()`, and flattening them into one candidate list is wrong in a way the
  unit tests did not see. Inside a packaged app the answer comes from the
  bundle, always — version preferred, but an unverifiable bundled binary is used
  anyway, because "rebuild" is not available to someone running an installed
  app. In the dev tree the version match is required. Reaching from a bundle
  into somebody's `target/` would run a daemon the bundle was never built with.

  **Careful here (2):** the `--version` probe passes a throwaway `--socket` to
  `divoomd` and NOT to the menubar. The redirect stops an old divoomd from
  littering `/tmp/divoomd.sock` when the timeout SIGKILLs it; the menubar binds
  no socket and refuses trailing arguments, so giving it one turns the probe into
  an exit-2 that reads as "stale". Both directions are pinned by tests.

  **R69 plan: ALL FOUR PHASES DONE (2026-08-30).** The step ledger in
  `docs/ROADMAP.md` is the record; every step updated its own row in the same
  commit, so the table and the git history cannot disagree. Highlights and the
  traps are in the CHANGELOG's v0.28.3 stanza. Three things a future session
  should not have to rediscover:

  * **An unwired backend command is evidence of a DECISION, not an oversight.**
    P2.1 was going to wire five LAN commands; four of them had been left alone
    deliberately, with the reasons sitting in the handler comments, and one of
    the plan's own premises (a per-device capability to gate 5-LCD on) was
    simply false. Read why before undoing it.
  * **Assert what is RENDERED, not the DOM property.** Seven green e2e tests
    described a panel that was plainly visible on screen while its `hidden`
    property was true — an author `display: flex` beats the UA stylesheet's
    `[hidden]`. A screenshot found it immediately. Any new UI assertion should
    use `page.is_visible` / `state="visible"`.
  * **`.failure` sidecars can outlive their condition.** The winner of the
    single-instance race never re-enters `acquire`, so anything written after it
    started stays forever. `LiveInstance` now clears rather than writes.

  **Open, and a decision rather than a task: no CI coverage job.** The floor is
  enforced locally only (step 15). A CI job must run on macOS to measure the
  same scope — `nowplaying` is macOS-only and counts toward the percentage — so
  a Linux job would have a different denominator and a floor that does not
  match. Local stricter than CI is the safe direction, but the floor only bites
  for whoever runs the gate.

  The plan text in `docs/ROADMAP.md` is kept as written, including the parts the
  P2.1 audit overturned, with the correction recorded beneath it. A plan that is
  quietly edited to match what happened teaches nothing; one that shows where it
  was wrong is the useful artifact.

- **2026-08-30 (v0.28.2) — SHIPPED. Tooling and docs; the app is unchanged.**
  Tag `9790649` on a green CI (run 33328371650); GitHub release +
  `Divoom-v0.28.2.dmg` (sha256 `4efff246...`), cask verified to carry that sha.
  No product code in this release — behaviour is identical to v0.28.1.

  **Session close-out (2026-08-30):** three releases in one day — v0.28.0 (six
  red CI runs cleared, socket rule made structural, camoufox raised to latest,
  sysmon made a daemon client), v0.28.1 (the GUI-kills-the-daemon crash, found
  by finally running the app), v0.28.2 (this one). Open items are in
  "Open threads" below; nothing is left half-done.

  * **`scripts/gui_pov.py`** — the harness that found v0.28.1's crash, promoted
    out of a scratchpad. Real daemon + real GUI backend + real page, no mocks.
    Checks the daemon is still ALIVE afterwards, that the live refresh is
    actually running (counted by CALLS, not by watching a value — a busy machine
    sits at 100% and looks frozen), and with `--kill-daemon` that the UI admits
    the backend is gone. Logs every api call, so a death report names the last
    25 things the UI asked for. **Use it before calling anything user-facing
    done.**
  * **macOS TCC written down** in `AGENTS.md` and the hardware note below: a
    shell-launched daemon has no Bluetooth grant and the first scan kills it
    with SIGABRT and an EMPTY stderr. Looks like your crash; is not. Build
    `--no-default-features` for terminal work, and redo that build after any
    `cargo test` (which rebuilds debug WITH default features).
  * **Pruned**: 14 dead scripts, `docs/archive/` entirely, 244 lines of
    superseded handoff entries, and a dangling `DEVICE_VALIDATION_PLAN.md`
    reference in `AGENTS.md`. All recoverable from git; the docs say how.


- **Older 2026-08-30 rounds pruned (v0.28.3 close-out).** The per-round prose for
  v0.28.1, v0.28.0/R68, the socket-robustness round and the R67 close-out is in
  `git log -p -- docs/SESSION_HANDOFF.md`; what each SHIPPED is in
  `CHANGELOG.md`, which is the durable record. Two facts from those rounds are
  load-bearing enough to keep out of the archive, so they live below in
  "Open threads" and the "Hardware note": macOS Bluetooth TCC kills a
  shell-launched daemon on its first scan, and `ci_local.sh` is structurally
  blind to Linux-only CI failures.

## Open threads / next up

- **R70 GUI/daemon boundary audit (2026-08-30) — 12 findings, ALL OPEN. Full
  table in `docs/ROADMAP.md` under "R70".**

  The question was "is anything left in the Python GUI that should live in the
  daemon". It is: seven live duplicates where the daemon ALREADY answers the
  command and the GUI does the work itself anyway, plus five pieces of dead
  weight (a `bleak` import in the process that must never own BLE; a 150-LOC
  pyaudio+numpy visualizer nothing calls; unreachable code after a `return`).

  Verified against the LIVE daemon on `/tmp/divoom.sock`, not read off source:
  `get_dial_types` returned real categories, `get_animated_preview` returned a
  valid 2.9 KB GIF data-url, and the bundled `divoomd mcp` served 13 tools —
  every one of them while the GUI runs its own Python twin.

  **Two are not merely redundant.** `media_sync.py:84` carries a docstring
  claiming it shares the device's renderer, and resizes LANCZOS where the device
  gets NEAREST. And `mcp_control.py` spawns `sys.executable -m divoom_lib.cli`,
  which inside the `.app` is the GUI binary — `parse_known_args()` eats the
  args and the single-instance guard exits, so "Start MCP Server" cannot work in
  a bundle at all. Reproduce that one in the bundle before fixing it.

  **The seam is the root cause, and it is where a fix should start.**
  `divoom_client/daemon_protocol.py` has no wrapper for ANY of the twelve-plus
  cloud commands, so every panel that needed one imported `CloudClient` instead.
  Add the wrappers, then route the panels, then delete the Python paths. One
  panel at a time leaves the class alive.

  Free consequence: this subsumes the Deferred "cloud browse cannot say WHY it
  is empty" item. The daemon already returns
  `Photo/GetAlbumList failed (RC=3): ...`; the GUI's `except → []` discards it.

- **gui_pov + real-backend check before v0.28.3 (2026-08-30) — PASSED, with two
  honest gaps recorded rather than papered over.**

  `scripts/gui_pov.py` is green: the daemon survives, and the sysmon refresh is
  running (4 calls in ~10s, values changing). The v0.28.3 GUI surface was then
  driven through the REAL `DivoomGuiAPI` in the bridge, because the weather and
  danmaku e2e suites mock `window.pywebview.api` and had therefore never
  exercised the real backend — the exact gap that let v0.28.1 ship a
  daemon-killing crash past a green suite. All five new methods round-trip and
  the daemon stays alive:
  `get/set_weather_city` (save, read back, clear), `search_weather_city`,
  `send_danmaku_text`.

  **Gap 1 — the cloud path is unverified for a CONFIGURED account.** The check
  ran under a throwaway HOME, so `search_weather_city` took the no-credentials
  branch and returned `[]` from `UserNewGuest RC=10` (guest login, upstream
  Divoom, documented since R61). That proves the error path, NOT the success
  path. Verifying the success path means a live authenticated call on the real
  account, which was deliberately not made as a background check. **First thing
  to try by hand: open Live Widgets -> Weather, click the location line, search
  a city.**

  **Gap 2 — the panel cannot tell "no matches" from "cloud unavailable".**
  `search_weather_city` returns `[]` for both, so the UI says "No cities found."
  when the real reason may be an unreachable or unauthenticated cloud. That is
  the honest-placeholder rule (a failed state must say WHY) not being met, and
  it is the same defect in every sibling cloud browse — clock faces, playlists,
  photo albums, aid sleep all swallow their exception and return `[]` too. Fix
  it as a CLASS, in the shared shape, rather than one panel at a time. Not fixed
  during the release cut on purpose: it is a contract change across five
  features and their tests, which is not release-eve work.


- **R66 CI workflow: VERIFIED GREEN (2026-08-18).** All five jobs pass on
  `2d7beb9`. The logs confirm the gate parity is real, not merely configured:
  `rust-ble`'s workspace clippy checks `divoom-menubar` and runs its 13 tests
  (no CI job had ever run them before R66), and `test` fetches camoufox.

- **INCIDENT — v0.23.0 shipped on a RED CI, and it was NOT billing.** Four of
  five jobs were green; `rust-core` failed for a real reason introduced in R66
  Phase 5: workspace-wide clippy on the LINUX runner pulls in `divoom-menubar`,
  whose tao/tray-icon deps need GTK/glib, which that runner does not install.
  The release was cut assuming the red was credit depletion, without reading
  the log. Diagnosing it took two minutes. Fixed in `2d7beb9` (`rust-core` lints
  `-p divoomd`; macOS `rust-ble` owns the workspace clippy, being the only
  platform where the menubar builds without extra system packages). **No user
  impact** — the DMG was built and verified locally on macOS.
  Two rules now in `AGENTS.md`: diagnose a red CI, never assume billing (red and
  out-of-credits look identical from outside — that is exactly why the gate
  exists); and `ci_local.sh` runs on THIS machine only, so Linux-only failures
  in `rust-core`/`rust-ble-linux` are structurally invisible to it.

- **The buildable work is planned, not listed here.** `docs/ROADMAP.md` →
  "R69 plan — what can be built without the user in the loop" has the four
  phases, in order, with acceptance for each. The items below are what is left
  after that: none of them is unbuilt, they are UNWATCHED, and there is no code
  to write until someone looks at a device.

- **R12 user-POV visual pass**: deferred to user (needs live app + real device for screenshots).
- **sysmon on a real device**: the RPC and the frame are verified against a real
  daemon over the real socket, but nobody has watched the gauges on a matrix.
  Needs hardware.
- **Cloud HTTP**: 533/533 commands cataloged (`docs/cloud_api/`). Clock-face
  store, playlist browse+push and AidSleep browse+play are all shipped and
  GUI-wired. What is still open is listed in `docs/ROADMAP.md` under "Open
  workstreams": four backend-only LAN clusters with no GUI surface, and
  `Cloud/ToDevice`, which stays unimplemented because its semantics were never
  confirmed and there is no live caller to infer them from.

  _(This bullet was truncated mid-sentence for four commits — it lost its
  continuation lines in the 2026-08-30 prune and read "Clock-face store wired
  into". Recovered from `git show 78b1986:docs/SESSION_HANDOFF.md` and rewritten
  as current state rather than restored verbatim.)_

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

Watch out: `cargo test` rebuilds `target/debug/divoomd` WITH default features,
so a BLE-free build does not stay BLE-free across a test run.
