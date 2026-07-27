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

- **2026-07-14 (Round 64) — gallery: decode magic 8/12, broken-image removal.
  NOT YET RELEASED (planned v0.22.20).** Four workstreams done:
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
  Details in `docs/archive/rounds/PLANNING_ROUND62.md`.

## Open threads / next up

- **Release v0.22.20**: confirm live gallery renders fully, then cut release.
- **R12 user-POV visual pass**: deferred to user (needs live app + real device for screenshots).
- **Cloud HTTP**: 533/533 commands cataloged (`docs/cloud_api/`). Clock-face store wired into
  GUI. Playlist browse+push + AidSleep browse+play both shipped. `Cloud/ToDevice` remains
  unimplemented (unconfirmed semantics, no live caller).

## Earlier history

The full round-by-round history (R3–R64, ~2k lines) is archived at
`docs/archive/SESSION_HANDOFF_2026-07-27.md`. Recover individual rounds from
`CHANGELOG.md`, `docs/archive/rounds/PLANNING_ROUND*.md`, and `git log`.

## Hardware note

macOS Bluetooth TCC is per responsible-process; drive real BLE by launching via
Terminal (`open *.command`). Device validation plan was in `docs/DEVICE_VALIDATION_PLAN.md`
(recover from git history if needed — removed in an earlier doc cleanup).
