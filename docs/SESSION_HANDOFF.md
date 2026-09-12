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

- **2026-09-12 — v0.36.0 RELEASED & INSTALLED LOCALLY: one struct per panel, the
  six user-reported defects, prompt-free rebuilds.** Detail: the v0.36.0
  CHANGELOG stanza; design rule: ROADMAP "per-device aggregate".
  - **Daemon**: `Device` (identity: live job, activity) holds an `Option<Link>`
    (connection: transport + the ONE queue); `Fleet` is the single owner. Queued
    work is bound to its link and dropped if the link is retired; a job's
    `alive` flag is a fence. Every pushed live frame is broadcast with its
    pixels. `owned_devices` is fleet-wide. Per-device `disconnect {mac}` and
    `device_status {mac}`. Gate: `divoomd/tests/live_jobs_stress.rs` (10).
  - **GUI**: the proxy names its panel on every call; bench selection is one
    funnel (`select_device`); status events are per-panel and jewels are
    honest; previews mirror the panel via the broadcast frames; animated GIFs
    play through `gif_frames.js`; the cover card shows the ORIGINAL art.
  - **Menubar**: `DeviceView` per panel with link state; tray word derived.
  - **All six user defects live-confirmed on the installed build with the user
    at the keyboard** (#1 corrected to the user's reading: cover = original
    art, smooth; device frame = diodes).
  - **Signing**: "Divoom Local Signing" (self-signed, trusted for codeSign in
    the login keychain) signs every bundle via `scripts/codesign_identity.sh`;
    a second, different build installed with NO Bluetooth prompt. Rebuild +
    `scripts/install_local.sh` freely on this machine.
  - **Cross-platform**: the encoder lookup is platform-named (`.so` on Linux)
    and Linux CI builds it; the examples check installs its own `bleak`.
  - **Verification**: `ci_local.sh` full green (28/28) at tag time; GitHub CI
    green at the tagged commit per `scripts/release.sh`.

## Open threads / next up

1. **Retire the daemon's "current" device.** Only mac-less callers use it now:
   the CLI (`divoom_lib/cli.py`) and MCP tools (`divoomd/src/mcp_tools.rs`).
   Once they pass `mac`, `Fleet::current` and `preset` go, and
   `connect_single_device`'s disconnect-free path is the only path.
2. **GUI `appConnected` is still one boolean.** It now follows the SELECTED
   panel's link (per-panel state lives on `discoveredDevices[].activityState`);
   the remaining single-device residue is `requireDevice()` and the global dot.
   Track 3 in the ROADMAP.
3. **Menubar tiles.** `DeviceView.preview` now carries real frames from the
   broadcast; the tray still lists names. Track 6.
4. **Now-playing masking residual.** MediaRemote answers for one session; a
   playing app behind a stopped holder stays invisible. The idle reply names
   the players and the card shows the hint; nothing more is readable.
5. **The browser e2e suite fails randomly at NORMAL machine load** (two runs,
   non-overlapping camoufox failures, all pass alone). Do not raise the
   timeout; measure browser + daemon startup under controlled load. ROADMAP
   OPEN heading. Note `python3 -m camoufox fetch` is needed once per Python
   install or the suite SKIPS rather than fails.
6. **`config.ini` stores the Divoom account password in PLAINTEXT.**
   `cloud_store` in the daemon is the one place that would change.
7. **Release hygiene**: a new machine needs `scripts/make_signing_identity.sh`
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
