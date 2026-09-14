# Session Handoff — read this first

**Consolidated roadmap**: `docs/ROADMAP.md` — shipped rounds, open workstreams.
This file tracks the per-round current state and open threads.

This is the **cross-agent session state**. opencode and Claude Code keep their
own conversation stores. THIS FILE + git history + CHANGELOG + ROADMAP are the
shared memory. Read this on entry and **update it at the end of every round**
(see the core rule in `AGENTS.md`).

## How to resume

- **opencode**: `opencode -s ses_f6a64811fffeYyM9ixX43QtgDz` (or `opencode export <id>`).
- **Claude Code**: reads `CLAUDE.md` → `AGENTS.md` → this file, plus `git log`.
- Both: `git log --oneline`, `CHANGELOG.md`, `docs/ROADMAP.md`.
- This file is the CURRENT state, not an archive. Once a round ships and its
  CHANGELOG stanza is written, its entry here is pruned to git history (house
  rule: one forward-looking doc). To recover older context:
  `git log -p -- docs/SESSION_HANDOFF.md` for past entries,
  `git log --diff-filter=D -- 'docs/**/PLANNING_*'` for round plans.

## Current state — _update this section each round_

- **2026-09-14 — legacy-facade retirement, step 1 COMMITTED (eca2224);
  step 2 MEASURED, not executed.** Step 1: the no-direct-facade gate
  (`tests/test_no_direct_facade_in_production.py`, seed zero) + the
  `mcp_server.py` docstring. Step 2 was scoped this session with an AST
  closure over the real production entry points (`divoom_gui`,
  `divoom_client`, `nowplaying`, the CLI/MCP modules), ignoring
  `TYPE_CHECKING` blocks and `divoom_lib/__init__.py`'s lazy `__getattr__`
  (`Divoom`, `LanTransport` — nothing in production resolves them):
  **27 of 104 `divoom_lib` modules are reached; 77 are the legacy direct
  path.** Reached and staying: `bt_spp_transport`/`bt_spp_rfcomm` (the
  daemon's SPP bridge, `divoom_client/spp_bridge.py`), `framing`,
  `transport`/`transport_interface`, `native_lib`, `divoom_auth`,
  `weather_provider`, `hotchannel_config`, `hot_update_state`,
  `lifecycle_config`, `models/*`, `utils/{atomic_io,converters,media_players}`,
  `exceptions`, the CLI/MCP modules. The 77 unreached (the facade
  `divoom.py`, `connection`, the BLE/LAN transports, `display/*`,
  `system/*`, `tools/*`, `scheduling/*`, `media/*`, `cloud.py`,
  `fonts/`, `media_decoder`, the Python `native/` encoders, `wall.py`,
  `monthly_best_daemon.py`, `game`, `probing`, `tool.py`, ...):
    - `display`: __init__.py, animation.py, animation_8b.py, animation_user.py, cloud_channel.py, custom_channel.py, design.py, display_animation.py, display_text.py, drawing.py, light.py, lightning_channel.py, scoreboard_channel.py, text.py, time_channel.py, vjeffect_channel.py
    - `fonts`: __init__.py, bitmap_font.py
    - `media`: __init__.py, music.py, radio.py
    - `native`: __init__.py, downscaler.py, image_encoder.py
    - `scheduling`: __init__.py, alarm.py, sleep.py, timeplan.py
    - `system`: __init__.py, bluetooth.py, control.py, date_time.py, device.py, device_settings.py, sound.py, temp_weather.py, time.py, weather.py
    - `tools`: __init__.py, aid_sleep.py, countdown.py, custom_art_push.py, hot_update.py, noise.py, notification.py, scoreboard.py, timer.py
    - `top-level`: ble_connection.py, ble_notify.py, ble_preflight.py, ble_probe.py, ble_reads.py, ble_registry.py, ble_transport.py, cloud.py, connection.py, divoom.py, game.py, lan_transport.py, lan_transport_extras.py, lan_transport_photo.py, media_decoder.py, monthly_best_daemon.py, probing.py, protocol.py, sender_protocol.py, spp_connection.py, tool.py, wall.py
    - `utils`: cache.py, devices_db.py, discovery.py, divoom_image_encode.py, divoom_image_encode_32.py, image_processing.py, logger_utils.py, media_source.py
  Why it was NOT executed in this pass — two things are decisions, not
  mechanics: (1) `pyproject.toml` ships `divoom_lib` as the public
  `divoom-control` library with `examples/` (7 scripts) as its usage docs and
  `tools/check_examples.py` + `tools/capability_census.py` gating them in
  `GOH_CI_STEPS`; retiring the 77 modules retires that public library
  surface and both gates. (2) The Python tests for the two already-ported
  orphans are large (`test_wall.py` 459 lines, `test_wall_geometry_cache.py`
  169, `test_monthly_best_daemon.py` 500, plus wall cases in
  `test_r42_backup_restore.py` and `test_ble_phase3.py`) while the Rust
  ports carry two tests between them (`monthly_best.rs`; `wall.rs` none
  inline, `tests/wall_configure.rs` 2 KB) — deleting the Python drops
  behaviour coverage the daemon now owns. Execution order when it is
  decided: re-express the wall/monthly-best cases as `divoomd` tests
  first (fail-first), then delete the two orphans, then the facade +
  transports + `examples/` + the two gates in one subtractive commit, then
  `pyproject` packaging down to the client packages. `native_src/` + the
  dylib stay regardless (`divoomd` FFIs them).

- **2026-09-13 — v0.37.0 RELEASED & INSTALLED LOCALLY** (tag v0.37.0 at
  cd553cd, GitHub release with the DMG, cask bumped; daemon inode
  546319145 running from /Applications/Divoom.app, signed by the local
  identity). Detail: the v0.37.0 CHANGELOG stanza; the ROADMAP "Shipped"
  entry. Verified on the installed build after install: daemon and
  menubar report 0.37.0; the active panel, `owned_devices` command,
  store faces (19) and their picture decode, Keychain-backed credentials
  (no password line in config.ini), and the CLI `select` all answer.
  Local gate 27/28 with one socket-test flake (5/5 green alone, ledger in
  ROADMAP); GitHub CI 5/5 green at the tagged commit.
- **2026-09-12 — v0.36.0 RELEASED & INSTALLED LOCALLY: one struct per panel, the
  six user-reported defects, prompt-free rebuilds.** Detail: the v0.36.0
  CHANGELOG stanza; design rule: ROADMAP "per-device aggregate". Signing:
  "Divoom Local Signing" (self-signed) signs every bundle via
  `scripts/codesign_identity.sh`; rebuild + `scripts/install_local.sh`
  prompt-free on this machine.

## Open threads / next up

1. **Browser suites run in CI** (own step, `--run-browser`): 3 runs green,
   1 with a single timeout in the gallery-overflow test that did not
   recur; that test now reports its layout on timeout. Watch for a repeat.
2. **`examples/` documents the bleak facade** -- library docs, or retire in
   favour of daemon-client examples. Not decided.
3. **Menubar tile visual check**: the rows and the switch were read through
   System Events (NotchNook covers that part of the menu bar for a click
   tool); the tile ICON itself is proven up to the `Icon` handed to
   `NSMenu`, not by eye.
4. **Release hygiene**: a new machine needs `scripts/make_signing_identity.sh`
   once (one keychain prompt, user present) or every install prompts.

**Environment notes that recur** (not repo defects):

* **`sccache` can wedge a build**: 51 minutes at 0:00 CPU, `sccache
  --show-stats` showing accepted requests and nothing executed. Same build in
  4s with `RUSTC_WRAPPER=""`. Check CPU time before assuming a build is slow.
* **The shared `CARGO_TARGET_DIR` sits at the disk gate's ceiling** (~45-50GB
  of 50GB). Disk hygiene then aborts `structural.sh` before layer 3 with a
  message about the gate. `debug/incremental` and `llvm-cov-target` are the
  safe things to clear.
* **Bluetooth-grant terminal calibrator**: `cargo test` under the Claude
  desktop app's Bash has no Bluetooth grant, so any test that reaches a real
  CoreBluetooth central dies with SIGABRT and no message. That is a finding
  about the code (rule 10), not the terminal — fix the eager radio use.

## Hardware packet

    python3 scripts/hw_verify.py --self-test        # calibrate FIRST
    python3 scripts/hw_verify.py --out report.json

Start the GUI first: it owns the Bluetooth grant, and the packet refuses to
spawn its own daemon. `--self-test` exits **3 = PARTIAL** until a device is
connected. `tools/check_hw_verify_methods.py` gates the packet's method names
against the daemon's match arms. Play something before `album_art`.
`search_weather_city` is a canary (expected to fail on the real account).

## Earlier history

`CHANGELOG.md` is the durable record of what shipped, and `docs/ROADMAP.md` of
what is open. Round-by-round handoff prose is recoverable from
`git log -p -- docs/SESSION_HANDOFF.md` and, for R3–R64, from the archive file
deleted on 2026-08-30: `git log --diff-filter=D -- 'docs/archive/*'`.
`docs/CAPABILITY_MAP.md` holds the census verdicts from R70-R72.

## Hardware note

macOS Bluetooth TCC is granted per RESPONSIBLE PROCESS and keyed on the code's
designated requirement. A daemon started from a shell has no grant, so the
first BLE scan kills it with **SIGABRT and an empty stderr**. Users are
unaffected (the GUI launches the daemon and owns the grant); it bites terminal
work and tests.

**To drive a locally built daemon on hardware:** build and install the bundle
and let the app be the responsible process — `scripts/build_release.sh` then
`scripts/install_local.sh` (quits the app, installs, `open`s, proves the
running daemon's inode is the installed one). With the local signing identity
present (`scripts/make_signing_identity.sh`, once) there is no Bluetooth
prompt. For a traced daemon: `scripts/make_dev_daemon_app.sh` (BLE debug on,
log at `/tmp/divoom_dev_daemon.log`, lines tagged `[ble <id>]`); quit the GUI
first or it respawns its own daemon over the socket.

Then drive `/tmp/divoom.sock`. `connect {mac}` works directly; `scan` often
reports "already in progress" while the GUI scans. A device does not always come
back on its own after a daemon restart: `scan` times out while `connect` with
the saved identifier succeeds.

**Reading a trace:** a device ECHOES `basic frame cmd=0xNN` for opcodes its
firmware implements. A silence proves nothing on its own — send a known-good
command (0x45) first in the SAME window and compare.

Watch out: `cargo test` rebuilds `target/debug/divoomd` WITH default features,
so a BLE-free build does not stay BLE-free across a test run.
