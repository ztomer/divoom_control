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

- **2026-08-30 (v0.28.2) — tooling and docs; the app is unchanged.** No product
  code in this release.

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


- **2026-08-30 — v0.28.1 SHIPPED and verified in the bundle.** Tag `a37fb70` on
  a green CI (run 33320160112); GitHub release + `Divoom-v0.28.1.dmg`
  (sha256 `1e2f9bde...`), Homebrew cask carrying that exact sha.
  Verified against the artifact users install, not just the source tree: the
  daemon inside `Divoom.app/Contents/Frameworks/bin/divoomd` answers
  `now_playing` / `players` / `sysmon` three rounds running and stays alive —
  the exact sequence that aborted it in v0.28.0.

  **v0.28.0 was live on Homebrew with that crash for a few hours.** It shipped
  with "nobody has clicked it" recorded as a known gap, which is not the same as
  mitigating the gap. If validation is cheap enough to write down, do it before
  the release.

- **2026-08-30 (v0.28.1) — the GUI was exercised for real, and it killed the
  daemon.** v0.28.0 shipped with "nobody has launched the app and clicked it"
  recorded as the open risk. Doing that found three defects in one sitting.

  * **`now_playing`/`players` ABORTED the daemon.** `nowplaying::current_track()`
    builds a `reqwest::blocking::Client` on the Feishin path; that client owns a
    private tokio runtime, and dropping a runtime in an async context panics on
    a worker thread and kills the process. The GUI asks `now_playing` on load,
    and the Feishin path is taken whenever nothing is playing OR something is
    merely PAUSED — so opening the app with music paused killed the background
    service, which then left its socket behind. Both handlers are now `async`
    and reach the blocking probe only through one `spawn_blocking` helper.
    **`live_jobs` had always done this correctly**; only the two command
    handlers skipped it.
  * **The System Monitor card was frozen.** `restoreActiveWidgetForDevice` reset
    `selectedWidget` to "music" whenever the device had no live job, ~250ms
    after any click. The Live (5s) timer only runs while its widget is selected.
    It now adopts a running job and otherwise leaves the selection alone.
  * **A dead daemon looked like an idle machine.** The refresh returned silently
    on failure, leaving stale numbers up. It now blanks them and says why, using
    the `<socket>.failure` report the daemon writes, surfaced via a new
    `unreachable` field on the transport rather than errno string-matching.

  **How they hid:** the now-playing tests called the crashing function as plain
  `#[test]`, i.e. with no runtime running — the one context where the bug is
  impossible. They are `#[tokio::test]` now, and the new regression test drops a
  nested runtime through the helper so it reproduces the mechanism with no
  network and no Feishin install (the real trigger needs Feishin credentials and
  would never fire in CI).

  **Harness worth reusing:** `tests/e2e_gui_bridge.py` + camoufox drives the
  REAL GUI backend against a REAL daemon. That is what found all three. Any
  future "does the app actually work" question should start there.


- **2026-08-30 (R68) — v0.28.0 SHIPPED.** Tagged at `6d08e4b` on a green CI
  (run 33312022508), GitHub release published with
  `Divoom-v0.28.0.dmg` (sha256 `2a20bb63...`), Homebrew cask bumped and
  verified to carry that exact sha. `brew install --cask ztomer/tap/divoom-control`.
  This release carries R67's work too — v0.27.0 was written but never tagged,
  because CI had been red for six consecutive runs.

  **That validation happened, and it found three bugs** — see the v0.28.1 entry
  above. The sysmon path itself was correct; what was broken around it was worse
  than what was changed. Flagging the gap was right; shipping before closing it
  is what put a daemon-killing bug in a published DMG for a few hours.

- **2026-08-30 (R68, v0.28.0) — the six-run CI red is cleared; four things
  fixed, two of them gates that were wrong about their own subject.**

  * **`check_no_allow.py` matched its own rationale.** It regexed raw source, so
    a doc comment explaining why a field is named `_file` "rather than carrying
    an `#[allow(dead_code)]`" read as the violation. Same defect
    `check_positional_args.py` was fixed for six commits earlier — the stripper
    was shared out to `_srcscan.strip_rust_comments` then, and this sibling was
    never migrated. **All three gates that INTERPRET Rust source now strip
    comments**; `check_file_size.py` counts lines and is correctly exempt.

  * **The socket rule is now structural.** `serve` borrowing the listener was a
    proxy for the real constraint, cost every test call site a
    `Box::leak(Box::new(listener))`, and had left `clippy --all-targets` red on
    Linux since it landed. `HeldSocket` owns the listener, the startup lock and
    the recorded identity, and its `Drop` body does the ownership-checked
    unlink — Rust runs a `Drop` body before dropping fields, so the socket is
    necessarily still open when the check runs. A second check-then-act
    (`SocketOwnership::of` read after the lock section) is gone: identity is
    captured inside `acquire`. **Careful here:** the invariant is now drop
    order. Do not move the release out of `Drop`, and do not add a field the
    release depends on being alive AFTER it.

  * **camoufox is at the latest build (0.5.5 / beta.29).** The recorded plan —
    "prefix every evaluate / wait_for_function with `mw:`" — was only half
    possible. `wait_for_function` has NO main-world form, and neither does
    `add_init_script`, which is where the suites install `window.__api` before
    the app reads it. All three holes are bridged in
    `tests/support/browser.py`; 191 call sites route through it. 132 e2e pass.

  * **sysmon is a daemon client.** New `sysmon` RPC returns the stats and the
    exact frame `live_jobs/render.rs` would push; the GUI writes those bytes to
    a PNG for both the tile and the device. The one-shot path refreshes
    `sysinfo` twice around `MINIMUM_CPU_UPDATE_INTERVAL` — CPU is a delta, and
    one refresh reports a confidently idle machine.

  * **The daemon e2e harness was testing a stale binary.**
    `_find_rust_binary` preferred `target/release/divoomd`, which nothing in
    this repo rebuilds, so a leftover release build was "the daemon under test"
    on this machine indefinitely. The version bump exposed it (0.27.0 vs an
    expected 0.28.0 → the client's version guard stopped it mid-test →
    `[Errno 2]`, which reads like a socket bug). Now newest-by-mtime plus a
    `daemon_version` assertion at fixture setup. **Note for next session:**
    `target/release/divoomd` on this machine is still 0.27.0; the harness
    handles it, but rebuild it if you touch release packaging.

  Through-line: four of the failures this round were not product defects. Two
  were gates wrong about their own subject, one was a fix that had not been
  finished (the borrow landed without its call sites), and one was a harness
  pointed at the wrong artifact. A red CI still has to be READ — and so does a
  GREEN one, since CI was green while local was red for a reason that had
  nothing to do with the diff.


- **2026-08-30 (socket robustness) — stale-socket startup failures fixed and
  made visible.** `divoomd/src/socket_bind.rs` replaces the three-line
  check-then-act `bind()`: an advisory lock on `<socket>.lock` makes
  inspect-and-bind atomic (closing the two-daemon startup race that CREATES the
  orphan `socket_owner` guards against at exit), blockers are distinguished with
  a remedy each, and only the unambiguous cases self-heal — a stale socket and a
  missing parent directory. A regular file on the path is never auto-removed.

  The reason now reaches the user: `<socket>.failure` is read by
  `divoom_client/socket_failure.py`, logged by `ensure_daemon` in place of the
  timeout message, and carried by `daemon_health` into the GUI banner.

  **Careful here:** `serve()` BORROWS its listener, and that is load-bearing —
  an open fd pins the socket's inode so `(dev, ino)` still identifies it at
  shutdown. Do not change it back to owning without reading the invariant note
  in `socket_owner.rs`.

- **2026-08-30 (R67 close-out) — three CI-only failures fixed; release still
  UNTAGGED pending a green run.** Local gates green; Python suite green
  locally on camoufox 0.5.4.

  All three were the same shape: **a fact verified in one environment and
  trusted in another.**

  * `check_positional_args` gave OPPOSITE verdicts on macOS and Linux for the
    same commit. It regexed raw source (so a comment quoting `args.get(1)`
    matched as code) and picked Python signatures first-wins over an unsorted
    `rglob` (so the annotated-vs-bare `show_light` winner depended on
    filesystem order). The APFS answer masked the comment bug; ext4 exposed it.
    Now sorted + richest-signature-wins + comment-blind (`tools/_srcscan.py`,
    also used by `check_weather_parity`). Both defects pinned by
    `tests/test_positional_gate.py`, each proven red first.
  * **The Linux build broke twice this round** on an ungated reference to the
    macOS-only `nowplaying` crate. A macOS box cannot see that class, so CI was
    the only instrument. `scripts/check_linux_build.sh` now cross-compiles
    divoomd for Linux with zig (wired into `.gatesrc`), calibrated by
    confirming it reproduces CI's exact `error[E0432]`.
  * **The 60 browser-e2e failures were never ours.** Unpinned `camoufox`
    upgraded to 0.5.5, whose browser isolates `page.evaluate` from the main
    world, so `window.DivoomState` reads `undefined`. Reproduced locally and
    probed (29 scripts 200 OK, DOM built, zero console errors -- the page is
    fine). The variable is the BROWSER BUILD: same package 0.5.4, beta.29 fails
    and beta.28 passes, and a package pin alone would NOT have fixed CI. Pinned
    with `camoufox set official/stable/152.0.4-beta.28`.

  **Open thread:** raising the camoufox pin is a MIGRATION — every `evaluate` /
  `wait_for_function` in the 15 e2e modules needs camoufox's `mw:` prefix
  (`main_world_eval=True` alone does not restore the old default; verified).
  Details at `tests/support/browser.py`.

  **Next action: tag v0.27.0** once CI is green (`scripts/release.sh`). The
  version, CHANGELOG and crates are all at 0.27.0 already.

- **Older rounds pruned to git history (2026-08-30).** Entries for 2026-08-29
  and earlier are in `git log -- docs/SESSION_HANDOFF.md`; what they SHIPPED is
  in `CHANGELOG.md`, which is the durable record. This file is the current
  state, not an archive — when a round's work is released and its changelog
  stanza written, its handoff entry has done its job.

## Open threads / next up

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

- **R12 user-POV visual pass**: deferred to user (needs live app + real device for screenshots).
- **sysmon on a real device**: the RPC and the frame are verified against a real
  daemon over the real socket, but nobody has watched the gauges on a matrix.
  Needs hardware.
- **Cloud HTTP**: 533/533 commands cataloged (`docs/cloud_api/`). Clock-face store wired into

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
