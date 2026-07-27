# Round 62 — Bug batch: gallery, hot-channel sync, playlist/album push, sync-now, theming, alignment

User-reported bug batch (2026-07-14), tracked here per the round-planning
convention in `docs/ROADMAP.md`. Investigated with 3 parallel Explore agents
+ direct/live reads (including a live repro against the real Divoom cloud
API and this machine's actual `~/.config/divoom-control/cache_gallery`).

## Bugs

1. **Pixel art gallery is broken — most images don't render.**
2. **Can't sync the hot channel — the Sync button is not actionable.**
3. **Playlist — no way to push a playlist to the device.**
4. **Photo album — no way to push a photo album to the device.**
5. **Schedule / Auto-Sync — no "Sync Now" (should push to all toggled and
   connected devices, with progress shown).**
6. **Light mode — bottom-right popups render black-on-black, unreadable.**
7. **Device settings (clock format / temperature / power mode) — the
   button groups are center-aligned; should be right-aligned.**

## Findings

- Local `main` was 1 commit behind `origin/main` — `0d513a5`
  ("WiFi/LAN command completeness; live 'not in range' device chip",
  released as v0.22.17) was already merged by another session and ships
  **Photo Album push end-to-end**, fixing #4 for free. Fast-forwarded.
- **#3 (playlist push) is already shipped** (v0.22.15) and reads correctly
  in code (`divoom_gui/web_ui/playlists.js` + `push_playlist` in
  `divoom_gui/api/lighting.py:239`) — likely the report predates that
  release or was confused with another bug in this batch. Verified live
  during smoke-test, no code change.
- **#1 (gallery)**: root-caused via a live repro against the real Divoom
  cloud API. Two compounding bugs: (a) `download_item()`
  (`divoom_gui/gallery_sync.py`) never retries a corrupt/truncated
  cached `.bin` — confirmed live, 69/308 of this machine's actual cached
  files throw an AES-CBC padding error from a truncated download and stay
  broken forever; (b) the generic `assets/pixoo.png` fallback is used for
  both "still loading" and "permanently failed" with no visual
  distinction, so the stale-cache-first render reads as broken gallery
  art instead of a loading state.
- **#2 (hot channel sync button)**: `gallery_hot.js`'s `applyProgress`/
  `finishProgress` are closure-local but `connection_events.js`'s
  `onHotProgress` calls them as `window.applyProgress`/`window.finishProgress`
  — both undefined, so the button-reset path never runs and the button
  stays disabled after the first click, forever.
- **#5 (Sync Now)**: doesn't exist yet. Auto-Sync is schedule-only, driven
  by an external launchd process (`divoom_lib/monthly_best_daemon.py`) the
  GUI can't trigger on demand; the GUI's own "Update Hot Channel" button
  only targets the single currently-connected device. New feature, reusing
  existing daemon primitives (`connect_single_device` + `hot_channel_update`
  looped per selected target) — no new Rust work.
- **#6 (light-mode toast)**: `.toast` in `widgets_extra.css` hardcodes a
  dark background literal instead of `var(--card-bg)`.
- **#7 (settings alignment)**: the base `.tabs-row` CSS sets symmetric
  `margin: auto`, which wins over the parent's `justify-content:
  space-between` and centers the pill group instead of right-aligning it.

Full design detail lives in the session's plan file (not repo-tracked);
this doc is the durable, cross-session record. See `CHANGELOG.md` for the
shipped fixes as each lands, and `docs/SESSION_HANDOFF.md` for current
round status.

## Outcome

All 7 items resolved:

1. **Gallery** — fixed. Corrupt/truncated `.bin` cache entries now get
   deleted on decode failure so the next fetch re-downloads (was cached
   broken forever — confirmed live on this machine's real cache). Loading
   vs. permanently-unavailable placeholder states are now visually
   distinct.
2. **Hot Channel sync button** — fixed. `applyProgress`/`finishProgress`
   exposed on `window`; dead `pollProgress`/`_pollTimer` removed.
3. **Photo album push** — already shipped (`0d513a5`/v0.22.17, landed by
   another session before this round started). Verified live.
4. **Playlist push** — already shipped (v0.22.15). Verified live, no bug
   found.
5. **Sync Now** — new feature shipped. `sync_now()` bridge method +
   `sync_now.js` + per-device progress on the Auto-Sync device rows.
6. **Light-mode toast contrast** — fixed (`var(--card-bg)` instead of a
   hardcoded dark literal).
7. **Device settings pill alignment** — fixed (right-aligned to match the
   existing Orientation row pattern).

Verification: full pytest suite green (2805 passed / 96 skipped / 0
failed), `check_no_emoji.py` / `check_file_size.py` clean, 5 new tests
(each proven to fail on the pre-fix code), live app launch + Playwright
screenshots of the toast and settings alignment. Released — see
`CHANGELOG.md` and the git tag for the version.
