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

- **CI IS DOWN — `./scripts/ci_local.sh` is the gate.** GitHub Actions credits
  are exhausted, so CI always fails: a red check is not a code signal and a
  green one is unobtainable. `ci_local.sh` mirrors `tests.yml` job-for-job. The
  pre-commit hook is NOT a substitute (staged files only, no tests). See
  `AGENTS.md`.

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

- **The R66 CI workflow changes are UNVERIFIED.** `.github/workflows/tests.yml`
  now runs the Rust jobs from the workspace root and installs camoufox instead
  of chromium. The YAML parses and every command was proven locally via
  `ci_local.sh`, but the workflow has not executed because Actions billing is
  out. **Re-check it the moment credits are restored.**
- **R66 not released.** Layout + gates only, no user-facing behaviour change;
  `pyproject.toml` stays at 0.22.21. `release.sh`'s `ci_gate` cannot verify a
  green CI while billing is out (documented credit-depletion exception).
- **`ZoneTilerWM` has an unmerged branch `drop-intel-macos`** — the house
  Apple-silicon-only policy applied there (it was the only other project still
  building universal). Merge when ready.
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
