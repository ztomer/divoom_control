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

- **R12 user-POV visual pass**: deferred to user (needs live app + real device for screenshots).
- **Cloud HTTP**: 533/533 commands cataloged (`docs/cloud_api/`). Clock-face store wired into
  GUI. Playlist browse+push + AidSleep browse+play both shipped. `Cloud/ToDevice` remains
  unimplemented (unconfirmed semantics, no live caller).

## Earlier history

The full round-by-round history (R3–R64, ~2k lines) is archived at
`docs/archive/SESSION_HANDOFF_2026-07-27.md`. Recover individual rounds from
`CHANGELOG.md`, `docs/PLANNING_ROUND*.md` (current round only), and `git log`.

## Hardware note

macOS Bluetooth TCC is per responsible-process; drive real BLE by launching via
Terminal (`open *.command`). Device validation plan was in `docs/DEVICE_VALIDATION_PLAN.md`
(recover from git history if needed — removed in an earlier doc cleanup).
