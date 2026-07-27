# Session Handoff — read this first

**Consolidated roadmap**: `docs/ROADMAP.md` — shipped rounds, open workstreams,
and deferred items in one view. This file tracks the per-round state.

This is the **cross-agent session state**. opencode and Claude Code keep their
own conversation stores (they can't share a live session), so THIS FILE + the
git history + CHANGELOG + ROADMAP are the shared memory. Any agent (opencode or
Claude) should read this on entry and **update it at the end of every round**
(see the core rule in `AGENTS.md`).

## How to resume

- **opencode**: `opencode -s ses_184471307ffeCUHgzv9w51O0oA` (or
  `opencode export <id>` to read it as JSON).
- **Claude Code**: reads `CLAUDE.md` → `AGENTS.md` → this file, plus `git log`.
- Both: `git log --oneline`, `CHANGELOG.md`, `docs/PLANNING_ROUND*.md`.

## Current state — _update this section each round_

- **2026-07-14 (Round 64 — gallery: decode the rest + broken-image removal, NOT yet released, planned v0.22.20):** User: "fix gallery images that don't render — detect broken/remove at runtime + load time, figure out why some fail to decode, verify it doesn't happen again, iterate over all categories." Did the 4 steps.
  1. **Probe-first, full coverage.** New offscreen harness `scripts/verify_gallery_render.py` decodes every gallery asset across all 16 categories via the real `get_animated_preview` chain. First run in `.buildvenv` (no `Crypto`) → 455/455 fail `No module named 'Crypto'` (the dev box only had it in system python — masked the bug). After `pip install pycryptodome lzallright` → **29/455 fail = magic 8 (19 items) + magic 12 (10 items)**.
  2. **Why they fail (root cause, two parts).** (a) `pycryptodome`+`lzallright` were required by `decode_cloud_frames` but NOT declared deps — a clean install/DMG decoded zero cloud items. (b) `decode_cloud_frames` only handled magic 9/18/26; magic 8 (static AES image — strip 1 header byte, decrypt with the magic-9 key `78hrey23y28ogs89`/`1234567890123456` → 16×16) and magic 12 (scroll/marquee buffer `[12][scrollMode][speed:2 BE]`, strip 4, decrypt → 64×16) were never decoded. Reverse-engineered from APK `W2/b.java` (`s`/`v`) + `W2/a.java` (AES key/IV); confirmed live-decodable.
  3. **Fixes.** (a) `pyproject.toml` + `requirements.txt` now declare `pycryptodome`/`lzallright`, and `divoom.spec` force-collects `Crypto`/`lzallright` so PyInstaller bundles them (clean-install DMG has Crypto). (b) `media_decoder.decode_cloud_frames` gained magic 8 + magic 12 branches; `CLOUD_CONTAINER_MAGICS = (8, 9, 12, 18, 26)`; new `is_black_image(path)` (CONSERVATIVE: broken = unreadable/degenerate 0-size/fully-transparent; solid-color or near-black art is valid, NOT dropped — an over-strict uniform-color check was reverted after the harness showed legit dark animations). (c) `gallery_download.fetch_gallery_asset` now runs `preview_valid()` which drops a cached preview if `is_black_image` (and unlinks the `.bin`), then re-downloads+decodes it in the same pass. (d) `web_ui/gallery.js`: added `removeTile(item)`; the preview `<img>` gets an `onerror` handler that removes the tile when a broken cached preview fails to load; the decode-failed path removes the tile (was a dead `is-unavailable` skeleton).
  4. **Verify + iterate all categories.** Harness re-run across all 16 categories → **455 items, 0 UNDECODABLE, 0 blank frames**. 64 tests added/passing (`test_media_decoder_cloud.py` magic8/12 + `is_black_image`; `test_gallery_sync_coverage.py` 3 drop/redownload cases); recorded live fixtures `tests/fixtures/gallery_magic{8,12}.bin`. Full suite green (2715 passed / 94 skipped; 4 numpy-gated modules excluded on this box — pre-existing env gap). Emoji + 500-LOC gates clean. **NOT released yet** (user said "fix", didn't ask to ship; and they can re-check live). Plan: `docs/PLANNING_ROUND64.md`. Open thread: confirm live gallery renders fully, then cut v0.22.20 via `scripts/release.sh`.

- **2026-07-14 (Round 63 — gallery black-tile fix, RELEASED v0.22.19):** User bug —
  "pixel art → gallery: items have names but most are empty / black
  placeholders." Root-caused by tracing the real render path end-to-end (real
  `DivoomGuiAPI` over the e2e HTTP bridge driving the real `web_ui` in headless
  Chromium): the backend emits correct `preview_url`s, and the frontend renders
  fine when `get_animated_preview` succeeds — so the persistent black tiles came
  from a `preview_url` left empty by a `.bin` that failed to decode. The Round
  62 fix deleted the bad `.bin` but only *unlinked* it, so recovery still needed
  a second `fetch_gallery` pass (tile stayed black until the gallery was
  reopened). Fix: extracted `GallerySyncMixin._fetch_gallery_asset()` which
  drops a `.bin` that fails to decode **and re-downloads + decodes it in the
  same call**, so one fetch fully recovers every preview. 3 new unit tests in
  `test_gallery_sync_coverage.py`; gallery + media-decoder suites green (99
  passed / 2 skipped). CHANGELOG + version bumped to 0.22.19; **released**
  (commit `eb7805c`, tag + GitHub release + Homebrew cask bump all live;
  `main` pushed). The 500-LOC gate forced a split of the download/decode into
  `divoom_gui/gallery_download.py` (`fetch_gallery_asset`);
  `GallerySyncMixin._fetch_gallery_asset` now delegates to it.

- **2026-07-14 (Round 62 — user bug batch, released): gallery cache-retry
  fix, hot-channel button fix, Sync Now feature, light-mode toast fix,
  device-settings alignment fix.** User filed 7 live bugs; see
  `docs/PLANNING_ROUND62.md` for the full findings and `CHANGELOG.md`'s
  Unreleased-turned-versioned entry for what shipped. Highlights:
  - Local `main` was 1 commit behind `origin/main` — fast-forwarded first
    (`0d513a5`/v0.22.17, already shipped Photo Albums end-to-end).
  - Playlist push and photo album push were both already working
    end-to-end; verified live, no code change.
  - Gallery ("most images don't render"): root-caused via a **live repro
    against the real Divoom cloud API and this machine's actual
    `~/.config/divoom-control/cache_gallery`** — a truncated/corrupt
    download's `.bin` was cached forever and never retried (confirmed:
    AES-CBC padding errors on real cached files). Fixed in
    `gallery_sync.py::download_item`; also gave the "still loading" state
    a placeholder distinct from "permanently unavailable" (both used to
    render the same static Pixoo logo).
  - Hot Channel "Update" button stayed disabled forever after one click —
    `gallery_hot.js`'s `applyProgress`/`finishProgress` were never exposed
    on `window`, so `connection_events.js`'s event-driven
    `onHotProgress` silently no-op'd the reset path.
  - New **Sync Now** (Routines > Auto-Sync): `sync_now()` bridge method
    sequentially connects+syncs every toggled target device, reusing
    `connect_single_device` + the existing single-device `hot_update`
    daemon call (no new Rust work), with per-device progress on the
    existing device-toggle rows.
  - Light-mode toast contrast + device-settings pill right-alignment: both
    small CSS fixes.
  - Local dev fix: `pytest.ini` now also excludes `.claude/` (other agent
    sessions' worktrees on this shared-tree project caused an "import file
    mismatch" collection abort local-only; CI unaffected).
  - Full suite green: 2805 passed / 96 skipped, 0 failed (5 new tests: 1
    gallery decode-retry unit test + 2 hot-channel-button e2e + 2
    sync-now e2e — all proven to fail on the pre-fix code before
    verifying green).
   - **Released as v0.22.18** (user: "cut a release"). Tag `v0.22.18`
     pushed, GitHub release + DMG published
     (https://github.com/ztomer/divoom_lib/releases/tag/v0.22.18), Homebrew
     cask bumped to 0.22.18. Local `main` was already the v0.22.18 commit
     (`9482899`, 1 ahead of `origin/main`); no code change this round — only
     the tag/release/cask.
   - **CI fix (follow-up, same day): the `tests` job was RED on the v0.22.18
     tag + the handoff/docs push.** One failure:
     `test_e2e_sync_now.py::test_sync_now_progress_updates_the_right_device_row`
     — 30s timeout waiting for `.sync-now-row-status[data-addr="AA:BB"]`.
     Root cause: `gallery.js`'s `setTimeout(updateSyncTargetList, 1500)`
     fired on the slow CI runner and re-rendered the sync-targets list with
     the test's mock `get_sync_candidates` response (`'{}'`), which
     `renderSyncTargets` treated as a non-empty list, cleared `#sync-targets-list`,
     then threw on `({}).forEach` — wiping the rows the test had just created.
     Locally the test finished under 1500ms, so it never hit it. Fixes (commit
     `d3389b7`): (1) the test mock now returns a real candidate array for
     `get_sync_candidates`; (2) the render+progress-fire+read are collapsed
     into one synchronous `evaluate` so the auto-refresh timer can't race it;
     (3) `renderSyncTargets` now guards `Array.isArray` so a stray `'{}'`
     clears the empty-list message instead of throwing. The other 9 failures
     in the full run were pre-existing resource-contention flakiness in
     `test_daemon_connect_edge_e2e.py` (documented in R61) — they pass in
     isolation both with and without the change. Re-ran `tests` on `main`:
     all 5 jobs green (run 29361659806). Not re-released (the failing test is
     test-only; the shipped v0.22.18 DMG is unaffected).

- **2026-07-14 (CI fix): the `tests` GitHub Actions workflow is green again.**
  Every push since `046cdf8` (Python daemon archived) had a red `tests` job.
  Root cause: `archive/tests/conftest.py` shipped beside the live
  `tests/conftest.py` and both register `--run-hardware`, so bare `pytest`
  aborted collection (`option names {'--run-hardware'} already added`) before
  running a single test — the other 4 jobs were green the whole time. Fixes,
  in order (each surfaced the next, since the collection abort had masked
  every downstream failure):
  1. `pytest.ini` — exclude `archive/` from collection (`--ignore=archive` +
     `norecursedirs`); it is retired reference-only code (commit `af37222`).
  2. `tests/test_e2e_gui_daemon_connect_disconnect.py` — the two
     `mock_simulate_drop` e2e tests now skip (not hard-fail) when the native
     daemon reports the command missing; they already skip in CI for want of
     Playwright, but hard-failed for any dev who has it (`af37222`).
  3. `tests/test_audio_visualizer.py` — module-level
     `pytest.importorskip("pyaudio")`; it hard-imported pyaudio (absent in CI,
     no PortAudio), 7 errors (commit `8aa15d1`).
  All 5 jobs green on `8aa15d1` (run 29326562142). Local full suite: 2767
  passed / 94 skipped / 0 errors.

  **Then wired the e2e + audio suites INTO CI** (user follow-up): the `test`
  job now `brew install portaudio` + `pip install pyaudio playwright` +
  `playwright install chromium`, so the audio-visualizer suite and the
  JS-mock Playwright e2e suites (aid_sleep, clock_faces, playlists,
  ux_feedback, mock_device, status chips/dot) run for real in CI. Two follow-on
  fixes were needed, each found by pushing and reading the runner:
  - `_IsolatedStack._wait_for_http` 5s → 30s + dump bridge stdout/stderr on
    timeout (the diagnostic that revealed the next item).
  - The ONE bridge-based file (`test_e2e_gui_daemon_connect_disconnect`) spins
    up the REAL `DivoomGuiAPI`, whose import does `import webview` (pywebview) —
    Cocoa init HANGS on the headless runner (no Aqua session). It now skips on
    `CI`/`GITHUB_ACTIONS` and still runs locally. This is a hard limit of
    hosted runners, not a fixable test.
  Green on `17ce5f9` (run 29331997523): **2719 passed / 107 skipped / 0
  errors**. Remaining follow-up (not blocking CI): the native daemon still
  doesn't implement `mock_simulate_drop` (its 2 tests skip); if it grows the
  command, guard converts to a real run. The GUI-bridge suite is local-only by
  necessity.

- **2026-07-14 (later still): WiFi/LAN command completeness pass; live
  "not in range" device-chip fix.** User: "cut a release" (v0.22.16
  shipped), then "how many functions are wifi related? we can add the
  support for that" — plus a bug report mid-conversation ("chips show, but
  never say 'not in range'") that got resolved into a real fix first.
  - **Chip badge fix (found via user report, not the WiFi count ask).**
    Traced `device_selector.js`'s `mergeDiscoveredDevices`: the "not in
    range" badge was seeded once at session-restore (`unconfirmed: true`)
    and cleared by the first scan hit, but nothing ever downgraded a
    device that was confirmed present THIS session and later genuinely
    dropped out of range — the union-only merge (R46 #5) never removes an
    address on a scan miss. Fixed: counts consecutive scan misses per
    address, downgrades after `MISS_THRESHOLD=2` in a row.
    `daemonOwned`/streaming devices are exempt (they intentionally don't
    advertise, so a miss there is never "absence"). 5 new e2e tests in
    `test_e2e_device_status_chips.py`; proved the key test could fail
    (bumped the threshold to 999, watched it red, restored) before
    trusting it green.
  - **WiFi command count**: exactly 45 total, from `HttpCommand.java`'s
    `DeviceAndServerCmd` (43) + `ForceDeviceHttp` (2) routing arrays —
    the commands Divoom's own app posts to the device's local WiFi HTTP
    API instead of the cloud. 10 were already implemented before this
    round. User picked all 4 remaining clusters (asked via
    `AskUserQuestion`, multi-select, all 4 chosen):
    1. **Photo album management — DONE, live, GUI-wired.**
       `Photo/GetAlbumList` (new `divoomd/src/cloud_photo.rs` — cloud.rs
       and cloud_category.rs were both full) browses albums; `Photo/
       PlayAlbum` (LAN) plays one. New "Photo Albums" 5th sub-tab in the
       Pixel Art panel, same shape as Playlist/AidSleep. Also implemented
       the other 4 CRUD commands (`SetAlbumCover`/`DeletePhoto`/
       `RemovePhotoFromAlbum`/`DevicePhotoToAlbum`) plus `GetPhotoList`
       at the plumbing layer only — full photo-level management needs a
       thumbnail UI, out of scope this round.
    2. **LAN-getter completeness — DONE, backend only** (no GUI needed,
       these are internal state reads): 8 read-back counterparts of
       already-BLE-working Set commands, now also reachable over LAN.
    3. **Channel extras + Voice/SendText — DONE, backend only, NOT
       GUI-wired.** 5-LCD "Times Gate" multi-panel commands need
       hardware this project has no reason to own.
       `Voice/SendText` specifically needs real-hardware render
       confirmation before it's trusted — the exact same trap
       `push_text` already fell into and climbed out of (R32 §D: a
       superficially-similar "set light phone word" 0x87 BLE opcode
       ACKed cleanly but never actually rendered on Pixoo-class
       matrices; `push_text`'s fix was to render to a bitmap and push it
       as an image instead). Implemented but deliberately not surfaced.
    4. **Danmaku scrolling overlay — DONE, backend only, NOT GUI-wired.**
       Same unconfirmed-render caveat on `SendText`; `RandomFace` has a
       real request class but zero confirmed callers anywhere in the
       decompiled app — may be dead server-side.
  - **File-size gate hit repeatedly** as commands piled up:
    `divoomd/src/device_call/mod.rs` split into a new `device_call::lan`
    module (`handle_lan_call` + its helpers, ~250 lines); Python
    `lan_transport.py` split into `lan_transport_photo.py`/
    `lan_transport_extras.py` mixins; `divoom_gui/gui_api.py` split its
    one-line `LightingApi` forwarding methods into a new
    `lighting_forward.py` mixin (`LightingForwardMixin`). All four
    follow the same mixin-split pattern already established for
    Playlists/AidSleep/PhotoAlbums.
  - **Caught a real regression from the gui_api.py split**:
    `test_round6_layout_and_exposure.py::test_gui_api_exposes_set_volume_and_get_volume`
    grepped `gui_api.py`'s raw source text for a literal `def
    set_volume(...)`, which broke when that method moved into the new
    mixin file — fixed the test to check both files' source (kept the
    file's established "static analysis only, no live import" convention
    rather than switching to runtime introspection).
  - Verified: full `tests/` suite green (see CHANGELOG for the exact
    count — re-ran after the gui_api.py mixin-split regression fix above);
    `cargo build`/`cargo test` clean in `divoomd`;
    `check_no_emoji.py`/`check_file_size.py` gates clean. Bumped to
    v0.22.17. **Not pushed or released this round** — committed locally
    only; ask before releasing, per the user's established pattern (this
    round's earlier v0.22.16 WAS released, on explicit "cut a release").

- **2026-07-14 (later still, `/loop`-continued research): AidSleep RC=3
  fixed and shipped; cloud API catalog now 533/533 complete.** User: research
  the AidSleep RC=3 mystery and finish the `misc_small.md` batch, then
  implement whatever comes out of it, loop until done — "if it's not
  possible, I guess we're done" was the explicit acceptance criterion for a
  genuine dead end. It was NOT a dead end.
  - **Systematic re-investigation of AidSleep RC=3** (deeper than the prior
    round's pass): tried every request-shape hypothesis exhaustively — guest
    vs. real-login accounts, every `BaseLoadMoreRequest` field, `DeviceId`
    0/omitted/placeholder, `Type` 0/1/2, `GetAllList` vs. `GetMyList`,
    0-/1-based paging — all identical `RC=3`. Traced `BaseParams.postSync`'s
    routing and `OkHttpUtils.checkServerPath`/`checkIsDivoom` line-by-line:
    transport byte-for-byte identical to the working `Playlist/GetMyList`
    call. The decisive datapoint: a live `Device/GetListV2` call showed the
    account has **zero devices bound server-side** — and `AidSleep/*` is
    device-scoped, unlike account-scoped `Playlist/GetMyList`.
  - **The fix, found via the `misc_small.md` research pass**:
    `BlueDevice/NewDevice` — the real app's device-registration call
    (`bluetooth/f.java`'s `applyNewBlueDevice`: `APP/GetServerUTC` for a
    signed timestamp, then `BlueDevice/NewDevice` with `UTC`/`UTCEncrypt` +
    `Type`/`SubType`, returning a real `BluetoothDeviceId`/`DevicePassword`).
    This project's `virtual_device.json` was never populated because
    nothing had ever called it. Registered one live (Type=1, SubType=1 —
    the server accepted this pair) and `AidSleep/GetAllList` immediately
    went `RC=3` → `RC=0` with a real catalog (Gentle Rain, Ocean Waves,
    Fireplace, Quiet Library, ...). Implemented as
    `divoom_auth.ensure_virtual_device` / `divoomd::cloud::
    ensure_virtual_device`: lazy, one-time registration per machine/
    account, cached to `virtual_device.json`, triggered only by the feature
    that needs it (not folded into `authenticate()`, since registering has
    a real server-side effect on the account — kept the footprint minimal).
  - **Shipped end-to-end**: BLE play/add/delete/exit
    (`divoom_lib/tools/aid_sleep.py`, already existed from the prior round)
    plus a new Rust `divoomd/src/device_call/aid_sleep.rs` module (the
    daemon had no JSON-over-BLE send path for this command family before —
    reused the existing generic `dev.send_command(command_id, bytes,
    write_with_response)` transport method, command_id=1 matching the
    decompiled `bluetooth.q#B()`). New "Sleep Sounds" sub-tab in the
    Schedule panel (3rd tab alongside Auto-Sync/Time): type-filter tabs
    (Natural Sound/White Noise/Music) + browse/Play list, backend
    `divoom_gui/aid_sleep.py` + `LightingApi.play_aid_sleep`. Verified
    visually in the Playwright-driven browser preview (tab switches, type
    filter, no console errors) and via 4 new e2e tests
    (`tests/test_e2e_aid_sleep.py`, mirroring the Playlist/clock-face
    pattern).
  - **Completed `docs/cloud_api/misc_small.md`** (the 16th and final
    catalog batch — background research agents were unreliable this round,
    got killed twice mid-run, so did the research directly instead): AI,
    BlueDevice, Dialog, FillGame, Mall, NoDevice, PowerOn, QingTing, Radio,
    Weather, Google/Outlook calendar (31 commands). **Cloud API catalog now
    533 of 533 commands documented.** `BlueDevice/NewDevice` (in this batch)
    is the AidSleep fix above. Everything else in the batch is Divoom's own
    account/social/e-commerce layer, or a different product family (WiFi
    speakers' internet radio / scheduled power-on — not the BLE Pixoo/
    Tivoo/Ditoo/Timoo displays this project targets). `Google/EnterCalendar`
    and `Outlook/EnterCalendar` are `DeviceAndServerCmd` members (LAN-routed)
    with a real caller but zero decompiled payload beyond auth — flagged as
    "thin signal," not implemented blind. `UNKNOWN_COMMANDS.md` updated (13
    of 533 zero-signal commands total).
  - Proved the new AidSleep-device-registration test can fail (stripped the
    fix, watched `test_get_aid_sleep_list_registers_a_device_when_none_bound`
    go red, restored) before trusting it green, per project discipline.
  - Verified: full `tests/` suite 2766 passed / 0 failed / 97 skipped (10
    more than the prior round's 2756 — the new AidSleep-registration tests
    in `test_cloud.py`/`test_divoom_auth_coverage.py` and 4 new
    `test_e2e_aid_sleep.py` tests); `cargo test` clean in `divoomd`; `cargo
    build` clean; `check_no_emoji.py`/`check_file_size.py` gates clean.
    Bumped to v0.22.16. **Not pushed or released this round** — committed
    locally only; ask before releasing, per the user's established pattern.
  - `Cloud/ToDevice` (the third lead from the original catalog) remains
    unimplemented — unconfirmed semantics, no live caller found, lower
    priority.

- **2026-07-14 (later, `/loop and implement`): Playlist browse+push shipped
  end-to-end; AidSleep backend implemented, not GUI-wired.** Picked up the
  prior round's open ask ("pick one of the three leads... implemented
  against real request shapes now") and did two of the three.
  - **Playlist browse+push — DONE, live, in the GUI.**
    `Playlist/GetMyList`/`GetMyImageList` confirmed RC=0 with a real account
    (`divoom_lib/cloud.py`). Push is LAN-only per `HttpCommand.java`'s
    `DeviceAndServerCmd` array (`Playlist/SendDevice` routes to the device's
    own local HTTP API, not cloud) — added `lan_transport.py`'s
    `send_playlist` + Rust `device_call`'s `lan.send_playlist`. New
    "Playlists" sub-tab in the Pixel Art panel (4th tab alongside Custom
    Art/Gallery/Hot Channel): `divoom_gui/web_ui/playlists.js` +
    `templates_pixel_art.js` markup, backend `divoom_gui/playlists.py`
    (`PlaylistsMixin`) + `LightingApi.push_playlist`. Reused the shipped
    clock-face browser's list-row/Apply-button CSS (`cloud-clock-list`/
    `-row`/`-apply-btn`) verbatim — no new CSS needed. Verified visually in
    the Playwright-driven browser preview (tab switches correctly, active
    state matches the R12-fixed translucent-tint pattern, no console
    errors) and via 3 new e2e tests (`tests/test_e2e_playlists.py`,
    mirroring `test_e2e_clock_faces.py`): list renders, "connect a device
    first" guard, Apply reaches `push_playlist` with the real `PlayId`.
  - **AidSleep — BLE commands (play/add/delete/exit) implemented; cloud
    browse NOT wired into the GUI.** `divoom_lib/tools/aid_sleep.py` reuses
    the existing SPP_JSON BLE framing unchanged (confirmed via a dedicated
    research pass: identical to the decompiled APK's `bluetooth.q#B()`,
    command_id=1, JSON payload — zero new low-level protocol code needed).
    But `AidSleep/GetAllList`/`GetMyList` reproducibly returns `RC=3`
    ("Request data is incomplete") against a real account, tried with every
    request-field permutation the decompiled request class allows (guest
    creds, forced real login, `Language`/`CountryISOCode`,
    `DevicePassword=0`) — same unresolved-server-side-validation shape as
    the earlier `Channel/StoreClockGetClassify` RC=12 case. Documented
    honestly in both `divoom_lib/cloud.py` and `divoomd/src/
    cloud_category.rs`. Per the project's "honest placeholders" rule,
    deliberately **not** surfaced in the GUI — no browse UI for a call that
    doesn't work live.
  - `Cloud/ToDevice` (the third lead) not picked up — lower priority,
    unconfirmed semantics.
  - Mid-session the user manually relayed a real Gemini design-critique
    reply after interrupting an in-progress Gemini-bridge `navigate` call
    (the reply had landed in the original chat right as/after I navigated
    to a fresh one) — no data was lost, verified every finding against
    source as usual.
  - Verified: full `tests/` suite 2756 passed / 0 failed / 97 skipped
    (16 more than the prior round's 2740, matching the new AidSleep/cloud/
    lan_transport/e2e-playlists tests added); `cargo test` clean in
    `divoomd`; `cargo build` clean; `check_no_emoji.py`/`check_file_size.py`
    gates clean. Bumped to v0.22.15. **Not pushed or released** — committed
    locally only, per the user's existing pattern of not auto-releasing.

- **2026-07-14: closed out the 5-item post-release punch list** (user gave
  terse one-line answers to each of the 5 "what's left" items from the prior
  round: "1. use gemini / 2. skip. known to work. I'll report if there are
  errors / 3. do research, search the web, if not found, write it down into
  a separate md file (unknown commands). / 4. I guess that using the actual
  device city is more or less equivalent so we don't need to change this. /
  5. split cleanly").
  1. **R12 visual pass, via Gemini** — used the `gemini-bridge` skill (Chrome
     transport) to get a real design critique of the app (screenshots of the
     dashboard/appbar/tab-strip sent to Gemini Pro). The first ~25 minutes
     produced no reply (a documented gemini-bridge failure mode — sustained
     empty reply, no quota banner); a fresh chat with the same images got a
     real reply through. Verified every finding against actual source before
     applying anything: 3 of 5 were false positives caused by the test
     screenshot itself (headless-Chromium fell back to literal `{}` glyphs
     for icon characters it couldn't render; the appbar already had
     `align-items:center`; inactive-tab-text contrast was already
     borderline-passing WCAG AA, not failing). 2 were real and fixed: the tab
     strip's active state (solid `--primary` fill + white text) didn't match
     the sidebar's own established translucent-tint pattern
     (`.nav-btn.active`) — unified them; the sidebar's device chips had a 2px
     left-alignment mismatch against the nav items — fixed by adjusting
     `.device-chips` padding. `tests/test_tabs_chrome.py` updated to match
     the new (intentional) active-state contract.
  2. **Skip** — no action (menubar D-glyph icon; user will report if issues
     surface).
  3. **Cloud HTTP endpoint research** — dispatched 16 parallel background
     research agents covering all 533 `HttpCommand.java` commands, each
     cross-referencing the decompiled APK's request/response classes with
     web search. Result: `docs/cloud_api/README.md` (full catalog + index)
     and `docs/cloud_api/UNKNOWN_COMMANDS.md` (8 of 502 documented commands
     have zero signal from either source). Surfaced 3 candidate new features
     (AidSleep browse+play, Playlist browse+push, `Cloud/ToDevice`) — not
     implemented, just documented; see `docs/ROADMAP.md`'s Cloud HTTP
     section. One batch (`misc_small` — Google/Outlook/Weather/Radio/
     QingTing/BlueDevice/Dialog/NoDevice/PowerOn/Mall/AI/FillGame, 31
     commands) was still running when this round's work was committed —
     append it + update the README's tally when it lands.
  4. **No change** — confirmed: the weather widget's existing system/OS
     location is an acceptable equivalent to a Divoom-city-search feature;
     `search_weather_city` stays implemented-but-unwired, as before.
  5. **`macos_notifications.rs` split cleanly** — pulled DB access
     (`notification_db.rs`) and routing-rule load/save/match
     (`notification_routing.rs`) into their own modules; the file itself
     keeps the monitor state/loop and device-forwarding. Pure refactor, zero
     behavior change. Clears the file-size gate (was 503 lines, one over).
  Verified: full `tests/` suite 2740 passed / 0 failed / 97 skipped (a
  concurrent full-suite run showed 2 isolated failures —
  `test_real_event_relay_degraded_then_disconnected`,
  `test_rust_spp_connect_failure_integration` — confirmed via `git stash`
  regression-isolation to be pre-existing flakiness unrelated to this
  round's changes; both pass in isolation and the suite is clean end to
  end); `cargo test` 106 passed. `check_no_emoji.py`/`check_file_size.py`
  clean.

- **2026-07-13: v0.22.13 RELEASED** (user: "commit, push a releash, tell me
  what's left"). Branch `claude/determined-curran-400d36` was a clean
  fast-forward of `origin/main` (0 behind, 3 ahead) — pushed directly to
  `main`, then `scripts/release.sh` (symlinked `.buildvenv` from the main
  checkout into this worktree, since worktrees don't share it): DMG built,
  tag `v0.22.13` pushed, GitHub release published
  (https://github.com/ztomer/divoom_lib/releases/tag/v0.22.13), Homebrew cask
  bumped + verified (`version "0.22.13"`, sha256 matches the uploaded DMG).
  Covers the daemon archival (v0.22.12) + the clock-face store fix (v0.22.13)
  in one release. Remaining open items are listed in `docs/ROADMAP.md`'s
  "Open workstreams" — all either DONE, user-driven (R12 visual pass/hardware
  verification), or blocked on user input (Cloud HTTP endpoint priorities,
  weather-city-search UX decision).

- **2026-07-13 (later same day, v0.22.13): the clock-face store actually
  works now, and it's wired into the GUI.** Continues the entry directly
  below (user provided the decompiled APK). First pass landed
  `Channel/StoreClockGetClassify`/`GetList` — correct per the APK's own
  request/response classes, but returned RC=12 live for an unresolved
  reason. User: **"wire up to the gui what we know that works. try harder
  to decompile the binary, search for references online."** Went deeper:
  read the APK's smali directly for `BaseParams._postSync` (the JADX "not
  decompiled" stub) and found it just calls `OkHttpUtils.postSyncInternal`
  — which IS fully decompiled and confirms no hidden headers/signing beyond
  `Connection: close`, ruling out a transport-level explanation. Then went
  external: found `github.com/r12f/divoom` (independent, MIT, real working
  Rust client) which documents `Channel/GetDialType` + `Channel/GetDialList`
  as Divoom's **public, unauthenticated developer API**
  (doc.divoom-gz.com/web/#/12?page_id=190) — not part of the phone app's own
  `HttpCommand.java` catalog at all. Verified live immediately: real
  category names (`Social`, `Normal`, `financial`, …) and real
  `ClockId`/`Name` data, zero credentials needed. Replaced the abandoned
  `StoreClockGet*` code entirely with this in `divoom_lib/cloud.py` +
  `divoomd/src/cloud_category.rs` (parity, daemon-dispatch wired), verified
  against a real running `divoomd` socket end-to-end (not just mocked).
  **Then wired to the GUI**: found `display.show_clock(clock=clock_id)`
  already routes large ids through `lan.set_clock()`
  (`Channel/SetClockSelectId` to the device's own LAN IP) when the device
  has WiFi — so no new device-apply plumbing was needed, just a picker UI.
  Added a "Cloud Clock Faces" browser to the existing Clock channel panel:
  category dropdown + list + Apply button, reusing the existing
  `set_clock()` GUI API verbatim (`divoom_gui/clock_faces.py` backend,
  `divoom_gui/web_ui/cloud_clock_faces.js` + `index.html` markup +
  `style_extra.css`). Verified in a real headless-Chromium Playwright run
  against the actual `index.html` (screenshots taken, visually confirmed
  matches the app's existing design language) before writing 4 permanent
  regression tests (`tests/test_e2e_clock_faces.py`): initial load without
  a tab click (Clock panel is active by default — a real gap `showChannel
  Panel()`'s click-only trigger would have missed), category switching, the
  existing "connect a device first" guard, and Apply reaching `set_clock()`
  with the correct `ClockId`. Also confirmed via `git stash` that an
  unrelated pre-existing `names.forEach is not a function` console error
  (from `scan_devices` in the Playwright mock harness) predates this work —
  not something introduced here. Full suite 2740 passed / 97 skipped;
  `cargo test` 106 passed. Version bumped 0.22.12 → 0.22.13; **not yet
  released**. The other ~225 `HttpCommand.java` endpoints remain
  unimplemented — ask is now "which ones matter for a real feature" rather
  than "we don't know the shapes."

- **2026-07-13 (earlier same day): user provided the decompiled APK**
  (`references/apk/decompiled_src/` — gitignored, exists on disk in the
  main checkout, not this worktree; readable directly by absolute path)
  in response to the Cloud HTTP "needs the user" ask below. Unblocked +
  fixed a real bug: `list_clock_faces()`/`CLOCK_FACE_CLASSIFY` was calling
  the WRONG endpoint (`GetCategoryFileListV2`, the pixel-art gallery, not
  clocks) — confirmed via `HttpCommand.java` + `WifiChannelModel.java`'s
  `R()` method that the real clock-face store is
  `Channel/StoreClockGetClassify` + `Channel/StoreClockGetList`. Fixed in
  `divoom_lib/cloud.py` + `divoomd/src/cloud_category.rs` (parity), tests
  updated (`tests/test_cloud.py`), `docs/ROADMAP.md`/`CHANGELOG.md`
  updated. Full suite 2734 passed / 97 skipped; `cargo test` 106 passed.
  **Superseded by the entry above**: live round-trip against this endpoint
  returned RC=12 (`HTTP_REQUEST_EMPTY`) — reproduced with both a real
  account and guest auth (ruled out as a token issue). Kept here for the
  investigation trail; the code itself was replaced, not just the docs.

- **2026-07-13 (this round): Python daemon server archived (v0.22.12,
  not yet released) + a "/loop non-user-dependent work" hardware pass.**
  Continuation of the same day's v0.22.11 work. Two threads:
  1. **Hardware verification (user: "/loop and finish the non-user
     dependant work. hardware is available")**: `pic_scan_ctrl` 0x35 —
     both control-mode GATT writes ACK cleanly on a real Pixoo-1
     (transport-level only, no on-device visual confirmation possible).
     Ditoo-light-2 re-verified end-to-end (cloud fetch → `sync_artwork`
     push → brightness read-back). Niche Rust-daemon subsystems
     exercised: SD-music query + drawing-pad enter/exit ACK; the 0x8e
     animation user-define read-back timed out on this Ditoo
     (inconclusive, non-destructive). Cloud HTTP (200+ endpoints)
     investigated further and reclassified BLOCKED — `CLOCK_FACE_CLASSIFY`
     probed against 7 values, none matched, but the correct shape can't
     be reverse-engineered from live probing alone; needs APK source or
     user priorities. Findings written inline at each call site
     (`divoom_lib/display/drawing.py`, `divoomd/src/device_call/{drawing,
     animation}.rs`, `divoom_lib/cloud.py`, `divoomd/src/cloud_category.rs`)
     and in `docs/ROADMAP.md`.
  2. **Python daemon archival (user: "the python daemon version can be
     archived"** — sign-off on the previously-deferred, explicitly
     irreversible Phase 5 step 5.3). Clarified scope first via
     AskUserQuestion (client vs. server code split) — user confirmed:
     keep client infra active, archive server-only code and its tests.
     `git mv`'d 13 server-only modules from `divoom_daemon/` to
     `archive/divoom_daemon/` (cross-imports rewritten to
     `archive.divoom_daemon.*`); `divoom_daemon/__init__.py` rewritten to
     document its new client-library-only role;
     `daemon_client.spawn_daemon()`'s Python-fallback branch replaced
     with a clear `RuntimeError` when no `divoomd` binary resolves;
     `cli_commands.cmd_daemon()` replaced with a stderr pointer at
     `divoomd` (returns 1). 47 test files that exercised only the
     archived server moved to `archive/tests/` (outside `pytest`'s
     `testpaths`, so excluded from default/CI runs) — 6 were split
     file-by-file (delegated to a general-purpose Agent) where some
     tests needed the archived server and others tested still-active
     client code, which stayed in `tests/`. `archive/tests/conftest.py`
     is a copy of `tests/conftest.py` so the archived suite still
     collects/runs standalone on request. `README.md`/`docs/ROADMAP.md`
     updated to declare `divoomd` the sole daemon.
     **Verified:** full `tests/` suite 2731 passed / 97 skipped (0
     failed); `archive/tests/` collects 469 tests with zero errors (not
     run by default); `check_no_emoji.py`/`check_file_size.py` clean
     (the one file-size violation, `divoomd/src/macos_notifications.rs`,
     predates this change). Version bumped to 0.22.12 in `pyproject.toml`
     + `CHANGELOG.md`; **not yet released** (no "cut a release" ask this
     round).
  Also noted, unresolved: user reported "gh fails" but gave no specific
  command/error and it wasn't reproducible in this session's `gh auth
  status` — flagged back to the user, no further action taken.

- **R61 follow-up (2026-07-13): full daemon+UI e2e connect/disconnect
  verification DONE (user-requested; "the menubar item is live... full e2e
  verification tests with daemon/ui/correctness when connecting
  disconnecting from devices with clear feedback").** Prior e2e coverage had
  a real gap: 3 Playwright files (`test_e2e_ux_feedback.py` etc.) drove the
  real `web_ui` against a fully JS-mocked `pywebview.api` (no daemon ever
  touched); 2 daemon-level files drove a real daemon with no UI and no
  socket isolation. Nothing exercised daemon + UI together. Closed in 4 parts:
  1. **Rust mock transport**: new `mock_simulate_drop` command
     (`divoomd/src/daemon_mock.rs`, split out of `daemon_connect.rs` to stay
     under the 500-LOC gate) simulates an unexpected mid-session BLE/LAN
     drop — walks the same degraded-then-disconnected broadcast a real drop
     takes, so tests can cover the "link died on its own" path, not just
     clean connect/disconnect (mock transport previously had no way to
     simulate this — `cmd_disconnect` was a clean no-op only).
  2. **New GUI-daemon e2e bridge**: `tests/e2e_gui_bridge.py` runs the REAL
     `DivoomGuiAPI` backend (`divoom_gui/gui_api.py` + `ConnectionApi`/
     `ScannerMixin`) in an isolated subprocess (HOME redirected to a
     throwaway dir, `ensure_daemon`/`daemon_alive` monkeypatched to an
     isolated socket path — never touches `~/.config/divoom-control/` or the
     default `/tmp/divoom.sock`), served over a tiny local HTTP bridge (with
     CORS support — `file://`-loaded pages need it, first version silently
     failed every fetch without it, a real bug caught by the harness itself
     mid-build). `tests/test_e2e_gui_daemon_connect_disconnect.py` drives
     the real `web_ui` against this bridge + a real (isolated, PID-tracked,
     never `pkill`) `divoomd`: mock-connect → dot goes active, drop → dot
     goes inactive via both polling AND a live `DaemonClient.subscribe()`
     event-relay thread (real degraded→disconnected broadcast shape reaching
     the real `window.Divoom.onDaemonEvent` handler), and a genuine
     `connect_single_device` FAILURE (unreachable LAN, no mock) reaching the
     toast via `get_last_connect_error`. 4/4 passing, stable across 20+ runs;
     2 isolated flakes traced to concurrent heavy `cargo build --release`
     resource contention, not a logic bug (didn't reproduce in 21 further
     runs).
  3. **Menubar device-connection feedback (new feature, not just tests)**:
     investigation found the menubar's icon previously reflected ONLY the
     macOS notification-monitor's state (`divoomd/src/daemon.rs`'s
     `get_status` → `macos_notifications::status_event()`), NEVER device
     BLE/LAN connection — a real, confirmed gap, not a testing gap. User
     chose to fix it, not just document it. Added: `native-port/
     divoom-menubar/src/state.rs` (pure `resolve_icon_state()`, priority
     offline > idle > degraded > connected, mirrors the GUI's
     `transport-dot` precedence — notif-monitor activity demoted to tooltip
     detail, no longer drives icon color), `daemon.rs::connection_state()` +
     a new blocking `subscribe()` (the menubar had zero async runtime —
     kept it that way, a plain background thread over `UnixStream` rather
     than pulling in tokio), and `main.rs` wires a `UserEvent::DaemonEvent`
     that wakes the poll loop early on a live broadcast (never touches
     `TrayIcon` off the main thread). 10 new tests (6 pure unit + 3
     integration against a fake Unix-socket daemon + 1 pre-existing),
     stable across repeated runs.
  4. **Opt-in live-hardware pass**: `tests/test_e2e_live_hardware_connect_
     disconnect.py`, gated via the existing `--run-hardware`/
     `HARDWARE_TEST_MODULES` mechanism (skips by default). Deliberately
     READ-ONLY — verifies the real daemon's `device_status`/
     `connection_state` fields are internally consistent, never issues a
     connect/disconnect against a live shared daemon (no way to tell "safe
     to disturb" from "user mid-session" from the outside). Confirmed
     correctly gated (skips without `--run-hardware`) and confirmed it
     skips cleanly (not spawn-and-touch) when no live daemon is reachable —
     the user's own live daemon/menubar/GUI processes, seen running earlier
     in this session, were no longer running by the time this was tested
     (session ended at some point mid-work; not something this work did —
     all daemon/socket isolation was verified never to touch the live
     `/tmp/divoom.sock`).
  Also fixed the file-size gate regression the mock-transport change caused
  (`daemon_connect.rs` 571 lines → split `daemon_mock.rs` out, 441 lines).
  Files changed: `divoomd/src/{daemon.rs,daemon_connect.rs,daemon_mock.rs}`
  (new), `divoomd/src/lib.rs`, `native-port/divoom-menubar/src/{main,daemon,
  tray}.rs`, `native-port/divoom-menubar/src/state.rs` (new), `tests/
  e2e_gui_bridge.py` (new), `tests/test_e2e_gui_daemon_connect_disconnect.py`
  (new), `tests/test_e2e_live_hardware_connect_disconnect.py` (new), `tests/
  conftest.py`.

  **SHIPPED: committed, tagged, released as v0.22.10** (user: "commit, tag,
  push, cut a release"). `main` had moved ahead since this was written (the
  `pkill`/RuntimeWarning follow-ups below had already landed and v0.22.9 was
  already live) — synced onto it first, resolved `CHANGELOG.md`/
  `PLANNING_ROUND61.md` conflicts by hand, reran full verification (3197
  Python passed, 0 failed, 97 skipped; `cargo test` clean in `divoomd` +
  `native-port/divoom-menubar`), then ran `scripts/release.sh`: DMG built,
  tag pushed, GitHub release published
  (https://github.com/ztomer/divoom_lib/releases/tag/v0.22.10), Homebrew
  cask bumped. `docs/PLANNING_ROUND61.md` archived to `docs/archive/rounds/`
  (round fully closed); `docs/ROADMAP.md` refreshed to match. One open
  thread carried forward: live-hardware confirmation of the new menubar
  connection-feedback feature (daemon/menubar wasn't running by the time
  the opt-in pass was ready) — tracked in `docs/ROADMAP.md`'s open
  workstreams, not lost.

- **R61 follow-up (2026-07-13): `task_0bec8493` device-loop thread-teardown
  audit DONE.** Audited every daemon/owner test fixture that spins up a real
  `DeviceOwner._device_loop()` thread — all already call `owner.stop()` on a
  guaranteed try/finally path; no missing teardown found. The real gap was
  inside `stop()`: `asyncio`'s `loop.close()` shuts its default executor down
  with `wait=False` (doesn't wait for in-flight `asyncio.to_thread()` work),
  and `stop()` never joined `self._loop_thread`. Fixed both (bounded executor
  shutdown + thread join); added a `tests/conftest.py` autouse trip-wire that
  fails loudly if a `"device-loop"` thread survives a test. Verified with two
  full 3273-test suite runs (fixed vs. clean-HEAD baseline). The fixed run's
  one unrelated failure (`test_daemon_connect_edge_e2e.py`) was isolated via
  `regression-isolate` and traced to a separate, pre-existing `pkill -9 -f
  divoomd` scoping bug (silently fails to kill the Python-daemon fallback;
  also unscoped enough to kill a real running `divoomd` elsewhere on the
  machine — confirmed one of the user's own processes was at risk during this
  session's test runs, though it was found alive and untouched afterward).
  Two follow-ups filed: `task_4b6f060a` (scope that pkill to its own PID),
  `task_ff25dadc` (unrelated RuntimeWarning cleanup). Files changed:
  `divoom_daemon/device_owner.py`, `tests/conftest.py`. Not yet committed.
  See `docs/PLANNING_ROUND61.md` §1 and `CHANGELOG.md` for full detail.

- **R61 in progress (2026-07-12/13), running under `/loop` per `docs/PLANNING_ROUND61.md`
  — items 0→5 in order: doc cleanup, 95% coverage, cloud API, loose ends, device
  detect/connect verify, release.** Item 0 (doc cleanup) DONE (see below). **Item 1
  (95% coverage) DONE — TOTAL 69% -> 96%, exceeding target.** First unblocked a
  **full-suite pytest crash** — `tests/test_spp_integration.py::
  test_spp_not_routed_for_unknown_protocol` let a real `BleakClient.connect()` reach
  macOS CoreBluetooth (no device at the fake test address), SIGABRTing the whole
  interpreter under TCC (the known [[divoom-ble-tcc-harness-limit]] class, but this
  specific test should never have touched real hardware — fixed by patching
  `divoom_lib.divoom.BleakClient` at the correct call-time import site, commit
  `e26fc6d`). Then four waves of parallel coverage agents (Agent tool, not Workflow)
  closed the gaps: wave 1 (`a15a628`) 69%->76% (6 files); wave 2 (`11d5beb`) 76%->83%
  (9 files, incl. `gui_main.py`/`audio_visualizer.py` with 2 narrow justified
  `# pragma: no cover` lines); wave 3 (`504e2c3`, partial — 6/8 agents hit the
  account's session/usage limit mid-task, salvaged + fixed what was left) 83%->90%
  (8 files); wave 4 (`cdd52ce`) 90%->**96%** (18 files). Along the way: found + fixed
  a real bug in `divoom_daemon/command_queue.py` (a cancelled queue item's coroutine
  was never `.close()`'d — reordered so it always runs); root-caused (partially) and
  fixed a genuine flake in `test_owner_art_coverage.py` that reproduced 3/3 times
  under the FULL 3273-test suite but never in isolation (loosened the assertion to
  the real invariant, filed follow-up `task_0bec8493` to audit device-loop thread
  teardown across the daemon test suite — needs dedicated tracing, not static
  reading). Full suite: 3191 passed, 0 failed, 92 skipped. **No `omit`/exclude-lines
  config needed** beyond the two inline pragmas. See `docs/PLANNING_ROUND61.md` for
  the full waved breakdown and commit hashes.

  **Item 0 (doc cleanup) detail:** committed 4 uncommitted "R61 coverage push" test
  files found on entry (86 tests, green); untracked the stray `.coverage` binary
  artifact; archived 9 fully-shipped `PLANNING_*` docs to `docs/archive/` (rounds
  57-60, BLE/socket hardening, daemon ownership, native-port hardening, next-phase,
  arch-gap-scan, native-UI parity — all cross-checked shipped before moving, `git mv`
  to preserve history); fixed a stale "TODO: not implemented" claim in
  `CUSTOM_CHANNEL_VS_APK.md` for 6 rows that are actually shipped; refreshed
  `ROADMAP.md`'s planning-doc index + added the inline-styles migration remainder as
  a live backlog line. `docs/` top level down from 25 to 14 files. Deferred:
  trimming `SESSION_HANDOFF.md`'s history (this file) — held off while still
  actively appended to mid-round; revisit once items 2-5 close.

  **Item 2 (finish cloud API work) DONE (commit `249743c`).** Auditing Python
  `divoom_lib/cloud.py` vs Rust `divoomd/src/cloud_category.rs` for parity found a
  real gap: `fetch_gallery`/`get_category_file_list` (Rust) already retried once on
  RC 9/10/11 ("token expired") with a forced credential refresh, but
  `search_weather_city` (both languages) and Python's `get_category_file_list`
  didn't — an expired token would hard-fail those calls instead of self-healing.
  Fixed both languages; `cloud.py` now 100% covered (11 tests, up from 6); `cargo
  check` clean. One item explicitly NOT resolved: `CLOCK_FACE_CLASSIFY = 0` carries
  a pre-existing "VERIFY against the APK" comment in both languages that this
  session couldn't verify (no APK decompile source or live cloud credentials
  available) — left as documented, unverified, not a regression.

  **Items 3 (loose ends) + 4 (device detect/connect verification) BLOCKED — need
  the user.** No `divoomd` running, no `/tmp/divoom.sock`, and this shell can't
  itself spawn a BLE-scanning process (macOS TCC SIGABRTs it — the standing
  [[divoom-ble-tcc-harness-limit]]). Both items need the user to start the daemon
  (GUI or standalone) so a session can drive scan/connect over the socket or the
  UI. Stating that plainly per PLANNING_ROUND61.md rather than faking a result.
  Everything else NOT gated on live hardware is done: Timoo re-verify is tracked
  in `ROADMAP.md`; no other undocumented loose end found; the R12 visual/hardware
  arc was already correctly marked user-driven before this round.

  **UPDATE (same session, later): the user started the real app** (`divoom_gui.
  gui_main` + release `divoomd` + `divoom-menubar`), unblocking items 3-4.
  **Item 3 (Timoo re-verify) DONE, hardware-confirmed:** scan found Timoo-
  light-4; connected; `sync_artwork` fetched + decoded a real cached cloud file
  and 0x8B-streamed it via `display.show_image` (`success:true`); post-push
  `get_brightness` read back 60 (unchanged) — no device-stick. One transient
  disconnect between connect and push (reconnected clean on retry — Timoo's
  known marginal BLE range, not a new bug). **Item 4 (device detect/connect)
  DONE on the daemon side** (same socket-driven scan/connect/read-back/
  disconnect sequence); **UI side NOT directly confirmed** — the user denied
  `request_access` for their own live Divoom app (reasonable), so no
  screenshot/click walkthrough of the packaged UI was taken; the UI's
  rendering logic IS covered by 10 Playwright E2E tests exercising the real
  `web_ui` JS, but that's not a substitute for watching it on screen.
  Remaining loose end (R60 show_clock visual pass) stays user-driven, as does
  the daemon-down-banner regression check (skipped rather than kill the
  user's live daemon mid-session).

  **Also shipped while the app was live:** the user reported the sidebar's
  device list gave no clear signal of which of 4 known devices were actually
  online (3 were, 1 wasn't) — fixed in commit `2d0a845`: known-but-undetected
  chips now carry an explicit "not in range" badge + tooltip instead of just a
  55%-opacity fade (which was too subtle to read at a glance). Extended the
  existing Playwright E2E test to cover it.

  **Item 5 (cut a release) — DONE, RELEASED as v0.22.9.** User said "ship it."
  Pre-flight: `git merge-base --is-ancestor v0.22.2 HEAD` (latest published GH
  release) passed, plus all local interim tags v0.22.3-8 confirmed as ancestors
  — no divergence. Bumped `pyproject.toml` 0.22.8->0.22.9; added a `## v0.22.9`
  CHANGELOG header (consolidating the round's unversioned R61 sections above it
  for `scripts/release.sh`'s note-extraction, which pulls everything down to the
  last published release v0.22.2 — a "catch-up" release by the script's own
  design, appropriate here since R57-R61 were all interim-tagged but never
  published as GitHub releases). Ran `scripts/release.sh`: DMG built
  (`dist/Divoom-v0.22.9.dmg`), tag pushed, GitHub release created. The
  Homebrew-cask-bump step hit a one-off `gh api` JSON-parse hiccup (not
  reproducible on manual retry seconds later); re-ran with `--skip-build`
  (idempotent) and it completed clean. Cask bumped in `ztomer/homebrew-tap`;
  `brew style --fix` caught a pre-existing (not new) trailing-newline nit,
  fixed + pushed (`ce090c4`); `brew audit --cask ztomer/tap/divoom-control`
  clean. Release: https://github.com/ztomer/divoom_lib/releases/tag/v0.22.9

  **R61 COMPLETE — all 6 items (0-5) closed.** Full breakdown, all commit
  hashes, and the honest exceptions (show_clock visual pass + `CLOCK_FACE_
  CLASSIFY` APK verification remain user-driven/unverified, not regressions)
  are in `docs/PLANNING_ROUND61.md`.

- **Follow-up (2026-07-13): test-noise fix in `tests/test_owner_live_coverage.py`.**
  Two tests that point `DeviceOwner._loop` at a closed event loop to verify
  `owner_live.py`'s `live_job_stop`/`stop_all_live_jobs` swallow the
  `asyncio.run_coroutine_threadsafe()` `RuntimeError` cleanly were tripping a
  `RuntimeWarning: coroutine '...' was never awaited` at teardown — harmless
  but could mask a real un-awaited-coroutine bug later. Fixed in `owner_live.py`
  by capturing the coroutine in a local before scheduling and calling
  `coro.close()` only in the branch where `run_coroutine_threadsafe()` itself
  raised synchronously (closed/dead loop, so the coroutine was never wrapped
  into a Task) — not on a `.result(timeout=...)` timeout, where the coroutine
  is already owned by a running Task and closing it out-of-band would be
  unsafe. Verified with `pytest tests/test_owner_live_coverage.py -q -W
  error::RuntimeWarning` (26 passed, no warnings); full suite 3171 passed, 108
  skipped, 9 pre-existing failures unrelated (the `test_daemon_connect_edge_e2e.py`
  / `test_control_server.py` tests that need a real daemon process — reproduced
  identically on clean `HEAD`, confirming the known [[divoom-ble-tcc-harness-limit]]
  and not a regression).

- **R60 open-thread verification (2026-07-12) — DONE + checkpoint `v0.22.8` (user
  drives the release).** Roadmap
  `docs/PLANNING_ROUND60.md`: #1 (docstring strip) DONE; #4 (durable
  device_call parity test) DONE at v0.22.4 — the test caught 15 key-alias gaps
  (`system.*`/`sound.*`/`device.get_work_mode` prefixes) now closed with alias
  arms in `device_call/mod.rs` + submodules; #6 (Phase-5 archive docs) DONE at
   v0.22.5 — Python daemon marked REFERENCE/FALLBACK, kept (`DIVOOM_USE_RUST_DAEMON=0`);
   #3 APK `C2()` canonical established (v0.22.6) — `show_clock()` overlay bytes
   (pos 4,5,6 = `weather,temp,calendar`) diverge from canonical
   `humidity,weather,date`, but the fix + the plan's visual kill-criterion need the
   user-driven hardware loop (BLE scans here abort the interpreter per `conftest`).
   #5 get_* read-back timeouts audited (v0.22.7): bounded + cached in both Python
   (`ble_reads.read_with_retry` 2.5s + last-good cache) and Rust (every `get_*`
   uses `ctx.timeout`; daemon wraps each call in `tokio::time::timeout` 30s
   clamped [1,120]). #2 (cloud-decode device push + no-stick, 3/4 devices — Timoo
   offline), #3 (show_clock realigned to APK C2() canonical `[0x00, t, style,
   0x01, humidity, weather, date, R,G,B]` + wire-byte test + device accept), #7
   (Ditoo Tier B soak) all DONE in v0.22.8, driven from this shell (BLE works;
   `conftest` abort does not occur here). **Roadmap complete (remote-verifiable
   parts).** Caveats: Timoo-light-4 not in BLE range; physical-screen visuals are
   user-POV. Interim tags `v0.22.3`…`v0.22.8`. No release yet — user drives the
   release after satisfaction.
- **Follow-up (2026-07-13):** (1) Investigated the red `tests` CI workflow — one
  deterministic failure: `tests/test_gui_api.py::TestDivoomGuiAPI::
  test_connect_single_device` mocked `self._daemon_client` but `connect_single_device`
  routes through `self._client()` → `reconnect_daemon()` (R57) which resets the
  client and re-runs `ensure_daemon()`, hitting a real daemon (timeout). **FIXED**
  by patching `divoom_gui.daemon_bridge.ensure_daemon` (the seam the sibling
  `reconnect_daemon` tests use). Pre-existing (R47), not an R60 regression. (2)
  Event-driven audit: the daemon (`divoomd`) is fully broadcast/subscribe
  (`status`/`owned_devices`/`hot_progress`/`degraded`), no poll loops; the 4s
  `refreshConnectionState` heartbeat is no longer scheduled (R59). Only legit
  external-data polls remain (`widgets.js` weather/stock/sysmon/music) + one
  dead-code `pollProgress` in `gallery_hot.js`. (3) Roadmap leftovers: R60's 7
  items complete (remote-verifiable); loose ends = Timoo-light-4 re-verify #2,
  user-POV physical visuals, and the two long-deferred arcs (Cloud HTTP round;
  R12 visual/hardware). Committed (no new tag — pending user release).
- **EVENT-DRIVEN UI (R59, 2026-07-12) — DONE + HARDWARE-VERIFIED; shipping as v0.22.2.**
  The dashboard learned daemon/device state by **polling on 4s heartbeats** (connection,
  owned-devices, daemon-health) + 5s notif-status + 600ms hot-progress — flaky/laggy. This
  round makes the daemon **push** that state and the UI **listen**. (1) **Honest, complete
  `status` events** — connect/disconnect now carry `connected` + `mac`/`lan_ip` (was only
  `state`/`counters`). Fixed the **subscribe snapshot lie**: a new subscriber got a hardcoded
  `idle` even when a device was connected; `initial_status` now reports the daemon's *actual*
  `connected`+`mac`/`lan_ip`. (2) **`owned_devices` broadcast** on connect/disconnect replaces
  the 4s `get_device_activity` poll. (3) **`notif_status` is now a distinct event type** — the
  macOS monitor used to broadcast `type:"status"` and collide with the connection event (would
  wrongly flip the connection dot); now `type:"notif_status"`, replacing the 5s poll. (4)
  **`hot_progress` broadcast** (`starting`/`done`/`error`) replaces the 600ms poll. (5)
  **Link-health is event-driven** — `cmd_device_call` broadcasts `status` `degraded` on a
  failed/timeout op and recovers to `active` on success. (6) **GUI subscription forwards every
  event** to the web UI (`_make_daemon_event_handler` → `window.Divoom.onDaemonEvent` /
  `onOwnedDevices` / `onNotifStatus` / `onHotProgress`) and **detects daemon-down via socket
  closure** (`onDaemonDown`), self-healing (resubscribes when the daemon returns) — replacing
  the 4s daemon-health poll. (7) **Removed the flaky polls** — `connection_events.js` (extracted
  from `app_globals.js` to honour the 500-LOC gate) drives the dot/banner/owned/notif/hot purely
  from events; `app_globals.js`'s daemon-health poll gone too. **HARDWARE-VERIFIED:** new
  `tests/test_rust_daemon_parity.py::test_rust_hardware_event_broadcast` subscribes to a live
  daemon, connects a REAL device, asserts `status`(connected) + `owned_devices`(real mac) arrive,
  then `owned_devices`([]) on disconnect. Mock tests: `test_daemon_event_broadcast.py` (status
  carries connected+mac; honest snapshot; owned_devices), `test_gui_event_forwarder.py`
  (fake-window unit test of every event type + shutdown-follow). `test_p6_degraded_dot.py`
  updated to assert the event-driven design (now reads `connection_events.js`). **Release
  v0.22.2: RELEASED — DMG built + adhoc-signed, tag `v0.22.2` pushed, GitHub release created,
  Homebrew cask bumped (sha `f670305134a03a966461ec397b31d8fbb4b8d1172e9d79a0aac43af14455746a`).
  Divergence guard green (v0.22.1 is ancestor of HEAD).** Plan: `docs/PLANNING_ROUND59.md`.

- **RENAME: `native-port/divoomd` → `divoomd` (repo root) — DONE (2026-07-12).** Per
  user decree the Rust daemon is **no longer a "port"** — it now lives at the repo
  root. `git mv` + every path reference fixed and **verified**: `cargo build --release`
  green; 42 Rust lib tests + `native_encode_parity` (dylib root-walk) green after
  dropping the binary's parent-count `5→4` in `native_encode.rs:25` and `spp.rs:30`;
  `divoomd/src/live_jobs/render.rs:12` `include_bytes` `../../../../`→`../../../` (the
  crate is now 1 dir shallower); `daemon_client.py:196` dev-tree discovery, `divoom.spec`,
  `setup_app.py`, `build.sh`, `scripts/build_release.sh`, `scripts/rust_coverage.sh`,
  `.github/workflows/tests.yml` (4× `working-directory`), `scripts/linux_remote/test_host.sh`,
  `tests/test_rust_daemon_parity.py` (binary discovery + 2 inline paths), and the
  `native-port/gen_*.py` codegen OUTPUT paths all repointed to the root `divoomd/`.
  `build.rs` link-arg re-emitted (file touched to bust a stale cached
  `native-port/divoomd/daemon_info.plist` link path). Python: 25 relevant tests green
  (file-size gate + wedge + edge-e2e + 10 parity tests; 3 hw/cloud skips). **No version
  bump** — pure path rename, behavior unchanged.

- **HARDENING BLITZ (R58, 2026-07-12) — DONE + HARDWARE-VERIFIED.** Closed the gaps
  left after R57: (1) **socket idle timeout + bounded concurrency** in `socket_server.rs`
  — `CONNECTION_IDLE_TIMEOUT` (default 300s, `DIVOOMD_IDLE_TIMEOUT_SECS`) drops silent
  peers; `MAX_CONNECTIONS` (default 64, `DIVOOMD_MAX_CONNECTIONS`) via a `Semaphore`
  back-pressures a 6th+ connection (was unbounded — a silent client could pin a permit
  + the device lock forever). The idle watchdog **also covers `subscribe`** (a silent
  subscriber — one that gets no events for the window — is now dropped, releasing its
  permit; an event delivery resets it). (2) **`device_call` overall timeout enforced**
  in `cmd_device_call` (`daemon.rs`): wrapped in `tokio::time::timeout` so a hung op
  drops + releases the device lock instead of wedging it; honors a caller `timeout`,
  clamped 1..120s, **default 30s**. **USER-RAISED long-command concern — RESOLVED with
  data:** measured on real Pixoo-1, normal ops are connect ~3.9s (reconnect ~1.7s),
  brightness/clock/hot-channel 59–61ms, `hot_update.update` 1ms (no pending content) —
  all 1–2 orders of magnitude under the 30s cap, so the timeout is a net against *hung*
  ops only, not a cliff for slow-but-valid ones. Very large 0x8B animation / gallery
  pushes should pass an explicit `timeout` (≤120s). **HARDWARE RUN:** 4 real devices
  (Pixoo-1, Timoo-light-4, Tivoo-Max-light-3, Ditoo-light-2) — `test_rust_hardware_parity`
  extended to a 3× connect→device_call→disconnect→reconnect loop **and** sequential
  connect to every discovered device: **11 hardware assertions pass** (2 cloud skip).
  TESTS: 3 new Rust tests in `divoomd/tests/socket_server_hardening.rs` (idle-drop +
  back-pressure + subscribe-idle-drop), 2 in `daemon_connect.rs` (timeout not
  false-firing + lock released), plus updated `socket_server_behavior.rs`. Full suite
  green: 44 Rust lib + 3 socket + 2 device_call, Python wedge/edge-e2e/parity (23 pass,
  3 hw/cloud skips), 11 hardware. Plan: `docs/PLANNING_ROUND58.md`. **No version bump**
  (defensive change). DEFERRED: GUI-side background auto-reconnect-on-socket-drop
  (R57 covers the connect-click path; the rest needs the app to verify).

- **RELEASE v0.22.0 CUT + HOMEBREW UPDATED (2026-07-12).** Known-devices persistence
  (R50, my earlier commit 5bd42b5) shipped on top of the full v0.21.8–v0.21.23
  line. **CRITICAL cross-session catch:** the other session cut v0.21.8–v0.21.23
  from branch `claude/hopeful-hertz-eddb6b` but never merged to `main`; `main` had
  regressed to v0.21.7 + only the local known-devices feature, so a naive
  `v0.22.0` built from `main` would have DROPPED 29 commits of real fixes. Fixed
  by merging `e5388a6` (v0.21.23) into `main` (merge commit 1928f82), then
  rebuilding + releasing from the merged tree. Tests: 1747 pass / 90 skip / 1
  pre-existing Rust-BLE failure. DMG sha `92765206…`; Homebrew cask bumped to
  0.22.0 (sha `9276520600f549ef679fea7fe25faf7a051987b26537776cc808b0a184108351`),
  `brew audit` clean. **Lesson / standing rule:** before cutting a release, verify
  `git merge-base --is-ancestor <latest_release_tag> HEAD` — if the latest release
  commit is NOT an ancestor of `main`, `main` has diverged and must be merged first.
   The `claude/hopeful-hertz-eddb6b` branch may still hold unmerged work; check it.

- **R57 (2026-07-12): daemon connect hardening — ROOT-CAUSED, FIXED, RELEASED as
  v0.22.1.** The v0.22.0 "connect to all devices fails" regression is ROOT-CAUSED:
  Rust `BleTransport::connect` / `ble::scan` called `central.start_scan()` /
  `central.peripherals()` with **no timeout guard**, so a dead CoreBluetooth
  session hangs forever → `run_connect`/`run_scan` never error → `reset_central`
  self-heal never fires → daemon unusable for ALL devices. FIXED via a new
  `BleCentral` abstraction (`divoomd/src/central.rs`) whose `connect`
  bounds every BLE call in `tokio::time::timeout`; added a concurrent connect
  guard (`ConnectGuard`/`connecting: AtomicBool`), widened `is_dead_central` to
  match `timed out`/`stale`/`central`, made GUI connect re-ensure the daemon
  (`scanner_mixin.connect_single_device` → `reconnect_daemon`), added a JS connect
  watchdog (`app_globals.connectDevice`, 35s), and bumped `connect_timeout` 20→30s.
  DETERMINISTIC COVERAGE: 4 Rust `central.rs` wedge tests (`BleCentral::Faulty`) +
  5 Python `tests/test_daemon_client_wedge.py` tests. Ble-lifecycle split into
  `daemon_ble.rs` for the 500-LOC rule (daemon.rs now 467 lines). All green: 38
  Rust lib tests, 55 python protocol/wedge/JS/mock-e2e tests. Real BLE connect
  verified unchanged (0.7s on Pixoo-1). **RELEASED v0.22.1**: tag pushed, GitHub
  release w/ DMG at `dist/Divoom-v0.22.1.dmg`, Homebrew cask bumped to 0.22.1
  (sha `3f9fb34e69f63483fc409a445b9ce4b757f71a473fc941e9415383615de0a18e`),
  `brew audit` clean. Pre-release `merge-base --is-ancestor v0.22.0 HEAD` passed.
  **NEXT: e2e edge-case blitz** — mid-flight disconnect, scan/connect overlap,
  reconnect loop, offline-MAC connect, connect-already-connected, daemon-restart-
  mid-op — both against the mock-device harness and `--run-hardware` if a device
  is free. Plan: `docs/PLANNING_ROUND57.md`.

  **E2E EDGE-CASE BLITZ DONE (still same commit wave as the release):** 8 tests in
  `tests/test_daemon_connect_edge_e2e.py` drive a REAL divoomd over a Unix socket
  via its `mock` transport (no Bluetooth) + an unreachable LAN IP for the
  "device is off" case — mid-flight disconnect, 5× reconnect loop, connect-while-
  already-connected idempotency, connect-to-offline-device-then-recover, device-op
  after disconnect, scan-during-connect. All 8 pass. Plus 4 Rust
  `daemon_connect.rs` connect-lifecycle unit tests (mock-connect, concurrent
  connect-guard rejection, disconnect-with-no-device, reconnect loop). Full green:
  42 Rust lib + 39 python. The only remaining gap is a real-device `--run-hardware`
  scan→connect→device_call→disconnect→reconnect loop (needs a free Pixoo).


- **HOT-CHANNEL PREVIEW investigation → v0.21.23 (2026-07-10).** User: the newest
  hot file (a penguin, v1112) isn't visible in the preview grid; suspected a stale
  cache. Verified with data + a live look at the packaged app (computer-use):
  (a) the DECODE/CACHE is correct — the tile decodes the exact bytes streamed to
  the device (`fin.divoom-gz.com/{file_id}`), and `get_animated_preview` returns
  the right penguin; the on-disk `cache_gallery` is fine. (b) `fetch_hot_manifest`
  is deterministic (penguin at index 0, newest-first) but the packaged app's grid
  showed a non-penguin at tile 0 and shifted between renders. (c) Code audit: only
  `renderHotPreview` writes the grid, no shuffle/sort, renders in manifest order,
  async swap is race-safe; `gallery_hot_api.py` unchanged since v0.21.22 → same
  logic. Conclusion: no reproducible code bug; the ordering weirdness is most
  likely the hot API returning a non-stable "featured" order over time (or my own
  misreads of the animated grid — flagged honestly). FIXES (defensive, committed
  67fd449): re-fetch preview after an update (`gallery_hot.js` finishProgress) +
  sort preview newest-first in `hot_update_preview` (pins newest to tile 0
  regardless of API order). NOT independently reproduced/confirmed fixed — needs
  verification in a fresh v0.21.23 build (packaged app is still v0.21.22). Also
  note: a few tiles render near-black; their 0xAA first-frame color counts are low
  (2–12 vs the penguin's 58) — likely genuinely-dark animations, NOT confirmed
  decoder garbage (would need a device-vs-tile comparison to call it a bug).
  LESSON: applied [[trace-the-boundary]] — caught myself twice labeling
  low-res/animated thumbnails as "garbage"/"penguin appeared" without verifying.


- **HOT-CHANNEL UPLOADS WERE BROKEN → FIXED + HARDWARE-CONFIRMED, v0.21.22
  (2026-07-09).** User: "unsure the hot-channel downloads are uploaded to the
  device." They were right — uploads served 0 files for EVERY device class. Root
  cause (found via a `DIVOOMD_BLE_DEBUG` BLE wire trace): the hot API returns each
  file's `Version` as a JSON **string** (`"1112"`) but `VendorId` as a number;
  `fetch_hot_manifest` (`art_hot.rs`) parsed `Version` with serde `as_u64()` →
  `None` for strings → every `HotFile.version = 0`. So the `0x9B` manifest
  advertised `newestVersion=0` and `pick_file` never matched the device's request
  (`0xF7` for v1103) → `pick_file NONE -> break`, served 0. Fix: `json_u32()`
  accepts number OR string (Python parity `int(f["Version"])`), applied to Version
  + VendorId; pure `parse_hot_manifest()` split out with a regression test (string
  Version, numeric VendorId; proven red before green). HARDWARE CONFIRM: re-ran
  over the socket → manifest `...58040000` (newestVersion=1112), 10 files MATCH +
  streamed (**1907 0x9E packets**), served=10 confirmed=10, then v1113 request →
  clean break. Also this round: the earlier `show_after` switch fix (device now
  switches to the HOT channel after a push) is confirmed too. Committed (927cd92 +
  d9e8898). Kept gated BLE TX + `[hot]` session logging (DIVOOMD_BLE_DEBUG) that
  made this findable. Release v0.21.22 NOT cut yet.
  - CONCURRENCY FIX (done, 8dcab81): `run_hot_session` now holds the device lock
    for the whole BLE exchange, so a concurrent `device_call` (which drains the
    notify channel via `send_command_and_wait`) waits instead of truncating an
    in-flight upload. Download stays lock-free; `get_status`/`hot_update_progress`
    lock-free so the progress UI is unaffected. Hardware-verified: 11-file /
    1907-packet upload completed cleanly with the lock held.
  - RELEASED v0.21.22 (tag + GitHub release + DMG + cask). CI GREEN (rust-ble,
    rust-core, rust-ble-linux, test, no-emoji all pass; rust-ble-windows is the
    known non-blocking Unix-socket-on-Windows failure being removed on branch
    claude/beautiful-kare-94c4d2).
  - Process note: `git checkout -- <file>` on an UNCOMMITTED file wipes all working
    changes — it cost a re-apply of this fix mid-round. Commit before "break to
    prove the test fails" experiments.

- **HOT-CHANNEL SWITCH FIX → v0.21.22, AWAITING HARDWARE CONFIRM (2026-07-09).**
  User: "selecting the hot channel should switch the device to the hot channel;
  this doesn't happen now." Root cause: the native daemon dropped the `show` flag.
  GUI "Update Hot Channel" sends `hot_update{show:True}`; `art.rs cmd_hot_update`
  reads it as `show_after` (default true) and passes it down, but
  `art_hot.rs run_hot_update` took it as `_show_after` and never used it — so files
  were pushed but the screen never switched. The Python daemon DID switch
  (`owner_art.show_hot_channel` → `0x45 [0x02]`), so the two daemons disagreed. Fix
  (`art_hot.rs`): after a successful `run_hot_session`, if `show_after`, send
  `0x45 [0x02]` (HOT/cloud channel). Fires even when 0 files served (already up to
  date), so the button reliably lands the screen on the hot channel. Committed +
  version bumped to 0.21.22; release NOT cut yet — needs user-POV hardware confirm
  (OS-facing). Both target/release + target/debug divoomd rebuilt with the fix.
  Verify: `./run.sh` → connect a device → set it to Clock → click "Update Hot
  Channel" → screen should switch to the hot/cloud channel. (A/B driver in the
  scratchpad: `hw_test_hot_channel.py`.) After confirm: `scripts/release.sh`.

- **CI GREEN → v0.21.21 (2026-07-09).** The v0.21.20 tag push was the first CI run
  since v0.21.7, and it went red: `rust-core` + `rust-ble` both failed on a
  **rustdoc doctest** — `hot_state.rs` had an indented JSON example in its module
  doc (`//!`), which rustdoc compiles as a runnable Rust doctest
  (`test src/hot_state.rs - hot_state (line 11) ... FAILED`). Local `cargo test
  --lib` never caught it because `--lib` EXCLUDES doctests; they only run under
  `cargo test --doc`. Fix: wrapped the block in a `text` fence (renders, not
  compiled). Shipped as v0.21.21 (fresh DMG + tag + release + cask — user chose a
  follow-up patch over rewriting the published v0.21.20 tag). CI on v0.21.21:
  `rust-core`/`rust-ble`/`rust-ble-linux`/`test`/`no-emoji` all GREEN; overall run
  conclusion **success**. NOTE: `rust-ble-windows` fails on BOTH v0.21.20 AND
  v0.21.21 (`unresolved import tokio::net::UnixListener/UnixStream`) — the daemon
  is Unix-socket-only, can't compile on Windows; it's a pre-existing, inherent,
  NON-BLOCKING job (continue-on-error). Candidate cleanup: drop the Windows job
  since this is a macOS-only app.

- **ROCK-SOLID BLE CONNECTION → v0.21.19/20 + hardware test loop (2026-07-09).**
  User: "can't connect, very flaky." Live repro found the BLE **connect path had
  unbounded awaits** — `peripheral.connect()`/`discover_services()`/`subscribe()`
  (CoreBluetooth `connect()` waits forever for an unresponsive device, and it runs
  while holding the `device` lock → whole device path hung, connect never returned
  in 40s+). Fixed v0.21.19: each bounded at 20s (`CONNECT_TIMEOUT` in `ble.rs`).
  Then ran an adverse hardware test loop over the socket (daemon has TCC): connect/
  reconnect 0.2–1.7s, device-switch Timoo↔Pixoo 0.3–0.7s, channel-switch (0x45)
  with read-back confirming the mode changed, brightness writes, scan-while-
  connected, rapid connect/disconnect ×3, and 2 full quit/relaunch restart cycles
  — ALL pass. GUI **auto-connects to the last device + auto-scans on startup**
  (app_init.js); those two contend on the one adapter — noted, but the timeouts +
  self-heal make it recover cleanly. Also shipped v0.21.20: **version indicator in
  the Settings footer** (`get_app_version` in lifecycle_mixin reads
  pyproject/Info.plist). Final v0.21.20 DMG built + installed + confirmed on
  hardware. Test methodology: SIGTERM (not -9) between restarts; pace BLE ops.

- **RELEASE v0.21.20 CUT + HOMEBREW UPDATED (2026-07-09).** New one-shot
  `scripts/release.sh` (reads pyproject version → build DMG [skippable] → annotated
  tag + push → GitHub release on `ztomer/divoom_lib` with the DMG → bump
  `Casks/divoom-control.rb` version+sha256 in `ztomer/homebrew-tap` via gh API;
  idempotent). Ran it: tag v0.21.20 pushed, GitHub release created (notes span all
  of v0.21.8→20 since the last release was v0.21.7), DMG asset uploaded (URL 200),
  cask at 0.21.20 + sha 160f522e. `brew upgrade --cask ztomer/tap/divoom-control`
  now serves it. CAVEATS: (a) tag was cut from branch `claude/hopeful-hertz-eddb6b`
  (not main) — commits reach origin via the tag but NO origin branch points at
  them; merge the branch to main for branch history. (b) code repo is named
  `divoom_lib` (known, user won't rename). Next release: just bump pyproject + run
  `scripts/release.sh`.

- **BLE CENTRAL SELF-HEAL → FIXED v0.21.18 (2026-07-09).** User: "can't connect to
  screens, very flaky." Live repro: with a dead cached central, BOTH `scan` and
  `connect` returned `"Channel closed"` in ~0.0s — the CoreBluetooth session died
  (device disconnect / BT toggle) and the daemon cached the Adapter forever, never
  rebuilding it, so only a restart recovered. Fix (`daemon_connect.rs`): on a
  dead-central error (`is_dead_central` → contains "Channel closed"), call
  `Daemon::reset_central()` and retry the scan/connect ONCE with a fresh central.
  `run_scan`/`run_connect` helpers factor it. Teeth: `detects_dead_central_error`.
  NOTE: could not exercise the RECOVERY path on hardware (can't kill the central on
  demand without also restarting the daemon → fresh central); detector unit-tested,
  and a fresh central after install recovers the user immediately.

- **FALSE "SERVICE NOT RUNNING" BANNER + DEVICE-LOCK WEDGE → FIXED v0.21.17
  (2026-07-09).** User hit the daemon-down banner while the daemon WAS running.
  Root-caused live: `device_status`/`device_call` hung 6s+ while
  `get_status`/`get_device_activity` were instant → the daemon's `device` mutex
  was stuck, held by an unbounded BLE write that never returned (write to a
  peripheral that vanished when Bluetooth was toggled mid-op). The liveness probe
  (`daemon_alive`/`_client_alive`) used `device_status` (needs that mutex) → hung
  → false "dead" → banner. Fixes: (1) `ble.rs` bounds the write with `WRITE_TIMEOUT`
  (5s) so a hung write releases the lock and the daemon self-recovers; (2)
  `daemon_client.py` probe switched device_status → **get_status** (cheap,
  LOCK-FREE); (3) `notification_service._state` uses `getattr(mon,"is_running",…)`
  (get_status is now the probe, must not raise on an incomplete monitor — also fixed
  2 daemon_bridge tests). Rust + Python compile/tests green. NOTE: any daemon
  running BEFORE this build (incl. the user's current v0.21.16) can still be
  wedged — needs a daemon restart (quit+reopen app) to pick up the fix.

- **BLE SCAN CoreBluetooth-THROTTLE HARDENING → v0.21.16 (2026-07-09).** The wedge
  that dogged this session (rapid daemon restarts → CoreBluetooth scan-frequency
  throttle → scans return 0 until BT toggle) is now guarded in `native-port/divoomd`:
  (1) `Daemon::stop_scan_cleanup()` called on shutdown in `main.rs` — stops the
  scan on the cached central so a normal quit doesn't leak a scan session to
  bluetoothd; (2) `cmd_scan` caches last result+time (`Daemon.last_scan`) and a
  scan within `MIN_RESCAN_INTERVAL` (3s) returns the cached list (`"cached":true`)
  instead of hitting the radio. Teeth: `rapid_rescan_returns_cached_without_touching_radio`.
  Both feature sets compile. NOTE: `kill -9` still leaks (SIGKILL uncatchable) —
  tests should SIGTERM. Recovery for a wedged stack: BT toggle / `sudo pkill
  bluetoothd`. Functional scan (finds 3) was verified earlier post-BT-reset; this
  round is compile+unit-tested only (user's BT still wedged from prior testing).

- **SCAN TIMEOUT DEFAULT 60→20s → v0.21.15 (2026-07-09).** After the v0.21.14 scan
  guard fix, scans still ran ~80s because they run the full window when device
  count < limit and the default/persisted timeout was long. Lowered the default to
  20s across `scanner_mixin.get_scan_settings`, `presets_manager.load_config`,
  `daemon_config.DEFAULT_SCAN_TIMEOUT`, the Settings input default + JS fallbacks.
  Also reset THIS user's persisted config.ini `[gui] timeout` 120→20. Verified on
  the installed build: scan finds all 3 devices (Pixoo-1, Timoo-light-4,
  Tivoo-Max-light-3) fast. v0.21.14 guard confirmed working end-to-end (after a
  Bluetooth reset — my rapid daemon restarts during testing had wedged
  CoreBluetooth; see the v0.21.14 caveats below).

- **NATIVE DAEMON BLE SCAN CONCURRENCY GUARD → v0.21.14 (2026-07-09).** User: app
  found 2 of 3. Drove the daemon socket: it RELIABLY finds all 3 in isolated scans
  (6/15/60/120s) — BLE/daemon healthy. Root cause: **no scan concurrency guard** —
  overlapping scans share the one adapter and clobber each other (my own probes
  overlapping the GUI scan truncated it). Fix: `Daemon.scanning` flag + `ScanGuard`
  RAII in cmd_scan; concurrent scan rejected. Plus a 90s timeout cap in ble::scan.
  Teeth: `scan_guard_tests`; both feature sets compile.
  **IMPORTANT LESSONS / CAVEATS:**
  (a) I first tried to also make ble::scan incremental (event stream) + early-exit
  at limit — BOTH hung: querying peripheral `properties()` DURING an active scan
  blocks on macOS CoreBluetooth. Reverted to the proven single-window snapshot
  (query only AFTER stop_scan). Do NOT reintroduce during-scan property reads.
  (b) My many rapid daemon kill/restart cycles during testing WEDGED the Mac's
  CoreBluetooth — scans started returning 0 devices (cache went empty). This is
  environmental (not the code); needs a Bluetooth reset / settle to clear. Verify
  on a clean BLE stack. (c) Testing done by hot-swapping the release divoomd into
  the installed .app + re-signing (faster than a full DMG rebuild). The COMMITTED
  DMG still needs a rebuild with the final (reverted) code. (d) connect also scans
  (BleTransport::connect) and isn't under the guard yet — scan-vs-connect is a
  follow-up.


- **DMG BUILD + INSTALL + RUNTIME TEST → PASSED v0.21.13 (2026-07-09).** Built
  `dist/Divoom-v0.21.13.dmg` (38M, adhoc-signed) via `scripts/build_release.sh`
  (had to create `.buildvenv` first). Installed from the mounted DMG to
  `/Applications` (replaced 0.21.7). VERIFIED on the real build:
  (1) **App icon** — `Contents/Resources/Divoom.icns` present, all 10 iconset
  sizes incl @2x, `CFBundleIconFile=Divoom.icns`. (2) **Bundle** ships all web_ui
  changes (daemon-banner, hot-last-checked, loadLastChecked, refreshDaemonHealth)
  and the Rust `hot_state` (strings probe: `hot_update_state.json` + fields +
  `[ Wrn ] hot_state record_check failed:`). (3) **Launch** — dashboard renders;
  native Rust `divoomd` + `divoom-menubar` both spawn; BLE works (4 devices found,
  Timoo-light-4 connected); NO daemon-down banner (healthy). (4) **Daemon
  reliability (v0.21.9)** — `kill -9` the daemon → app STAYED running and a fresh
  daemon respawned within ~1s, device still connected, no banner. LIMITATION:
  couldn't drive the pywebview UI via computer-use — the user's tiling WM
  (`com.zaidenstein.ZoneTilerWM`, not allowlistable) overlays the window and eats
  clicks. So the MCP-card / hot-channel-stamp / banner VISUALS weren't clicked
  through on the DMG (all verified earlier via unit tests + the static web_ui
  preview). Note: stale `~/.config/divoom-control/mcp-server.log` (Jun 10) is
  still on disk — confirms the MCP fix relies on session-gating to not surface it.
  Full test suite can't run clean in this shell (BLE tests SIGSEGV mid-run;
  see [[divoom-pytest-shutdown-segfault]]) — changed-area files all green.


- **HOT CHANNEL "LAST CHECKED" STAMP → ADDED v0.21.12, MADE DAEMON-OWNED v0.21.13
  (2026-07-08).** Per-device dated verdict so "up to date" isn't blind (user's
  follow-up ask). v0.21.12 recorded it GUI-side; v0.21.13 moved the WRITE into the
  daemon (correct owner — it runs the update; daemon is native Rust now). The
  daemon stamps `hot_update_state.json` on completion in BOTH impls
  (`native-port/divoomd/src/hot_state.rs`; Python `owner_art.py` via
  `divoom_lib/hot_update_state.py`); the GUI passes the active device address on
  the write and only READS via `hot_get_check` (resolves the same active-device
  key). `hot_record_check` removed. Store keyed by device address (MAC/`LAN:ip`/
  `MatrixWall`); `>2wk` turns amber. Teeth: 3 Rust + 3 GUI-API + store tests.
  `cargo check` clean; Python suite green; preview re-verified. **Not on DMG.**
  Rationale on record: an undated "up to date" was untrustworthy; now dated +
  daemon-authoritative, captures non-GUI triggers too.

- **MCP CARD STALE TRACEBACK → FIXED v0.21.8 (2026-07-08).** The Settings →
  Connectivity → "MCP Server" card showed a Python traceback even with the toggle
  OFF (the v0.21.7 note flagged it as an open follow-up). Root cause 1: the GUI
  spawns `divoom-control mcp-server` with stdout redirected to a **log file**, but
  an MCP *stdio* server needs client-owned **pipes** — asyncio's write-pipe
  transport rejects a regular file (`ValueError: Pipe transport is only for pipes,
  sockets and character devices`) and crashed at startup, writing a traceback to
  `~/.config/divoom-control/mcp-server.log`. Root cause 2: the card **tailed that
  log unconditionally** (even stopped / never-started), so a crash from a prior
  session persisted. Fix: `run_stdio()` guards non-pipe stdio via
  `_stdio_is_pipe_like()` and exits with one clean diagnostic line
  (`mcp_server.py`); `MCPController` only surfaces the log for a server started
  THIS session and truncates on start (`mcp_control.py`). Real MCP-client launches
  (Claude Desktop/Cursor) were always fine — only the GUI "Start" toggle was
  doomed. Teeth: 3 new tests in `test_mcp_server.py` (33 pass total). **Not yet
  verified on a DMG** (native pywebview app; TCC/BLE harness limit) — confirmed by
  unit tests + direct reproduction of the guard turning the crash into a clean line.

- **DAEMON-DOWN SILENT + UNRECOVERABLE → FIXED v0.21.9 (2026-07-08).** Restart
  left the app unusable with no indication / no reconnect. Root causes: eager
  launch spawn (`gui_main.py`) discarded its client + never surfaced/retried
  failure; no daemon-down UI; `get_connection_state` couldn't tell daemon-down
  from no-device. Fix: eager spawn now assigns `api._daemon_client`; new backend
  `daemon_health()` (no-spawn liveness probe) + `reconnect_daemon()` (reset stale
  client + re-ensure); frontend daemon heartbeat (4s + on open, ungated) that
  auto-reconnects once then shows a **Reconnect banner** (`#daemon-banner` in
  index.html, styled in widgets_extra.css, wired in app_globals.js/app_init.js).
  Teeth: 7 tests in `test_gui_api.py` (52 pass). Banner render verified in the
  static web_ui preview. **Not yet verified on a DMG** (TCC/BLE harness limit).

- **MISSING APP ICON → FIXED v0.21.10 (2026-07-08).** Shipped `Divoom.app` had
  the generic blank icon: `divoom.spec` had `icon=None` and no `.icns` existed
  (only a 1024px JPEG mis-named `app_icon.png`). Fix: `scripts/make_icns.sh`
  builds `packaging/Divoom.icns`; `divoom.spec` points `icon=` at it;
  `build_release.sh` regenerates before packaging; `setup_app.py` gains `iconfile`
  for parity. **Not yet verified on a DMG.**

- **HOT CHANNEL false "up to date" + redundant downloads → FIXED v0.21.11
  (2026-07-08).** (a) UI verdict was `served.length===0` → "up to date"; a partial
  CDN download (files dropped from the advertised manifest) reported a clean
  "up to date" it never verified. Fix: `gallery_hot.js` now uses the engine's
  `manifest`/`downloaded` counts — `downloaded < manifest` → "Checked D/M" +
  amber + warning toast, not "Up to date". (b) manifest+bodies were fetched per
  device inside `update()`; added `_load_hot_files` device_type-keyed cache (5-min
  TTL) in `hot_update.py` so same-size devices reuse one fetch+download. Teeth: 2
  cache tests + guard updated (26 hot tests pass; full suite green). NOTE: did NOT
  add a persisted freshness timestamp — the "up to date" signal is protocol-honest
  once partial-download is surfaced; a dated last-checked marker is a possible
  future nicety (would need a new store; hotchannel.json is the *Monthly Best*
  config, a different subsystem). **Not verified on a DMG.**

- **SETTINGS TOGGLES IGNORED SAVED STATE → FIXED v0.21.7 (2026-07-08).** Caught by
  driving the real dashboard on-screen (computer-use): the Connectivity toggles
  didn't reflect their persisted value when Settings opened — `quit_menubar_on_exit`
  was `true` in config but the toggle rendered OFF. Root cause: the init read
  `api().get_*()` ran at `DOMContentLoaded`, before pywebview injects
  `window.pywebview.api`, so it was silently skipped and the toggle kept its
  unchecked HTML default. (Invisible on `keep_daemon_alive` — default false; exposed
  by `quit_menubar_on_exit` — default true.) Writing was always fine (verified by
  clicking → config flipped). Fix (`settings_notifications.js`): defer the value
  reads to the `pywebviewready` event, the same guard `restoreScanSettings` uses.
  **Verified on-screen on the 0.21.7 DMG:** toggle now shows ON (orange) reflecting
  the true default; Background agent shows off. Also re-confirmed on 0.21.7: dash
  renders, menu bar spawns, clean-quit terminates it, scan finds 4 devices + connect
  Pixoo-1 (brightness 60). NOTE: the MCP Server card shows a Python traceback in the
  UI (mcp_server run_stdio connect_read_pipe) — pre-existing, unrelated, worth a
  separate look. Shipped v0.21.7.

- **MENU BAR MISSING ON NORMAL LAUNCH → FIXED v0.21.6 (2026-07-08).** A clean-room
  install-from-DMG + single `open` launch caught it: the menu-bar agent never
  spawned when the app was started the normal way (Finder/Dock/`open`/cask) — no
  tray icon. `_spawn_menubar_agent`'s dupe-guard used `pgrep -f divoom-menubar`;
  `-f` is a loose substring match over every process's full command line, and under
  LaunchServices a coalition process transiently carries "divoom-menubar" in its
  args, so the guard false-matched → "already running" → skipped the spawn. (Direct
  `Contents/MacOS/Divoom` launches had no such process → looked intermittent.)
  Proven with a decoy: `pgrep -f divoom-menubar` matched `helper
  divoom-menubar-relaunch`; `pgrep -x divoom-menubar` (exact name) did not. Fix:
  use `pgrep -x`. Teeth: `test_menubar_dupe_guard_uses_exact_match`. **Verified
  end-to-end on the 0.21.6 DMG:** fresh install → `open` → menu bar spawns; scan
  finds 4 devices; connect Pixoo-1 (get_brightness → 60). Shipped v0.21.6.

- **CLEAN QUIT → v0.21.5 (2026-07-08): GUI terminates the menu-bar agent.** Root
  cause of the orphan: the native `divoom-menubar` is spawned detached and does NOT
  follow the daemon's `EVENT_SHUTDOWN` broadcast (the Python menubar did), so a
  plain quit left it in the tray. Fix: on a shared-lifecycle quit the GUI now calls
  `gui_main._terminate_menubar_agent()` (`pkill -f divoom-menubar`), gated by a new
  global flag **`quit_menubar_on_exit`** (default True) via
  `lifecycle_config.should_quit_menubar_on_exit(keep_alive, quit_menubar)` —
  `(not keep_alive) and quit_menubar`. New UI toggle: Settings → Connectivity →
  "Quit menu bar with dashboard". The 4 lifecycle API methods moved to
  `divoom_gui/lifecycle_mixin.py` (`LifecycleSettingsMixin`) so they stay
  pywebview-exposed while keeping `gui_api.py` under the 500-line limit (split, not
  trimmed). **Verified end-to-end on the installed 0.21.5 DMG:** default → quit
  kills app+daemon+menu bar (all clean); flag OFF → menu bar survives a quit.
  Tests: `test_should_quit_menubar_on_exit` (+ flag roundtrip). Suite for the
  touched area 49 green. NOTE: menu-bar **auto-spawn on launch** is intermittently
  not firing (pre-existing, unrelated to this change) — worth a separate look.

- **CLEAN HOMEBREW UPGRADE (2026-07-08): cask now stops all processes.** Verified
  the update UX: on `brew upgrade`, the app + `divoomd` + `divoom-menubar` were NOT
  being stopped — the cask had no `uninstall` stanza, and on quit the GUI shuts down
  `divoomd` (sends `shutdown`) but leaves `divoom-menubar` orphaned to launchd. Added
  an `uninstall` stanza to `ztomer/homebrew-tap` Casks/divoom-control.rb:
  `quit: "com.divoom.control"` (graceful GUI quit → daemon shutdown) + a `script:`
  `pkill -f 'Divoom.app/Contents/Frameworks/bin/divoom'` (reaps the orphaned menubar
  + any stubborn daemon); also fixed the stale `zap` socket path (`/tmp/divoom.sock`).
  `brew style` clean. **Proven through brew:** `brew uninstall --cask` prints
  "Quitting application … quit successfully" + "Running uninstall script" → zero
  survivors; reinstall + relaunch scans 4 devices. **KEY GOTCHA (now in RELEASING.md
  §5):** `brew upgrade` runs the *installed* version's uninstall stanza, so the
  0.21.3→0.21.4 hop still swapped the bundle under live processes (0.21.3 had none);
  0.21.4→later is clean. Never drop the stanza. Follow-up (not blocking): the GUI
  could terminate `divoom-menubar` on full quit so non-brew quits are clean too —
  left as-is since the tray agent is meant to persist a window-close (R24).

- **BLE SCAN CRASH FIXED (2026-06-30): disclaim the native daemon.** The bundled
  app "detected no Bluetooth devices" — `divoomd` crashed with a TCC `SIGABRT`
  (`NSBluetoothAlwaysUsageDescription` missing) the moment it scanned. The daemon
  itself was healthy: driven directly over `/tmp/divoom.sock` it returned both
  devices (Ditoo-light-2, Pixoo-1). Root cause was in `spawn_daemon`
  (`divoom_daemon/daemon_client.py`): it disclaimed TCC responsibility only for the
  Python daemon, spawning native `divoomd` as a plain `Popen` child that
  **inherited the launcher's responsible process**. When the `.app` was launched
  under another app (crash report: `responsibleProc: "claude"`, no BT usage
  description), CoreBluetooth SIGABRT'd it mid-scan → empty device list. From
  Finder/Dock it worked (responsible = `Divoom.app`, granted) — hence intermittent.
  **Fix:** disclaim the native daemon too (`use_rust or bundle_py is None`) so it's
  its own responsible process using its embedded `com.divoom.divoomd` plist (the
  `build.rs __TEXT,__info_plist` work, previously embedded but never the
  responsibility basis); `_spawn_disclaimed_macos` now takes an explicit `env` so
  `DIVOOMD_ENCODER_LIB` propagates. **Verified:** a `divoomd` spawned disclaimed
  *from a shell* (the prior SIGABRT context) scans cleanly and finds both devices,
  no crash. Teeth: `test_rust_daemon_is_tcc_disclaimed`. **Verified end-to-end
  through the shipped v0.21.4 DMG:** built → killed all entities → installed from
  `dist/Divoom-v0.21.4.dmg` → launched → the app's daemon scanned **4 devices**
  (Ditoo-light-2, Timoo-light-4, Pixoo-1, Tivoo-Max-light-3) and **connected to
  Pixoo-1** (`get_brightness` → 60 over live BLE), no crash. Shipped v0.21.4.

- **BLANK-GUI FIXED → v0.21.2 (2026-06-30):** the py2app `.app` opened a blank
  dashboard — pywebview's WKWebView won't load the `file://` UI inside a py2app
  bundle (renders fine as loose Python, so `./run.sh` always worked). Root-caused by
  driving the real app (WKWebView `loadRequest:` for file:// is blocked in a signed
  py2app `.app`; encoding/ATS/http-server/loadFileURL didn't help). **Fix: package
  the macOS app with PyInstaller** (`divoom.spec`) — verified end-to-end (dashboard
  renders, bundled `divoomd`+`divoom-menubar` spawn, Pixoo-1 connects).
  - Resolvers (`gui_main` web_ui + menubar binary; `daemon_client` divoomd + encoder
    dylib) are packaging-agnostic: PyInstaller `sys._MEIPASS` → py2app `RESOURCEPATH`
    → dev tree. Menu-bar "Launch Dashboard" works frozen (`launch.rs` empty-script).
  - `scripts/build_release.sh` builds via PyInstaller now; `setup_app.py` (py2app)
    kept for reference. Build venv needs `pyinstaller` + `psutil`.
  - Shipped: GitHub release v0.21.2 + Homebrew cask 0.21.2 (sha verified). v0.21.x
    py2app dmgs are superseded (their GUI was blank).
  - Known minor: web_ui logs a non-fatal `window.loadGalleryFilter is not a function`
    (gallery.js:354) — pre-existing, page still renders.

- **Deterministic mode test:** `scripts/hw_test_modes.py` walks every channel/mode +
  controls over the daemon socket with fixed args + read-back asserts (JSON report to
  test_reports/). Verified on Pixoo-1: full sweep **24/24** (6 clock faces, viz 0-2,
  vj 0-1, ambient r/g/b, scoreboard, solid+gradient image, brightness read-backs).
  `--mac`/`--all`/`--dwell`/`--quick`.
- **HARDWARE-VERIFIED the Rust daemon (2026-06-30):** against real Pixoo-1 over the
  socket — scan → connect → `get_device_name`="Pixoo-1" → `get_brightness`=75 →
  set 30/80 with read-back. (Getters error with a Python `AttributeError` on the
  Python daemon, so this confirmed the Rust path.) The Rust **menubar** also runs
  (spawned by the GUI); its tray visual is the only piece left for the maintainer to
  eyeball.
- **Bugfix:** `divoom_daemon/daemon_client.py` resolved the dev repo root with
  `parents[2]` (one level too high) → dev runs silently used the **Python** daemon;
  fixed to `parents[1]` so `./run.sh` spawns the **Rust** `divoomd`. (Bundle was
  unaffected — it uses `RESOURCEPATH`.)
- **`run.sh`** now kills any existing divoom processes (GUI / Python daemon / Rust
  `divoomd` / menubar) + clears stale sockets before launch.
- **CI fix:** `tests/test_no_emojis.py` diverged from the authoritative
  `tools/check_no_emoji.py` (flagged the permitted Kare icons ✓ ✗ ⚠); reconciled —
  CI green on Python 3.14.


- **ARCHITECTURE PIVOT (2026-06-30):** the egui UI is retired. Shipping stack is now
  **Python pywebview GUI + Rust daemon (`divoomd`) + Rust menubar (`divoom-menubar`)**.
  - New crate `native-port/divoom-menubar` (tao + tray-icon): windowless tray agent;
    polls the daemon socket for status/devices; Launch Dashboard / Open Notifications /
    Start+Stop Notifications / Quit; launches the GUI via `DIVOOM_GUI_PYTHON`/`SCRIPT`;
    Quit honours `keep_daemon_alive`. Ports `divoom_menubar/menubar.py`.
  - `divoom_gui/gui_main.py` spawns the Rust menubar (not the pyobjc one). pyobjc
    `divoom_menubar/` kept in-tree as reference only.
  - `native-port/divoom-ui/` (egui) DELETED; `scripts/build_native_app.sh` removed;
    `divoom-control-native` cask retired (tap pushed).
- **RELEASED v0.21.0 (2026-06-30):** CI bumped to Python 3.14; version 0.20.2 → 0.21.0;
  `scripts/build_release.sh` built `Divoom.app` + `Divoom-v0.21.0.dmg` (bundling +
  re-signing both `divoomd` and `divoom-menubar`); pushed `main` + tag `v0.21.0`;
  GitHub release created with the dmg; `divoom-control` Homebrew cask bumped to
  0.21.0 (sha256 `ede091f3…`, verified against the live asset) + tap pushed. `brew`
  confirms 0.21.0 is published. (Bundle is arm64, built on Apple Silicon — same as
  prior releases.)
  - Packaging: `setup_app.py` + `scripts/build_release.sh` bundle/sign `divoom-menubar`
    next to `divoomd` in the Python `.app`.
- **Dev helpers (root):** `./build.sh` builds the Rust daemon + menubar (+ encoder
  dylib; `--debug` for debug). `./run.sh` launches the Python GUI (which spawns the
  daemon + menubar); `--menubar` runs the tray alone for a smoke. Both source
  `tui/lib.sh` (Kare style). (Shippable `.app`: `scripts/build_release.sh`.)
- **NOT DONE YET:** on-hardware verification of the new stack (GUI ↔ daemon ↔ menubar
  on the 4 devices) — needs the maintainer to start the BLE daemon (TCC). Docs
  (PLANNING_NATIVE_UI / ROADMAP / PARITY_TRACKER) still describe the egui direction
  and need a pass.


- **NATIVE UI PORT — Phase 0 DONE (2026-06-29) — `docs/PLANNING_NATIVE_UI.md`:**
  building a native cross-platform Rust UI to replace the Python presentation
  layer (pywebview GUI + pyobjc menubar), making the shipped app Python-free.
  - **User constraints (locked):** full **native widgets** (NOT a webview — the
    earlier wry/webview plan is superseded, kept in the doc for record);
    **cross-platform** (macOS/Linux/Windows); **permissive licensing** — ship MIT
    now, maybe commercial later, never pay → **rules out Slint** (GPL-or-pay).
    **Toolkit chosen: egui/eframe** (MIT/Apache; picked over iced for pragmatism).
    The current `web_ui/` is the **visual reference only** (read for layout/look),
    not shipped; stays archived in-tree.
  - **VISUAL PARITY COMPLETE (2026-06-29):** every visual element of the current
    Python web UI is now reproduced natively. The last open item, an on-screen audio
    visualizer, was deliberately removed from the Python reference (Rams #10 — see
    `web_ui/widgets.js:15`), so it's N/A. Remaining follow-up (NOT parity): refresh
    the `divoom-control-native` Homebrew cask/dmg to a release when ready to publish
    (outward-facing — needs user go-ahead).
  - **Cloud gallery thumbnails DONE (2026-06-29):** new daemon command
    `get_animated_preview{file_id}` downloads + decodes a cloud file to a base64
    data-url (reuses `media::resolve_to_gif`; offline-tested vs cloud_fixtures).
    The UI gallery (under Pixel Art) renders `fetch_gallery`'s FileList as a grid,
    lazily fetches each tile's preview → texture, and pushes on click via
    `sync_artwork`. Needs cloud login for live data (Settings card exists). Only
    remaining visual-parity gap: the audio visualizer (needs local audio capture).
  - **Live device-screen preview DONE (2026-06-29):** the sidebar now renders the
    device's last-pushed frame (web parity). New `preview.rs` encodes RGB→data-url PNG
    and decodes data-url→egui texture (base64 + `image`); the app polls
    `get_device_activity` (~1.5s) and frames the UI pushes (pixel art) seed a
    client-side preview + persist via `set_device_activity`. Unit-tested +
    screenshot-verified (`DIVOOM_UI_FAKE_PREVIEW` debug seed). No daemon change.
    Remaining visual-parity gaps: gallery thumbnails (needs cloud auth), audio
    visualizer (needs local audio capture).
  - **egui 0.29 → 0.35 migration DONE (2026-06-29):** bumped eframe/egui/egui_extras
    to 0.35; ported the breaking API changes — `Rounding`→`CornerRadius` (u8),
    `Margin` is now `i8`, `painter.rect`/`rect_stroke` take a `StrokeKind`,
    `Frame::none()`→`Frame::NONE`, `FontData` wrapped in `Arc`, `ctx.style()/set_style`
    →`ctx.all_styles_mut`, `ViewportCommand::Screenshot(UserData)`, `TopBottomPanel`/
    `SidePanel` merged into `egui::Panel::{top,left,bottom}(id).exact_size(..).show(ui,..)`,
    and `eframe::App::update`→`logic(ctx)` (non-UI) + `ui(&mut Ui)` (panels). Clean
    debug+release build (only pre-existing dead-code warnings); screenshot-verified the
    Channels tab renders identically.
  - **Built so far** (`native-port/divoom-ui/`, eframe/egui 0.35):
    - `theme.rs` — Braun dark palette copied byte-for-byte from `web_ui/style.css`
      (`#121316` bg, `#ff5a1f` accent, 168px sidebar).
    - `shell.rs` — frameless integrated appbar (window controls + brightness/volume
      sliders + Settings pill + window-drag), sidebar (6 nav tabs w/ active orange
      accent + device panel pinned bottom), content host w/ Channels sub-tab row.
    - `daemon.rs` — NDJSON socket client on a worker thread (UI never blocks);
      `mpsc` to the egui loop. 2s status poll + scan/connect/device_call.
      `DIVOOM_SOCKET` env overrides the path (default `/tmp/divoom.sock`).
    - `app.rs` — state + frame orchestration; self-screenshot debug path
      (`DIVOOM_UI_SCREENSHOT=path` → egui `ViewportCommand::Screenshot`, saves a
      framebuffer PNG and exits; **no OS screen-record permission needed** — use
      this to verify the UI headlessly).
  - **Verified:** compiles clean; renders faithfully to the reference (screenshot);
    "daemon ready" shows live against a **no-BLE** `divoomd`
    (`cargo build --no-default-features`, run with `--socket /tmp/foo.sock`, point
    the UI at it via `DIVOOM_SOCKET`). Probed protocol: `get_status` (state +
    uptime_s), `device_call {method,args:[...]}` routes; `scan` is BLE-gated so the
    no-BLE core returns "not implemented" (expected — UI surfaces it).
  - **Phase 1 DONE** (`daemon.rs`): added a `subscribe` event thread (status
    pushes, auto-reconnect) + `divoomd` auto-spawn when the socket is absent
    (`DIVOOMD_BIN` / sibling-of-exe / PATH resolution + 4s poll-connect). Windows
    TCP transport still deferred to Phase 4 packaging.
  - **Phase 2 DONE** (`channels.rs`, new): the Channels tab now renders real
    per-channel panels reproduced from `web_ui` + `channels_grids.js`, each wired
    to the device_call leaf the Python `LightingApi`/`ToolsApi` use (verified vs
    the Rust dispatch + positional-arg convention):
    clock face → `display.show_clock [style]`; visualizer (12 EQ) →
    `display.show_visualization [n]`; VJ (16) → `display.show_effects [n]`;
    ambient (5 modes + color/swatches) → `display.show_light [hex,brightness,
    true,mode]`; scoreboard → `set_scoreboard [1,red,blue]`. Generic
    `selector_grid`/`cell_button`/`swatch` widgets. `DIVOOM_UI_CHANNEL` env picks
    the initial channel (screenshot aid). **Deferred to Phase 3:** Text push
    (needs the bitmap-font→image render from `LightingApi._render_text_png`) and
    the Sessions panel (Sleep Aid). Clock color uses `set_clock_rich` (face is
    white-only on the device via show_clock).
  - **Verified** by self-screenshots: clock/ambient/scoreboard panels render
    faithfully against a no-BLE daemon (device_call returns "no device" — expected
    without hardware; wiring is correct).
  - **Phase 3a DONE** (`device_settings.rs`, new): the **Device Settings** tab —
    device name, clock format (12/24h), temp unit, power mode, auto power-off,
    orientation (0/90/180/270), mirror/flip, confirm-gated factory reset; each
    wired to the device_call leaf the Python `ToolsApi` uses (verified vs Rust
    dispatch). **`sync_time` is a real daemon gap** (Python uses `DateTimeCommand`
    directly, not a device_call leaf) → button disabled w/ note; **TODO: port
    DateTimeCommand to a `divoomd` device_call leaf** for full parity.
    Added generic `Cmd::Raw`/`Update::Reply` (top-level daemon RPC w/ reply tag,
    stored in `app.replies`) for the remaining tabs; `DIVOOM_UI_TAB` screenshot aid.
  - **GAP-CLOSURE RUN (2026-06-29, "close the gaps across daemon/menubar/app"):**
    closed the daemon gaps + menubar polish. **sync_time** (daemon `set_date_time`
    0x18 + UI button), **cloud login** (daemon `save_credentials` + Settings card,
    unblocks gallery; split cloud_store.rs/cloud_cmds.rs for the 500-line gate),
    **test notification** (was an app gap — leaf existed; added UI control),
    **menubar status-color glyph**. **Sole remaining real gap: a native MCP server
    in divoomd** (the Python MCP is a `divoom_lib.cli mcp-server` subprocess; a
    Python-free bundle needs a Rust MCP stdio JSON-RPC server, ~13 tools → a large
    standalone workstream — needs an explicit go-ahead). Device-dependent niche
    (Custom Art, Hot Channel, audio viz, wall presets) still need hardware.
  - **PHASE 4b DONE — native app verified on hardware + shipped alongside
    (2026-06-29):** drove the real `.app` via computer-use (user approved): launch →
    UI spawns sibling `divoomd` → BLE scan found Tivoo-Max/Timoo/Pixoo (NO TCC
    crash — the embedded Info.plist makes the bundle its own responsible process) →
    connected to Tivoo-Max → UI controls hit the device (Rainbow clock; brightness
    0→read 0→restored 54; volume read back 5/15 on connect). Shipped ALONGSIDE the
    Python app (user picked "both"): `build_native_app.sh` makes
    `Divoom-Native-v0.20.2.dmg`, uploaded to the v0.20.2 release; new cask
    `divoom-control-native` (Projects/homebrew-tap, pushed, brew-style clean,
    brew-fetch verified). Python `divoom-control` cask untouched.
    Install: `brew install --cask ztomer/tap/divoom-control-native`.
  - **NATIVE PACKAGING (2026-06-29, non-destructive part of Phase 4b):**
    `scripts/build_native_app.sh` assembles `dist-native/Divoom Native.app`
    (Python-free: `Contents/MacOS/{divoom-ui, divoomd, libdivoom_compact.dylib}` +
    BT Info.plist, adhoc-signed). The UI spawns the sibling daemon and passes
    `DIVOOMD_ENCODER_LIB` (sibling dylib) so encoding works in the bundle. Separate
    `dist-native/` artifact (gitignored) — does NOT touch the py2app build / cask /
    defaults. Verified assembly+sign+plist; NOT launched (bundled daemon is the BLE
    build → TCC crash from a headless shell). **STILL USER-GATED:** first launch +
    one-time Bluetooth grant, then the actual cutover (flip the default launcher to
    the native app, update the Homebrew cask). Python UI stays the reference.
  - **MCP GAP CLOSED (2026-06-29):** `divoomd mcp` — native MCP stdio JSON-RPC
    server (`native-port/divoomd/src/mcp.rs` + `mcp_tools.rs`), ported from
    `mcp_server.py`/`mcp_tools.py`. Daemon-routed bridge (connects to DIVOOM_SOCKET,
    forwards tools/call → device_call); 13 tools; verified end-to-end + unit-tested;
    added tokio `io-std`. **All daemon/menubar/app parity gaps are now closed.** The
    only un-ported items are device-dependent niche (Custom Art browser, Hot Channel,
    wall presets) + audio-capture (audio visualizer) — need hardware. To use the MCP
    server, point an MCP host at `divoomd mcp` (it needs a running daemon).
  - **FUNCTIONAL PARITY REACHED (2026-06-29, after the /loop-until-parity run, 8
    iterations).** See **`docs/PARITY_TRACKER_NATIVE_UI.md`** for the full per-feature
    record + the "PARITY STATUS" closeout. All portable/verifiable UI features are
    ported (every tab + channel sub-tab, Device Settings+FM, Schedule alarms/
    memorial/timeplan, Live Widgets feeds+temperature, Pixel Art paint+gallery,
    Text push via embedded 5x7 font, read-backs, tray device section). Remaining
    items are BLOCKED, categorized in the tracker: **daemon gaps** (cloud login,
    test notif, sync_time, MCP — need new divoomd commands), **device-dependent
    niche** (Custom Art, Hot Channel, wall presets), **audio capture** (audio viz),
    and **minor polish**. The daemon gaps are the only ones blocking real end-user
    features — they need daemon-side work (user to authorize separately).
  - **EARLIER CORRECTION (2026-06-29):** the initial "Phase 3 complete / feature-
    complete" claim was **overstated** (~1/3 wired); the loop above fixed it. The app shell, most of Channels, and Device Settings are solid; but the
    **Live Widgets tab is mis-mapped** (shows the gallery; should be live data feeds
    — music/stocks/sysmon/weather), the **gallery belongs under Pixel Art**, and
    Sessions/Weather/FM/Memorial/Presets/cloud-login/MCP/notification-routing + many
    read-backs are missing. See **`docs/PARITY_TRACKER_NATIVE_UI.md`** (the live
    "/loop until parity" record). The per-tab bullets below describe what RENDERS,
    not full parity.
  - **Phase 3 (3a/3b/3c)** — all 7 sidebar tabs render (placeholder removed):
    `settings.rs` (notifications start/stop/status, LAN probe/connect, keep-alive,
    MCP deferred), `schedule.rs` (5 alarm slots → `alarm.set_alarm`), `pixel_art.rs`
    (16x16 paint editor → `show_image` rgb kwargs via `Cmd::Raw`), `wall.rs`
    (device slots → `wall_configure`), `widgets.rs` (gallery `fetch_gallery` — item
    count + honest cloud-auth note; thumbnail render deferred). All verified by
    self-screenshot. **Deferred (documented):** gallery thumbnail render + apply
    (needs cloud auth + remote image fetch), Channels Text push (needs bitmap-font
    →image render), Channels Sessions (Sleep Aid), clock color (`set_clock_rich`).
  - **Phase 4a DONE** — `tray.rs`: cross-platform native tray/menubar via
    **tray-icon** (MIT) mirroring `divoom_menubar` — Show Dashboard / Start-Stop
    Notifications (label tracks live state) / Quit. Built lazily on first frame,
    events polled from the eframe loop; same-process (Show Dashboard focuses the
    window). Builds + runs without crash; **the system-menubar item needs USER
    visual confirmation** (can't be captured by the in-app framebuffer screenshot).
  - **REMAINING — Phase 4b (USER-GATED, not done autonomously):** per-OS packaging
    (macOS `.app` + real Info.plist w/ BT strings + `LSUIElement`; codesign; dmg;
    Homebrew cask) and **cutover** (flip the default launcher from the Python GUI to
    `divoom-ui`). Cutover changes what ships + needs the macOS BT grant (physical
    click) + user review — left for the user. Python UI stays the reference, never
    deleted. Also pending: the `sync_time` daemon device_call leaf (task chip
    spawned) to re-enable Device Settings' "Update device time".
  - **How to run/verify the UI:** `cargo build` in `native-port/divoom-ui`; start a
    no-BLE daemon (`divoomd --socket /tmp/x.sock` from a `--no-default-features`
    build) and run `DIVOOM_SOCKET=/tmp/x.sock ./target/debug/divoom-ui`. Headless
    screenshot: add `DIVOOM_UI_SCREENSHOT=out.png` (+ `DIVOOM_UI_TAB=`/`DIVOOM_UI_
    CHANNEL=` to pick the view). Real-device exercise needs the user to start the
    BLE daemon (Claude's shell can't BLE-run it — TCC crash).
  - **Gotcha:** can't BLE-run `divoomd` from Claude's shell (TCC crash) — test the
    UI against the **no-BLE** daemon build. `screencapture` CLI yields a black
    frame (no Screen-Recording grant) → use the in-app self-screenshot instead.
- **PARITY ACHIEVED (2026-06-29, /loop "until parity with Python") — COMPLETE:**
  - **device_call method parity: 54 → 0 gaps** vs the Python Divoom API (excluding
    internal `protocol.*` plumbing). New Rust submodules `device_call/{animation,
    music,drawing}.rs` + additions to basic/system/tools, all ported verbatim from
    `divoom_lib` with wire-byte mock tests pinning payloads + LE/BE orders. Covers
    display channels, control, weather, light/tool read-backs, hot_update, the
    animation gif/user-define primitives, SD-card music, and the drawing-pad
    subsystem (`pic_scan_ctrl` 0x35 ported but flagged UNVERIFIED — no 0x35 in the
    APK). Re-run the audit any time: introspect the Divoom facade, dedupe by
    underlying qualname, diff leaf names vs the Rust `device_call` match arms.
  - **Cloud image decode parity DONE + verified** (the dominant gap): ported
    `media_decoder.resolve_to_gif` — magic 9/18/26 (AES + LZO1X via `minilzo-rs` +
    `_compact_tiles`) + 0xAA → frames → GIF (`src/media.rs`); fixed a real 0xAA bpp
    bug. BYTE-PARITY tests vs Python oracle fixtures (`tests/cloud_fixtures/`).
  - **monthly_best fixed** (connect/disconnect command names) + **gated behind
    `DIVOOMD_MONTHLY_BEST`** (default off; parity with Python's separate opt-in
    daemon).
  - **Rust is now the default daemon** (`DIVOOM_USE_RUST_DAEMON` defaults on when
    `divoomd` is present; Python kept as reference/fallback, **never deleted**).
  - **Device-verified**: the decoded magic-18 cloud animation renders on **Pixoo,
    Tivoo-Max, Timoo** (Ditoo was off-air). `cargo test` 70/70 both matrices; all
    parity verified offline before device pushes.
  - **Open**: re-verify Ditoo when it's back in range; the niche drawing/SD-music/
    animation methods are wire-tested but NOT hardware-verified (no device flows to
    exercise them). The connect-flakiness mitigation (poll-until-found) helps but
    BLE discovery can still miss a sleeping device.
  - **Gotcha:** `tests/test_rust_daemon_parity.py` spawns `target/{debug,release}/
    divoomd` and prefers debug — so `cargo test --no-default-features` (which builds
    a NO-BLE debug binary) makes the BLE/SPP parity tests fail with "BLE support is
    disabled". Run `cargo build` (default features) before the Python parity suite.
  - **Parity verified complete across ALL dimensions:** top-level socket commands
    (0 gaps, Rust superset), device_call methods (0 gaps — leaf + exact dotted
    string; the few client calls to non-existent methods degrade identically),
    LAN methods (0 gaps), cloud decode (byte-verified). The loop's goal is met.

- **NATIVE PORT HARDENING — Phases 1–4 DONE; Phase 5 gated (2026-06-28):**
  Phase 4 Tier B was verified on a **real Timoo over BLE** via the granted `.app`
  (grant persisted, autonomous): scan → connect → brightness round-trip (read-backs
  work) → exclusive gating → MCP-via-Rust `set_brightness(level=65)` → disconnect.
  Two bugs surfaced + fixed HW-verified: BLE `connect` poll-until-found (was a single
  3s window → reconnect misses; 3/3 clean no-pre-scan reconnects now) and a missing
  `shutdown` command (added; clean exit confirmed). Phase 5 is **gated** — see Open
  threads: top-level commands reached parity (`shutdown`/`probe_lan`/`sync_artwork`)
  but verification then exposed a deeper cloud image-decode gap (magic 9/18/26/0xAA),
  and per user directive the Python backend is to be **archived as reference, never
  deleted**.
  - **Phase 1 (commit `f7e0e7c`):** fixed the broken `--no-default-features` build.
    Root cause: the `DeviceTransport` device-I/O method layer was `ble`-gated even
    though it delegates to non-ble Spp/Lan/Mock, and `BleResult` lived in the gated
    `ble` module. Fix: relocated `BleResult` to `transport.rs` (ble.rs re-exports),
    un-gated the method layer + `NativeEncoder`/`encoder()` + `device_call` (gating
    only the inner `DeviceTransport::Ble` arms via `!matches!(Lan)`), and rewrote
    `wall.rs` to use the enum method layer (also fixed a latent Spp/Mock wall
    silent-fail). **`cargo test` = 62 green; `cargo test --no-default-features` = 62
    green.** The full command surface + MockTransport now build/test hardware-free.
  - **Phase 2 (commit `762c6ad`):** added `rust-core` (ubuntu, no-ble gate) and
    `rust-ble` (macos, full ble) jobs to `.github/workflows/tests.yml`. This is the
    gate that would have caught the e4bd424 regression.
  - **Phase 3 (500-LOC):** split `live_jobs.rs` (965) →
    `live_jobs/{mod(428),render(290),music(245)}.rs`; trimmed `daemon.rs` (502→482,
    moved `find_encoder_lib` into `native_encode.rs`). Added
    `tools/check_file_size.py` (500-line gate) → CI + pre-commit. No file violates.
  - **Phase 4 Tier A (hardware-free E2E):** `test_mock_exclusive_mode_gating`
    (Rust: acquire/steal-reject/foreign-token-deny/release/re-acquire + wire bytes)
    and `test_rust_mcp_via_daemon` (Python: MCPServer + DaemonDeviceProxy →
    spawned Rust daemon → `device_call` round-trip). Rust 63/63 both matrices;
    parity suite 12 passed / 1 skipped.
  - **Phase 4 Tier C (best-effort, no Win/Linux hardware):** added
    `rust-ble-linux` + `rust-ble-windows` `continue-on-error` compile-only CI jobs.
    Real-radio on those OSes is explicitly out of scope (no hardware) — never
    claimed verified.

- **Phase 5 commands (2026-06-28 late):** added `probe_lan` + `sync_artwork`
  (HW-verified) — top-level socket commands now match the Python daemon. BUT
  verification exposed a deeper gap below.

### Open threads

- **CI `tests` workflow red (RESOLVED 2026-07-13).** Was one deterministic
  failure: `tests/test_gui_api.py::TestDivoomGuiAPI::test_connect_single_device`
  mocked `self._daemon_client` but `connect_single_device` routes through
  `self._client()` → R57 `reconnect_daemon()` which resets the client + re-runs
  `ensure_daemon()` (real daemon → timeout). Fixed to patch
  `divoom_gui.daemon_bridge.ensure_daemon`. `tests/test_gui_api.py`: 55 passed.
  Pre-existing (R47 `_client()` seam), surfaced only because CI has no daemon.
  Not an R60 regression.
- **Event-driven audit — fully event-driven (RESOLVED 2026-07-13).** `divoomd`
  broadcasts `status`/`owned_devices`/`hot_progress`/`degraded` via
  `tokio::sync::broadcast`; GUI subscribes + forwards to `onDaemonEvent`/
  `onOwnedDevices`/`onNotifStatus`/`onHotProgress`. The 4s `refreshConnectionState`
  heartbeat is **no longer scheduled** (R59 removed the interval). Remaining
  `setInterval`s are legitimate external-data polls in `widgets.js`
  (weather/stock/sysmon/music — no device event source). **Minor cleanup (optional,
  not blocking):** `gallery_hot.js::pollProgress` is dead code (defined, never
  `setInterval`'d; live path is `onHotProgress`) — delete it.
- **Device-status tests updated to the event model (RESOLVED, committed after v0.22.2).**
  `tests/test_device_status.py` (backend honesty), `tests/test_e2e_device_status_chips.py`,
  `tests/test_e2e_device_status_dot.py` now drive the R59 live handlers
  (`window.Divoom.onDaemonEvent` / `onOwnedDevices`) instead of the dead `refreshConnectionState`
  / `refreshOwnedDevices` polls (which have no callers anymore — the 4s heartbeats are gone).
  The rewrite **caught a real bug**: `onDaemonEvent` ignored `state:"disconnected"` when
  `connected:true`, so a daemon reporting that honest state (the P6 regression case) was
  shown as connected. Fixed in `divoom_gui/web_ui/connection_events.js` — an explicit
  `disconnected` state now flips the dot + `appConnected` to false. **Released in v0.22.3.**
- **BLOCKER — cloud image-decode parity: RESOLVED (verified R60).** The native
  daemon's `media::resolve_to_gif` (`divoomd/src/media.rs`) already decodes magic
  9 (AES), 18/26 (AES + **LZO via `minilzo_rs`**), 0xAA (hot palette-delta) →
  animated GIF, plus GIF/PNG/JPG + magic-43. `sync_artwork`/`monthly_best` call it
  (so magic 9/18/26/0xAA now render; only a truly unrecognized container
  honest-errors). The earlier "MISSING: LZO / frame→GIF" note was STALE — the code
  was completed in a later round but the docstrings weren't updated. R60 stripped
  the false "not ported" docstrings (`sync_artwork.rs:7`, `art_codec.rs:134`,
  `monthly_best.rs:204`). Remaining: **hardware re-verify** the 4 magics render on
  the 4 devices (R60 #2) — the device is kept in the loop per standing directive.
  Plan + verified status: `docs/PLANNING_ROUND60.md`.
- **device_call method-level parity audit: RESOLVED (verified R60).** ROADMAP +
  `PLANNING_NATIVE_PORT_HARDENING.md` Phase 4 Tier A/B confirm 54→0 gaps vs the
  Python Divoom API; dispatch in `divoomd/src/device_call/mod.rs:32` (+ per-module
  `handle`). **R60 #4 DONE (v0.22.4):** added `tests/test_device_call_parity.py`
  (hardware-free static guard) which caught 15 key-alias gaps (`system.*` /
  `sound.*` / `device.get_work_mode` prefixes the Rust side only handled under a
  different group) — closed by adding alias arms in `mod.rs` + each submodule
  `handle`. `divoomd` now accepts the exact Python facade keys.
- **Phase 5 default-flip: RESOLVED (verified R60).** `daemon_client.py:200-208`
  already defaults to the Rust daemon when the binary is present (explicit
  `DIVOOM_USE_RUST_DAEMON=0/1` overrides). The `5.1` checkbox in
   `PLANNING_NATIVE_PORT_HARDENING.md` was stale; ticked in R60. Phase 5 *archival*
   (mark Python daemon reference-only, never delete) **DONE in v0.22.5** — REFERENCE/FALLBACK
   banners added to `divoom_daemon/__init__.py`, `daemon.py`, `device_owner.py`; hardening-plan
   Phase-5 wording corrected to "archive, not delete." Python still selectable via
   `DIVOOM_USE_RUST_DAEMON=0`.
- **Phase 5 archival = ARCHIVE, NOT DELETE (user directive 2026-06-28, superseded
  2026-07-13).** The 2026-06-28 directive was to keep `divoom_daemon` in-tree as
  reference/fallback, never delete. **RESOLVED/SUPERSEDED (2026-07-13):** explicit
  fresh sign-off ("the python daemon version can be archived") authorized the
  actual move — server-only modules `git mv`'d to `archive/divoom_daemon/`
  (history preserved, still importable, just not built/run/tested by default).
  See this file's top "Current state" entry for the 2026-07-13 round and
  `docs/ROADMAP.md`'s "Native Rust daemon" section for the full detail. No
  longer an open thread.
- _(RESOLVED this round: all of Phase 4 — Tier A, B (real device), C; plus the BLE
  connect-robustness bug and the `shutdown` parity gap.)_

- **DOC CLEANUP — native-port docs retired/pruned (2026-06-28):** Retired the
  obsolete `docs/PLANNING_NATIVE_PORT.md` (original evaluate-and-plan doc, fully
  executed now that the port shipped R54–R56); its decision summary moved into
  `docs/ROADMAP.md` and its 5 source-comment references were repointed there.
  Pruned this handoff's long R53.x-and-older tail (history retained in CHANGELOG +
  git). The active forward plan for the Rust port is
  `docs/PLANNING_NATIVE_PORT_HARDENING.md`.

- **RUST MOCK TRANSPORT & TEST COVERAGE INFRASTRUCTURE (2026-06-28):**
  Implemented MockTransport for offline Rust daemon testing and shipped 4 new E2E mock tests verifying wire byte patterns for core commands. This enables testing device_call serialization without real hardware.

  **Changes shipped:**
  - `src/mock_transport.rs` [NEW]: `MockTransport` struct with `send_command()` that logs `(cmd_id, payload)` tuples into a `Vec<(u8, Vec<u8>)>` and simulates generic ACK responses.
  - `src/mock_device_tests.rs` [NEW]: 4 `#[tokio::test]` E2E tests — `set_clock_rich` (0x45 APK C2 layout), `show_clock` (0x45 hass-divoom layout), `set_brightness` (0x74), `set_volume` (0x08). All assert exact wire byte patterns.
  - `src/transport.rs`: Added `Mock(MockTransport)` variant to `DeviceTransport` enum with delegated trait methods.
  - `src/daemon_connect.rs`: Added `{"mock": true}` connect path + `Mock` arm in `cmd_disconnect`.
  - `src/device_call/mod.rs`: Added `DeviceTransport::Mock(_)` to the BLE-like device gate.
  - `src/wall.rs`, `src/daemon.rs`, `src/macos_notifications.rs`: Added exhaustive `Mock(_)` match arms.
  - `scripts/rust_coverage.sh` [NEW]: Helper script for `cargo-llvm-cov` code coverage reporting.

  **Tests:** Rust **62 tests passed** (11 lib + 46 integration + 4 mock + 1 native-encode); Python **16 passed, 1 skipped** (daemon parity suite).

- **NATIVE PORT: DIVOOM CLOUD AUTHENTICATION, GALLERY SYNC, MONTHLY BEST LOOP, & CLOCK OVERLAY ALIGNMENT (2026-06-28):**
  Successfully completed the remaining native port features in the Rust daemon (`divoomd`) to achieve 100% parity with the authoritative Python daemon and library. The daemon can now run completely standalone, handling cloud logins, category file queries, scheduled monthly best background scrapers, precompiled animation streams, and APK-aligned clock layouts.

  **Changes shipped:**
  - `src/cloud.rs` [NEW]: Ports email login (`POST /UserLogin`), guest HMAC-MD5 signing (`POST /User/NewGuest`), UTC time sync, configuration parser (`config.ini`), cache manager (`auth_token.json` with 0o600 file write), cloud gallery categories retrieval (`/GetCategoryFileListV2`), and failure cooldown mechanism. Contains 5 inline unit tests verifying crypt/cache lifecycles.
  - `src/monthly_best.rs` [NEW]: Ports the background scraper ticker loop which polls `hotchannel.json`, extracts Magic 43 container GIFs, connects to target displays on interval, downsamples files, and streams native animation payloads.
  - `src/device_call/basic.rs`: Implemented `"animation.stream_animation_8b"` for precompiled stream uploads and `"display.set_clock_rich"` for APK C2() aligned clock coordinate layouts.
  - `src/daemon.rs`: Exposed `"get_credentials"`, `"get_cached_credentials"`, and `"fetch_gallery"` socket dispatch endpoints.
  - `src/lib.rs` & `src/main.rs`: Registered new modules and spawned the `monthly_best` background loop task at daemon startup.
  - `Cargo.toml`: Added `md-5` and `hmac` dependencies.
  - `tests/test_rust_daemon_parity.py`: Shipped `test_rust_cloud_auth_endpoints`, `test_rust_fetch_gallery`, and `test_rust_set_clock_rich` integration tests verifying all new socket calls.

  **Tests:** Rust 58 passed; Python 1703 passed, 87 skipped. (Verified with new unit and integration tests).


- **NATIVE PORT: BLUETOOTH CLASSIC SPP INTEGRATION VIA PYTHON SUBPROCESS BRIDGE (2026-06-28):**
  Successfully implemented Bluetooth Classic SPP support in the native Rust daemon (`divoomd`) using a lightweight Python subprocess bridge (`spp_bridge.py`). This allows the native daemon to connect to older classic SPP devices (e.g. Tivoo-Max) by reusing the proven Python `BTSppTransport` stack under the hood, bypassing complex Objective-C/IOBluetooth binding issues.

  **Changes shipped:**
  - `divoom_daemon/spp_bridge.py` [NEW]: Standard JSON-line standard I/O bridge wrapping `BTSppTransport` for classic Bluetooth connection management.
  - `native-port/divoomd/src/spp.rs` [NEW]: Native Rust `SppTransport` implementing tokio process spawning, input/output piping, and `0x8B` animation streaming parity.
  - `native-port/divoomd/src/transport.rs`: Added the `Spp` variant to `DeviceTransport` and delegated all relevant transport calls.
  - `native-port/divoomd/src/daemon_connect.rs`: Routed connection requests to `SppTransport` when `use_ios_le_protocol` is `false`.
  - Exhaustive match coverage updated across `daemon.rs`, `live_jobs.rs`, `wall.rs`, `art.rs`, `art_hot.rs`, and `macos_notifications.rs` to handle `DeviceTransport::Spp` cleanly.
  - `tests/test_rust_daemon_parity.py`: Shipped `test_rust_spp_connect_failure_integration` E2E test verifying dynamic python bridge subprocess spawning/error propagation, and added `test_rust_hardware_parity` executing live scans, connection, get/set brightness, and disconnection on real Divoom hardware (Tivoo-Max).
  - Renamed manual smoke-test `test_display_aliases.py` to `smoke_display_aliases.py` to fix pytest collection.

  **Tests:** Rust 51 passed; Python 1702 passed, 87 skipped. (Verified with new integration and hardware tests).

- **NATIVE PORT: ALIGN NOTIFICATION SERVICE, COMMAND SCHEMAS, TCP/TOKEN AUTH, --mac OPTION & RUST AUTO-SPAWN (2026-06-28):**
  Aligned the native Rust daemon's macOS notification service monitor (`macos_notifications.rs`), routing, and command responses with the ground-truth Python daemon. Ported the headless TCP server listener, token authentication features, and `--mac` option default address configurations. Shipped the `DIVOOM_USE_RUST_DAEMON` auto-spawner integration in the Python clients and GUI launcher.

  **Changes shipped:**
  - `src/macos_notifications.rs`: Refactored to query the Notification Center SQLite DB (Sonoma/Sequoia paths + Group Containers fallback) using a read-only `rusqlite` connection (removing `sqlite3` CLI subprocess calls). Parsed binary plists with the `plist` crate to retrieve `app`, `title`, and `body` fields. Implemented routing and tracking for `seen`, `routed`, and `dropped` counters, duplicate suppression, and health checks.
  - `src/daemon.rs`: Aligned `get_status`, `start_notifications`, `stop_notifications`, `notification_status`, and `set_routing` command payloads and response shapes to be identical to the Python daemon. Exposed status and notification events to socket subscribers. Relocated `DeviceTransport` to `src/transport.rs` and moved argument/blob parsing into `src/device_call/mod.rs` to keep `daemon.rs` strictly under 500 lines. Updated `device_status` to return the stored default MAC when disconnected.
  - `src/main.rs`: Supported `--host`, `--port`, `--token`, and `--mac` CLI flags (with `DIVOOM_DAEMON_TOKEN` env variable fallback). Enforced token requirement when binding to a TCP port, and wired TCP listener concurrently with Unix listener. Passed the default MAC config to the Daemon.
  - `src/socket_server.rs`: Made `serve_connection` generic over the stream type (`AsyncRead + AsyncWrite + Unpin`) to serve both Unix and TCP streams. Added `serve_tcp` and implemented constant-time comparison for token verification.
  - `tests/test_rust_daemon_parity.py`: Shipped a new Python integration test suite verifying the socket response shapes, token auth, and default MAC address config of the compiled Rust daemon subprocess using Python `DaemonClient`.
  - `divoom_daemon/daemon_client.py`: Added support for `DIVOOM_USE_RUST_DAEMON` inside `spawn_daemon()`, enabling Python clients/GUI launcher to dynamically auto-spawn and run the compiled Rust `divoomd` daemon instead of the default Python daemon.

  **Tests:** Rust 51 passed; Python 1711 passed, 87 skipped. (Verified with new integration tests).

- **NATIVE PORT: ART SYNC, HOT-UPDATE, WALL, LIVE JOBS, macOS NOTIFICATIONS + 500 LOC SPLITS (2026-06-26):**
  Ported the remaining high-level subsystems to the native Rust daemon (`divoomd`). All files comply with 500 LOC.

  **New modules shipped:**
  - `art.rs` (331): custom art push/query, cloud CDN download, hot-update dispatch
  - `art_codec.rs` (197): AES-128-CBC (pure Rust), magic-43/9/0xAA frame decoders, image rescale
  - `art_hot.rs` (251): hot-update manifest, SHA-1 verify, BLE chunk streaming
  - `wall.rs` (457): DivoomWall multi-panel coordinator + `cmd_wall_configure` (moved from daemon.rs)
  - `live_jobs.rs`: background widget loops (system monitor, stocks, weather, music album cover)
  - `macos_notifications.rs` (233): SQLite `usernoted` monitor via sqlite3 CLI, ANCS push
  - `daemon_connect.rs` (83): connect/disconnect/scan extracted from daemon.rs

  **Refactored:**
  - `daemon.rs` (498): thin delegations; `tx` field made `pub(crate)`
  - `lib.rs`: all new modules registered
  - `ble.rs`: `wait_for_any_response` for hot-update multiplexing
  - `lan.rs`: `probe()` method for LAN validation

  **Tests:** Rust 51 passed; Python 1686 passed, 87 skipped.
  Playwright UI failures (12 + 6 errors) are pre-existing missing-browser-binary issues, unrelated.

  **Commit:** `7cb5240`

  Modularized the native Rust daemon's (`divoomd`) `device_call` commands logic to strictly adhere to the 500 LOC limit constraint:

  **Modularization:** Extracted all inline command match arms and helper functions out of `daemon.rs` and moved them into submodules inside the `src/device_call/` directory:
  - `src/device_call/basic.rs` (305 lines)
  - `src/device_call/alarm.rs` (254 lines)
  - `src/device_call/sleep.rs` (198 lines)
  - `src/device_call/timeplan.rs` (102 lines)
  - `src/device_call/tools.rs` (150 lines)
  - `src/device_call/text.rs` (150 lines)
  - `src/device_call/game.rs` (90 lines)
  - `src/device_call/design.rs` (120 lines)
  - `src/device_call/system.rs` (285 lines)
  This shrunk `daemon.rs` from 1944 lines down to **317 lines**, bringing the entire daemon repository in line with the 500 LOC rule.

  **Feature Gating & Clean Compilation:** Gated the submodules in `mod.rs` and all BLE-specific imports/fields in `daemon.rs` behind `#[cfg(feature = "ble")]` to ensure warning-free and error-free compilation both with and without default features.

  **E2E & Parity Tests:** All 55 Rust tests pass successfully. Full Python pytest suite passes cleanly with 1706 passed, 87 skipped.

- **NATIVE PORT: SCHEDULING COMMANDS (2026-06-23 14:35 EDT):**
  Ported the alarm, sleep, and timeplan scheduling commands to the native Rust daemon (`divoomd`):

  **Alarm:** Ported `alarm.get_alarm_time`, `alarm.set_alarm`, `alarm.set_alarm_gif`, `alarm.get_memorial_time`, `alarm.set_memorial_time`, `alarm.set_memorial_gif`, `alarm.set_alarm_listen`, `alarm.set_alarm_volume`, and `alarm.set_alarm_volume_control` (with direct name and alias dispatch). Deserialized and parsed 10-byte alarm info blocks and 39-byte memorial blocks.

  **Sleep:** Ported `sleep.show_sleep`, `sleep.get_sleep_scene`, `sleep.set_sleep_scene_listen`, `sleep.set_scene_volume`, `sleep.set_sleep_color`, `sleep.set_sleep_light`, and `sleep.set_sleep_scene` (with direct name and alias dispatch). Deserialized and parsed 10-byte sleep scene status blocks.

  **Timeplan:** Ported `timeplan.set_time_manage_info` and `timeplan.set_time_manage_ctrl` (with direct name and alias dispatch). Mapped to command codes `0x56` and `0x57` respectively.

  **E2E & Parity Tests:** Updated the `ported_commands_route_to_device_call` integration test in `tests/daemon_behavior.rs` to verify that all newly implemented commands and their aliases correctly match in the router and dispatch to the device transport. Verified both compilation and test suite correctness with and without the `ble` feature gate. Full Python pytest suite passes with 1706 passed, 87 skipped.

- **NATIVE PORT: TOOL & NOTIFICATION COMMANDS (2026-06-23 14:30 EDT):**
  Ported the device tool commands (scoreboard, timer, countdown, noise meter) and notification display commands to the native Rust daemon (`divoomd`):

  **Scoreboard:** Ported `"scoreboard.set_scoreboard"`, `"set_scoreboard"`, `"scoreboard.get_scoreboard"`, and `"get_scoreboard"` (0x71/0x72 commands with type 1).

  **Timer:** Ported `"timer.set_timer"`, `"set_timer"`, `"timer.get_timer"`, and `"get_timer"` (0x71/0x72 commands with type 0).

  **Countdown:** Ported `"countdown.set_countdown"`, `"set_countdown"`, `"countdown.get_countdown"`, and `"get_countdown"` (0x71/0x72 commands with type 3).

  **Noise Meter:** Ported `"noise.set_noise"`, `"set_noise"`, `"noise.get_noise"`, and `"get_noise"` (0x71/0x72 commands with type 2).

  **Notification Display:** Ported `"device.show_notification"`, `"show_notification"`, `"notification.show_notification"`, `"device.show_notification_text"`, `"show_notification_text"`, and `"notification.show_notification_text"` (0x50 command handling icon-only and icon+text variations).

  **E2E & Parity Tests:** Updated the `ported_commands_route_to_device_call` integration test in `tests/daemon_behavior.rs` to verify that all newly implemented commands and their aliases correctly match in the router and dispatch to the device transport. Verified both compilation and test suite correctness with and without the `ble` feature gate. Full Python pytest suite passes with 1706 passed, 87 skipped.

- **NATIVE PORT: REMAINING DEVICE CALL COMMANDS (2026-06-23 10:23 EDT):**
  Ported the rest of the high-value `device_call` commands to the native Rust daemon (`divoomd`):
  
  **Volume Control:** Ported `"music.get_volume"`, `"get_volume"`, `"music.set_volume"`, and `"set_volume"` (0x08/0x09 commands).
  
  **FM Radio:** Ported `"radio.set_radio_frequency"`, `"set_radio_frequency"`, `"radio.set_radio"`, and `"set_radio"` (0x61 command) taking a 2-byte little-endian frequency.
  
  **Low Power Switch:** Ported `"device.get_low_power_switch"`, `"get_low_power_switch"`, `"device.get_low_power"`, `"get_low_power"`, `"device.set_low_power_switch"`, `"set_low_power_switch"`, `"device.set_low_power"`, and `"set_low_power"` (0xb2/0xb3 commands).
  
  **Auto Power Off:** Ported `"device.get_auto_power_off"`, `"get_auto_power_off"`, `"sound.get_auto_power_off"`, `"device.set_auto_power_off"`, `"set_auto_power_off"`, and `"sound.set_auto_power_off"` (0xab/0xac commands) taking a 2-byte little-endian minutes.
  
  **E2E & Parity Tests:** Added the `ported_commands_route_to_device_call` integration test to verify that all newly implemented commands are correctly matched in the router and dispatch to the device transport (failing honestly with "no device connected"). Verified both compilation and test suite correctness with and without the `ble` feature gate. Full Python pytest suite passes with 1706 passed, 87 skipped.

- **NATIVE PORT: EVENT SUBSCRIPTION & DEVICE NAME COMMANDS (2026-06-23 10:15 EDT):**
  Four changes in the native Rust daemon (`divoomd`):

  **Event Subscription & Broadcast:** Extended the socket server with support for the
  `"subscribe"` command. When a client connects and subscribes, the server immediately
  replies with the initial status snapshot (`{"type":"status", "state":"idle"}` or `"active"`)
  and then holds the connection open, streaming real-time broadcast events (such as BLE
  connection state changes). We use `tokio::select!` to multiplex socket reading (to detect
  peer disconnects) and event broadcasting (from a shared `tokio::sync::broadcast::Sender`),
  achieving self-cleaning, resource-safe event delivery.
  
  **Friendly Name Cache:** Added a thread-safe `device_name` cache (`Mutex<Option<String>>`)
  to `BleTransport` to avoid redundant BLE name queries (0x76 read is slow/flaky on some models).
  The cache is populated from peripheral advertisement properties on connect.
  
  **New Device Commands:** Ported `"device.get_device_name"` (retrieves from cache, falling back
  to 0x76 BLE query) and `"device.set_device_name"` (writes via 0x75 BLE command and updates cache).
  
  **E2E & Parity Tests:** Added `subscription_and_event_broadcast` integration test to verify the
  subscriber socket, and `device_name_commands_route_to_device_call` to check command dispatch.
  All Rust tests pass (with and without `ble` feature). E2E-smoke-tested `test_subscribe.py` against
  real Divoom hardware: successfully subscribed, connected, and observed the broadcasted status
  transition (`idle` -> `active`). Python suite: 1706 passed, 87 skipped.

- **FEISHIN + KASET + CARD PADDING ROUND (2026-06-23 00:45 EDT):** Three changes.

  **Feishin album art integration:** Added `/Applications/Feishin.app` (Electron-based
  Navidrome client) as the first-checked now-playing source in
  `media_source.py:get_current_playing_track()`. The integration works by:
  1. Checking if Feishin is running via `pgrep`
  2. Extracting Navidrome Subsonic API credentials from Feishin's Chromium Local
     Storage (LevelDB files at `~/Library/Application Support/Feishin/Local Storage/leveldb/`)
  3. Querying the Navidrome `/rest/getNowPlaying.view` Subsonic API endpoint
  4. Building a cover art URL from `/rest/getCoverArt.view` when available
  Credentials are cached for 60s to avoid repeated LevelDB file scans. The Navidrome
  server URL + auth params (`u=...&s=...&t=...`) are extracted via regex scanning of
  the LevelDB .ldb/.log files. Tests: 4 new Feishin-specific tests + updated Spotify
  test for the new check order (12 total, all pass).

  **Kaset album art integration:** Added `/Applications/Kaset.app` (YouTube Music
  client for macOS) as a now-playing source (checked second). Kaset's AppleScript
  `get player info` returns a JSON blob with an `artworkURL` (YouTube thumbnail),
  so callers skip the iTunes Search API for Kaset-originated tracks. All three callers
  (`live_jobs.py:run_music()`, `media_sync.py:get_current_track_info()`,
  `media_sync.py:push_music_cover_now()`) fall back to the iTunes API when no direct
  URL is provided (Spotify/Apple Music paths unchanged).

  **Card padding tightened:** `.card` padding reduced from `20px` → `12px`,
  `--panel-gap` from `20px` → `12px`, `.card-header` margin-bottom from `15px` → `10px`
  in `style.css`. This brings general tab panels (settings, routines, tools) to the same
  density as tile components.

- **TIVOO-MAX SPP ROUTING FIX (2026-06-22 23:45 EDT):** Debugged why Tivoo-Max BLE
  connections fail. Investigation found 2 bugs in the SPP routing code:

  **Bug 1: `owner_connect.py:_ensure_device_async` (line 118)** — hardcoded
  `use_ios_le_protocol=False` for ALL devices on the daemon's auto-reconnect path.
  When a Tivoo-Max is auto-discovered (no specific mac requested), the daemon creates
  a `Divoom` with `use_ios_le_protocol=False`. The SPP routing code (`connection.py:82`)
  sees this falsy value and, because the device name contains "tivoo", switches to
  Bluetooth Classic SPP transport instead of BLE. SPP on macOS has a known "Tahoe
  reconnection bug" that produces opaque timeouts. Fix: changed to `use_ios_le_protocol=None`
  so the autoprobe dynamically determines the correct BLE protocol.

  **Bug 2: `connection.py:connect` (line 82)** — SPP routing condition was
  `not self.use_ios_le_protocol`, which fires for BOTH `False` (explicit Basic protocol)
  AND `None` (unknown/unprobed). When protocol is unknown, `BLETransport.connect()` runs
  the autoprobe to determine iOS-LE vs Basic over BLE — SPP should NOT pre-empt that.
  Fix: changed to `self.use_ios_le_protocol is False` so SPP routing only fires when
  explicitly set to Basic protocol.

  Also added `test_spp_not_routed_for_unknown_protocol` to codify the fix. Updated
  `test_spp_connection_resolution` to use explicit `use_ios_le_protocol=False`.
  Suite: 1701 passed, 87 skipped.

- **CASK RELEASE / SCAN-TIMEOUT BACKSTOP FIX ROUND (2026-06-22 23:30 EDT):** After the
  cask install, `brew reinstall --cask divoom-control` succeeded but the user reported
  the app "can't detect any device — connects to one device (Tivoo) then gets stuck".
  Investigation found 3 bugs:

  **Bug 1: Backstop doesn't cancel the coroutine.** `owner_loop.py:_run_on_loop` runs
  scan coroutines on the device loop via `asyncio.run_coroutine_threadsafe`. The 90s
  backstop (`_SCAN_RESULT_TIMEOUT`) fires with a `TimeoutError` but the Future was never
  saved — so `future.cancel()` was unreachable. The scan coroutine kept running for the
  full user-configured timeout (e.g. 360s), consuming BLE resources and blocking
  subsequent operations. Fix: save the Future and cancel on backstop timeout.

  **Bug 2: Scan timeout > backstop = guaranteed failure.** The user's `config.ini`
  had `timeout = 360s`. The daemon `owner_connect.py:scan()` passed it straight to
  the BLE scan, but `_run_on_loop` only waits 90s. Every scan with timeout > 90s was a
  guaranteed failure (backstop fires, scan reported as failed, but coroutine runs for
  remaining 270s). Fix: cap scan timeout to `_SCAN_RESULT_TIMEOUT` (90s) at the daemon
  level, with a warning log.

  **Bug 3: HTML input max bypassed by JS config load.** The `<input id="scan-timeout"
  max="120">` was bypassed when `app_init.js:load_config()` set `el.value = conf.timeout`
  (e.g. 360). HTML `max` only applies to user interaction, not programmatic `.value`
  assignment. Fix: clamp to `el.max` before setting the value.

  The stale `last_connected_device` UUID (not in scan results) causes a 16s auto-connect
  timeout before the daemon falls back to a 3s reconnect scan and connects to the first
  available device (Timoo). The Tivoo connection timeout is a separate BLE issue
  (device-specific, not a code regression). Suite: 1700 passed, 87 skipped.

- **RELEASE CUT ROUND (2026-06-22 21:58 EDT): Cut release v0.20.0 (Claude).**
  Cut the `v0.20.0` release including the startup packaging fix and native Rust daemon port (Phase 2 progress).
  - Version bumped to `0.20.0` in `pyproject.toml` and documented in `CHANGELOG.md` and `docs/release_notes_v0.20.0.md`.
  - Rebuilt the app bundle (`dist/Divoom-v0.20.0.dmg`) and pushed `main` branch + tag `v0.20.0` to GitHub.
  - Updated the Homebrew cask with the new `.dmg` SHA-256 (`42bb39b1...`) in `homebrew-tap` and pushed.
  - Note: GitHub release creation via `gh` CLI failed with 401 Bad Credentials in this environment, so the user needs to execute the `gh release create` command manually (see details in final output).

- **HW ROUND (2026-06-22 17:10 EDT): native C image encoder — divergence FIXED + revived (Claude).**
  Two bugs: (1) `image_encode.c` static header was 6 bytes — the NN palette-count byte at
  `out_buf[6]` got clobbered by the palette memcpy (palette landed on byte 6), diverging from
  Python's correct 7-byte header; fix `static_header_size = 7`. (2) Both `image_encoder.py` wrappers
  allocated `(w*h+7)//8` (1 BIT/pixel) but the C worst-case check needs `w*h` (8 bits/pixel), so the
  C returned -1 for any real frame → silent Python fallback (native image encode was DEAD for
  16x16+). Fix: allocate `7 + 256*3 + w*h`. Now byte-identical to Python across all sizes/colours
  (static AND frame) AND actually reached. Dylib rebuilt + committed. HW: pushed the test animation
  to Pixoo-1 via the revived native path → `result:true`, identical behaviour. Teeth: direct-C-path
  tests (`test_c_static_*`) that bypass the wrapper fallback — 17 fail against the pre-fix dylib.
  **ALL named HW-deferred items are now cleared.** Remaining NOT-testable-on-this-fleet: SPP
  transport + live-job-double-poller (BLE-only Pixoo/Timoo/Tivoo; no RFCOMM/SPP device). R45 #1
  "Custom Art channel empty" still needs eyes on the device screen (can't validate headless).

- **HW ROUND (2026-06-22 12:43 EDT): 0x8B animation retransmit dead-path FIXED (Claude).** The
  0x8B streamer set the response scalar to 0x8B before START, but the start-ACK wait CLEARS it —
  so for the chunk loop + retransmit window the scalar was None and 0x8B isn't a generic-ACK, so
  the handler DROPPED every unsolicited retransmit request; `_serve_8b_retransmits` then timed out
  "done" and a lost chunk was silently unrecoverable (stream still returned True). Fix:
  `stream_animation_8b` adds 0x8B to `_listen_commands` for the stream (removed in finally) so the
  handler's is_listened branch queues retransmit frames without consuming the scalar. HW-validated:
  pushed a 2-frame test GIF to Pixoo-1 (`display.show_image`) — device start-ACKed, chunk streamed,
  retransmit phase quiet, push True; the working push is NOT perturbed. Teeth: wiring + handler-
  mechanism tests (the old retransmit test mocked wait_for_response, never hit the real handler).
  Remaining HW-deferred: native C static-encoder; SPP/live-job-double-poller NOT testable on this
  BLE-only fleet.

- **HW ROUND (2026-06-22 12:40 EDT): ACK ≠ device-confirmed honesty (Claude).** custom-art and
  hot-update both reported `success:True` on bare GATT write-ACKs with no device confirmation.
  HW-confirmed on Pixoo-1 that the only verification channel is unusable — **0x8E query_page
  times out at 4 s on every page, returns empty** — so we can't verify and won't add a 4 s dead
  wait. Fix surfaces honest status: `custom_art_push` returns `device_confirmed:False` (GUI toast
  "sent" not "pushed"); `hot_update._stream_file` now returns `(ok, confirmed)` and each `served`
  entry + a top-level `confirmed` count distinguishes device-confirmed files from streamed-but-
  silent ones. Teeth: `test_silent_device_file_marked_unconfirmed`. NOT verified via 0x8E (HW-
  unreliable). NOTE: the deeper R45 #1 "Custom Art channel empty" functional regression needs eyes
  on the device screen (can't validate headless) — still open. Remaining HW-deferred: 0x8B
  retransmit dead path, native C static-encoder, push smoke.

- **HW ROUND (2026-06-22 12:25 EDT): exclusive steal-reject — hang-then-steal FIXED (Claude).**
  Validating the deferred exclusive-mode item on the live Pixoo-1 surfaced a real bug: a
  competing `exclusive_start` hung exactly 30 s (the `exclusive_timeout`) then SILENTLY STOLE
  the lock and reported success. Root cause: `exclusive_start` acquired by submitting
  `acquire(token)` through the GATED queue — a lock-acquire gated by the lock it seeks. The
  foreign-token `acquire` never dispatched (the gate only runs the owner's items), so the clean
  "held by another session" reject was unreachable; the G3 idle deadline force-released the real
  owner and the waiter stole. Fix: `CommandQueue.acquire_now(token)` runs `acquire` straight on
  the loop (off the dispatch queue — no device I/O in `acquire`). `exclusive_start` uses it and
  returns the honest error. HW re-validated: steal rejects in 0.00 s; idempotent re-acquire +
  post-release acquire still work. Teeth: `test_acquire_now_rejects_steal_immediately`. Suite
  1680 green. ALSO HW-validated (no change): the **wrong-device guard** — a `device_call` with a
  mac different from the held device does NOT silently read/write the cached device; it releases
  + attempts the requested target and fails honestly if unreachable (`get_brightness(mac=BOGUS)`
  → `success:false "timed out"`, never the held Pixoo's 60). **Working harness: the dev-daemon `.app` (`open "dist/Divoom Dev Daemon.app"`)
  runs live repo code under its own BLE grant — restart it to load each fix, then drive it over
  `/tmp/divoom.sock` with `DaemonClient`.** Remaining HW-deferred queue: custom-art ACK≠success,
  hot_update ACK≠success, 0x8B retransmit dead path, native C static-encoder, push smoke.

- **HARDWARE VALIDATION (2026-06-22 12:07 EDT): R53.35 iOS-LE ACK change REVERTED — read-backs
  fixed on the real Pixoo (Claude).** Commit `b1e9770`. On a live Pixoo-1, ALL read-backs
  (`device.get_brightness`, `device.get_device_name`) had regressed to a 5.26 s timeout → `null`
  while writes worked. Root cause: R53.35 made `_handle_ios_le_notification` KEEP the
  `_expected_response_command` scalar on the generic 0x33 ACK. Clearing it is **load-bearing** for
  the protocol autoprobe — `ble_probe` sends a 0x46 query (0x46 ∈ GENERIC_ACK_COMMANDS); keeping
  the scalar let the iOS-LE probe spuriously "succeed" on the Basic-only Pixoo → mis-detected as
  iOS-LE → every read-back timed out. The revert restores `self._expected_response_command = None`
  on the ACK; the 0x46 probe now correctly fails over to Basic. **Re-validated on hardware via the
  granted dev-daemon `.app`** (`dist/Divoom Dev Daemon.app`, thin launcher → live repo code, owns
  the Bluetooth TCC grant): `device.get_brightness` → `60` in **0.06 s** (was 5.26 s → null);
  `device.get_device_name` → fast 0.06 s response. Lesson: 1679 mocked unit tests can't catch an
  autoprobe regression that only manifests against real BLE framing — a Hyrum's-law case where the
  scalar-clear was load-bearing for protocol detection. The R53.35 "two-frame iOS-LE read-back" the
  change targeted remains unverified on ANY real device. NB: to drive HW from Claude, launch the
  dev-daemon `.app` (`open "dist/Divoom Dev Daemon.app"`) — it runs BLE under its own grant, unlike
  the Bash tool (TCC SIGABRT).

### Earlier rounds (pruned 2026-06-28)

The full round-by-round log that used to follow here — the R53.x adversarial-loop
rounds, the R45–R52 GUI/arch rounds, and the R7–R15 backfill (~1.4k lines of
superseded detail) — was pruned from this handoff on 2026-06-28. The authoritative
history lives in `CHANGELOG.md`, `docs/PLANNING_ROUND*.md`, and `git log`; recover
any entry from the git history of this file.

## Hardware note

macOS Bluetooth TCC is per responsible-process; drive real BLE by launching via
Terminal (`open *.command`). Device UUIDs + method in `docs/DEVICE_VALIDATION_PLAN.md`.
