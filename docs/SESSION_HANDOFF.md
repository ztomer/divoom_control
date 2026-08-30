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
- Both: `git log --oneline`, `CHANGELOG.md`, `docs/PLANNING_ROUND*.md`.

## Current state — _update this section each round_

- **2026-08-29 (R67 Phases 3-4) — ROADMAP COMPLETE. All phases verified on
  hardware.** Python **2904 / 0 failed / 94 skipped; Rust 243 / 0.** Gates green.

  **The virtual wall never worked**, and it took three separate fixes:
  `wall_configure` uppercased slot keys while macOS uses lowercase UUIDs and the
  BLE connect compared case-sensitively (so no slot could connect); the daemon
  never read `target: "wall"` (so nothing reached a wall that did connect, and
  every DivoomWall method was dead code); and the ambient payload had brightness
  and RGB transposed in a six-byte packet. Verified live on Pixoo-1 +
  Ditoo-light-2: each command now goes out once per panel.

  **Weather** needed prevention, not repair — the two WMO tables were diffed and
  agree on all 48 codes. The mapping is a `const` table plus a parity gate; the
  GUI is a client of a new `weather` RPC.

  **Method note:** every Phase 4 bug was found by TRACING, not reading — the
  casing bug surfaced from a real wall_configure failure, the routing bug from
  grepping for a `target` the daemon never reads, and the transposition by
  diffing the Rust payload against the Python builder it was ported from.

  **Open:** the daemon NDJSON protocol (the user picked "device layer first",
  and the device layer is done); Feishin's Media Session left off by choice, so
  the weaker Subsonic path remains its source.

- **2026-08-29 (R67 Phase 2) — the album-art library. DONE and verified.**
  Suite: **Python 2926 / 0 failed / 94 skipped; Rust 196 / 0.** Gates green.

  Now-playing is a standalone `nowplaying` crate on macOS MediaRemote. Both old
  implementations are DELETED (`divoomd/src/live_jobs/music.rs` and 164 lines of
  `divoom_lib/utils/media_source.py`), along with the iTunes-Search URL guessing
  that could never resolve YouTube-Music content.

  **Read this before touching it:** a direct `dlopen` of MediaRemote from an
  unentitled process succeeds and returns a NULL dictionary — it fails looking
  exactly like "nothing is playing". `/usr/bin/perl` carries the entitlement, so
  the query runs inside perl via our dylib. Two traps found the hard way:
  MediaRemote declares `image/jpeg` over TIFF bytes (sniff, never trust), and
  perl's architecture is INHERITED from the launching process (arm64 from a
  shell, x86_64 from the daemon) so the host is pinned with `arch -arm64`.

  **The app no longer requests Automation access to music players at all** —
  MediaRemote needs no Apple Events, so C3's cause is gone rather than patched.

  **Method note:** all three helper bugs (pipe deadlock on 1.6MB of base64,
  discarded stderr, arch mismatch) were found by RUNNING it against the live
  system, not by review. The deadlock in particular passes with any small
  fixture and hangs only on real artwork.

  **Open:** the C7 audit (49 unaudited `args.get(N)` reads); C2's remaining half
  (weather + sysmon are still implemented twice); Feishin is still a Python-only
  provider and not yet folded into the crate; Phases 3 (weather) and 4 (wall).

- **2026-08-29 (R67) — six symptoms, seven classes. Phase 0 + 1 done, verified
  on hardware.** Full analysis + plan: `docs/PLANNING_ROUND67.md`.
  Suite: **Python 2943 / 0 failed / 94 skipped; Rust 157 / 0.** All gates green.

  The round started by probing the LIVE system rather than the code, and that
  is what cracked it: **two divoomd processes were running**, one a 34-hour
  orphan with no listener still holding the BLE central. `scan` and `connect`
  both worked fine (2.1s). "Connection is unreliable" was never a radio
  problem — it was process ownership.

  **The mechanism, confirmed by reproducing it:** the daemon unlinked its socket
  on shutdown without checking it still owned it. Killing the orphan DELETED the
  live daemon's socket, which left that one running and unreachable, so the GUI
  spawned another. Self-sustaining. Fixed by recording `(dev, inode)` at bind
  (`divoomd/src/socket_owner.rs`).

  Seven classes; C1/C3/C4/C5/C6/C7 fixed, C2 deferred to Phase 2:
  C1 one wire packet with four disagreeing builders (weather overlay landed in
  the humidity byte; ambient type byte hardcoded); C2 every live-widget data
  source implemented twice, Python for the preview and Rust for the device;
  C3 the TCC priming list missing Kaset; C4 live jobs silently no-op with a
  15-minute sleep; C5 above; C6 `HotProgress` stored without broadcasting, so
  the hot button hung on "Preparing…"; C7 positional args read from a COMPACTED
  list, so ambient brightness sent the mode number.

  **Method note worth keeping:** C7 and the version-stamp bug were both found
  during VERIFICATION, not review. `device_call` returns success even when the
  payload is wrong, so any harness asserting on RPC results is structurally
  blind to this whole class. `scripts/hw_e2e.py` asserts on the
  `DIVOOMD_BLE_DEBUG` wire trace instead, and that is what caught brightness
  tracking the mode. C7 also CORRECTS an earlier conclusion in this round that
  arity problems were "not a class" — that was right about dropped parameters
  and blind to misaligned ones.

  **New tooling:** `install.sh` (self-contained bundle to `/Applications`;
  the app now runs entirely from there), `scripts/hw_e2e.py`,
  `scripts/daemon_ping.py`, `tools/check_scripts.py`,
  `tools/check_version_consistency.py`. `make_dev_daemon_app.sh` had been dead
  since R66 and now verifies the bundle it builds.

  **Open threads:** the C7 audit (49 unaudited `args.get(N)` reads; `text.rs`
  known-latent), C2 / Phase 2 (the standalone album-art library — ZoneTilerWM's
  `Sources/ZTMediaRemote/` is the reference: MediaRemote via mediaremote-adapter,
  real artwork bytes, player-agnostic), Phase 3 weather unification, Phase 4
  virtual wall (untested, expected C1 fallout on the wall path).

- **2026-08-23 (later still) — v0.24.3: e2e injectors that silently did
  nothing.** Chased the two browser tests that reddened the v0.24.2 release.
  **Could not reproduce the flake** — not under a saturated 16-core machine,
  not across the full 166-test e2e subset, not on 3x re-runs of the exact
  failing command. What the code did show: three injected scripts ended their
  missing-element branch with a bare `return`, so a missing container raised
  nothing and pushed the damage downstream — the gallery one into an
  unsatisfiable wait (an opaque TimeoutError naming the layout check, which is
  why 5s -> 20s did not help), and the hot-preview one into a **vacuous pass**
  against an empty card. All three now fail at the precondition and name it.

  Also centralized ~47 ad-hoc e2e timeout budgets as `UI_TIMEOUT_MS` in the
  seam. Budgets are not assertions here — nothing measures UI speed — so a
  tight one cannot catch what a generous one misses. NOT applied to absence
  assertions, where a short timeout IS the assertion.

  Honest scope carried into the CHANGELOG: the no-op fixes are proven
  root-cause work; the budget change is unproven hardening.

- **2026-08-23 (later) — v0.24.2: a dropped-notification bug the flaky CI was
  hiding.** The pre-push gate rejected a docs/CI commit on
  `test_run_loop_handles_two_records_with_identical_delivered_date`. It passed
  3/3 in isolation in 14ms, so the cause was not slowness: the monitor never saw
  the second record.

  **Root cause** — `divoom_client/macos_notifications.py` polled with
  `WHERE delivered_date > ?` against a cursor it advances as it goes. Ties
  WITHIN a batch are harmless (the query already returned them), which is why
  this survived ~2900 runs. ACROSS batches, a record arriving later that ties
  the cursor can never satisfy `>` and is dropped for the monitor's lifetime.
  Fixed by breaking ties on stable identity (`>=` + a rowid set at the cursor
  timestamp) — a timestamp alone cannot be exact in both directions.

  The test's own docstring already stated the correct behaviour; the code never
  implemented it, and the test only reached the branch by luck. It now forces
  the interleaving, so it takes the path every run.

  Also: migrated CI off the deprecated Node20 actions (checkout@v4 /
  setup-python@v5 -> @v7), and retired the last "CI is down" claims from
  `.githooks/pre-push`, `scripts/ci_local.sh`, `docs/PLANNING_ROUND66.md`.
  **The load-bearing fact, now in AGENTS.md: this repo is PUBLIC, so GitHub
  Actions on standard runners is FREE — no credits are consumed here, whatever
  the account's private-repo balance.** That belief has now outlived the fact
  twice; the last time, v0.23.0 shipped on a red CI.

- **2026-08-23 — flaky-CI round. Four findings, none of them flakiness.**
  Suite: **Python 2920 / 0 failed / 0 errors / 94 skipped** (+10 new);
  Rust workspace green; `ci_local.sh --fast` all jobs pass. Detail in CHANGELOG.

  1. **`control_server` early error replies did not drain the request body**
     (real shipping bug, not a test problem). Three branches in `do_POST`
     answered above the `rfile.read()`; the close RSTs and the client's next
     write dies with EPIPE before it can read our status code. Any client
     POSTing with a bad token can hit it. Fixed as a class in `_send()`.
  2. **The e2e browser guard was conventional, not structural.** 13 of 15
     modules called `require_browser()`; the two sync-API ones did not, so a
     missing browser errored them while the rest skipped. The guard now lives
     inside `launch()`/`launch_sync()`.
  3. **The guard suite's own bail-out** used `if not installed_verstr()`, but
     that function RAISES when nothing is fetched. Same class, one function over.
  4. **`camoufox fetch` exits 0 when it installs nothing.** A GitHub API rate
     limit produced a green step and no browser. `GITHUB_TOKEN` kills the cause;
     `tools/check_camoufox_installed.py` kills the silence.

  Method note worth keeping: the first body-drain test ran on **TCP** and passed
  with the fix REMOVED. The defect only reproduces on **AF_UNIX**. A test written
  against the wrong transport is a green light bolted over the bug — measure the
  instrument before trusting the reading.

- **2026-08-17 (Round 66) — repo restructure + gate repairs. RELEASED v0.23.0.**
  Layout round; net **-14,240 LOC**. Suite: **Python 2910 / 2816 passed / 0
  failed / 94 skipped; Rust 119 passed** across the workspace (was divoomd-only
  before this round). Full detail in `docs/PLANNING_ROUND66.md` + CHANGELOG.

  1. **Dead code out (~12.6k LOC):** `native-port/spike-ble/`,
     `divoom_menubar/` (the pyobjc menubar — still listed in setup_app.py AND
     pyproject, so every DMG shipped a menubar that never ran), and `archive/`
     (the 2026-07-13 Python daemon server). Removing `archive/` also retired
     the `pytest.ini --ignore=archive` workaround.
  2. **One Cargo workspace** (root `Cargo.toml`, `exclude = ["references"]`,
     one lock, one repo-local `target/` pinned by `.cargo/config.toml`).
  3. **`native-port/` retired** → `divoom-menubar/` + `scripts/codegen/`.
  4. **`divoom_daemon/` → `divoom_client/`** (159 refs). It held no daemon.
  5. **64-bit only; macOS is Apple silicon only.** Hard-fail gate + 10 tests.
  6. **e2e suites moved Chromium → camoufox** behind one seam
     (`tests/support/browser.py`).

  **Six gates were reporting success while checking less than claimed** — all
  invisible to a green suite. This was the round's real value:
  - `divoom-menubar` had **never been formatted**; CI and the pre-commit hook
    both scoped to `divoomd`. Both now gate the workspace root.
  - `native_encode.rs`/`spp.rs` counted 4 parents up from the binary to find the
    repo root. The workspace moved it one level shallower — silent degradation
    (Option -> None), not an error. Fixed as a class in `divoomd/src/paths.rs`.
  - The e2e `importorskip` guard checked the module, not the browser binary —
    that is why this round's first baseline showed 69 "failures".
  - `build_libdivoom.sh`'s arch `*)` fallback warned and built anyway.
  - Two e2e tests waited on a proxy DOM signal and asserted on a different one.
  - `ARCHITECTURE.md` still said `divoom_daemon/` owned the device, ~5 weeks
    after the Rust cutover, while `AGENTS.md` sends every agent to read it.

- **CI IS BACK UP (2026-08-23).** This supersedes the "credits are exhausted"
  state that stood from 2026-08-17: `a7a699f` re-enabled `tests.yml` and it runs
  green on `main`. A red check is a code signal again — read the log, never
  assume billing (that assumption is what shipped v0.23.0 on a red CI).
  `ci_local.sh` remains the pre-push gate and still mirrors `tests.yml`
  job-for-job, but it runs on THIS machine only, so Linux-only failures in
  `rust-core`/`rust-ble-linux` stay structurally invisible to it. The pre-commit
  hook is NOT a substitute (staged files only, no tests). See `AGENTS.md`.

- **2026-08-02 (Round 65) — house Rust gate + v0.22.21 release.** Shipped + released:
  1. Wired the house Rust gate into CI + pre-commit (`cargo fmt --check`, clippy
     `--all-features -D warnings`, `tools/check_no_allow.py`); ~53 warnings fixed,
     #[allow] sites removed, 9 over-500-line files split, one-time `cargo fmt`.
  2. CI fix: the `rust-core` job's `cargo clippy --all-features` pulls `ble` →
     btleplug → dbus on Ubuntu; added `libdbus-1-dev pkg-config` install step.
  3. **RELEASED v0.22.21** via `scripts/release.sh` — re-cut the tag at HEAD (the
     first tag pointed at a pre-bump commit), built `dist/Divoom-v0.22.21.dmg`,
     created the GitHub release with the DMG (40MB), bumped the Homebrew cask to
     v0.22.21 + sha256. Install: `brew install --cask ztomer/tap/divoom-control`.
  4. **NEW RELEASE RULE (structural):** a release may only be cut when GitHub CI
     is green for the tagged commit. `release.sh` preflight `ci_gate` checks the
     commit's check-runs and aborts on red/pending/unverifiable CI; the sole
     exception is credit depletion (auto-detected; `--skip-ci-check` overrides).
     Rule also written into AGENTS.md. `ci_gate` branch-tested (OK/FAIL/PENDING/
     CREDITS/NO_RUNS).
  5. Full suite green (102 lib+integration Rust tests; Python suite per last rounds).

- **2026-07-14 (Round 64) — gallery: decode magic 8/12, broken-image removal.
  RELEASED v0.22.20.** Four workstreams done:
  1. Detect & remove broken images — `is_black_image()` (conservative), `preview_valid()` drops
     corrupt cached previews, `<img onerror>` removes dead tiles in gallery JS.
  2. Decode magic 8 (static AES image) and magic 12 (scroll buffer) — new branches in
     `decode_cloud_frames`. `pycryptodome`+`lzallright` now declared deps (were missing —
     clean install/DMG decoded zero cloud items).
  3. Full suite green, `scripts/verify_gallery_render.py` across all 16 categories: 455 items,
     0 undecodable, 0 blank frames.
  4. Not released — user said "fix", not "ship". Cut v0.22.20 via `scripts/release.sh` when ready.

- **2026-07-14 (Round 63) — gallery black-tile fix. RELEASED v0.22.19.** Root-caused via live
  repro: `fetch_gallery_asset` now re-downloads+decodes in one call on decode failure. 3 new tests.

- **2026-07-14 (Round 62) — 7-bug batch. RELEASED v0.22.18.** Gallery cache-retry, hot-channel
  button fix, Sync Now feature, light-mode toast contrast fix, device-settings alignment fix.
  Details in git history (round plans were pruned).

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
- **Cloud HTTP**: 533/533 commands cataloged (`docs/cloud_api/`). Clock-face store wired into

## Earlier history

The full round-by-round history (R3–R64, ~2k lines) is archived at
`docs/archive/SESSION_HANDOFF_2026-07-27.md`. Recover individual rounds from
`CHANGELOG.md`, `docs/PLANNING_ROUND*.md` (current round only), and `git log`.

## Hardware note

macOS Bluetooth TCC is per responsible-process; drive real BLE by launching via
Terminal (`open *.command`). Device validation plan was in `docs/DEVICE_VALIDATION_PLAN.md`
(recover from git history if needed — removed in an earlier doc cleanup).
