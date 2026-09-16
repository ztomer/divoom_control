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

- **2026-09-14 — legacy-facade retirement DONE (v0.38.0).** The 77 modules
  the production import closure never reached (measured by AST over
  `divoom_gui`, `divoom_client`, `nowplaying`, the CLI/MCP modules; 27 of 104
  reached) now live in `examples/divoom_legacy/` as a standalone package:
  same subpackage layout, every import made absolute (`divoom_legacy.*` for
  itself, `divoom_lib.*` for the retained core it depends on), plus
  `DeviceSlot` (only `wall.py` used it). 114 test files that exercised them
  moved to `examples/tests/` with their support modules and the BLE mock
  (`examples/tests/support/mock_device.py`); `examples/tests/conftest.py`
  re-exports the main conftest. Both suites green: `tests/` 1597, and
  `examples/tests/` 1413 (`scripts/py_ci.sh` runs both; the coverage floor
  stays over `divoom_gui` + `divoom_client`). Gates re-targeted, not
  dropped: `check_positional_args` and `test_device_call_parity` read the
  legacy signatures at their new path; `check_examples` pins the scripts to
  `divoom_legacy.divoom`; `capability_census` treats both prefixes as "the
  library"; `check_gui_is_a_client` forbids `divoom_legacy` by prefix;
  `test_no_direct_facade_in_production` became "production never imports
  the retired package" over all four production trees. Decided and done:
  `pyproject` keeps `divoom_lib` (the core) and excludes `examples/`; the
  font blobs stay in `divoom_lib/fonts/` because `divoomd` embeds them.
  Also gone: the vendored house checks (`tools/check_no_allow.py`,
  `tools/check_file_size.py`, `scripts/house_emoji_gate.sh`) — the CI list
  and GitHub CI run `structural.sh --full` and `rust_gate.sh` from
  gates_of_heck by name.
  Open: the Python legacy suite is the only executable spec for the
  daemon's device_call arms; if `examples/` is ever deleted, port
  `test_device_call_parity` and the positional gate to read a recorded
  signature table first.

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
2. **`examples/` decision CLOSED 2026-09-15** — keep as the retired-library
   archive with daemon-client counterparts alongside: `examples/README.md`
   already states the retired status + the `divoom-control` CLI as the
   scriptable daemon-client path; production-import ban green
   (`test_no_direct_facade_in_production` 5 passed) and capability census
   0 DIRECT / 0 WRAPPED. No further retire — deleting it would orphan the
   only executable spec for the daemon's device_call arms.
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
