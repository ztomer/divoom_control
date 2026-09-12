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

- **2026-09-12 (later) — v0.37 work COMMITTED, NOT YET INSTALLED OR TAGGED.**
  Detail: the "Unreleased" CHANGELOG stanza; plan: ROADMAP "v0.37 plan"
  (steps 0-4 and 6 SHIPPED, 5 open).
  - **CLI is a daemon client** (e1b8ca7): attaches to the running daemon,
    never spawns one, never opens Bluetooth; bleak out of its import path.
  - **No "current" device** (2bcd5b0): `Fleet::resolve_target(mac)` --
    explicit mac, else the single linked panel, else a refusal with the count.
  - **GUI link is per panel** (b05083d); **menubar rows draw the frames**
    (5d4b33f, visual check on the real tray pending install).
  - **Now-playing reads per client** (a2a0520, fd038e8): the "platform
    limit" was a three-argument declaration of a five-argument function;
    signatures recovered from the framework's code (skill
    `private-framework-signatures`). Live: Kaset playing behind its own
    stub session, the helper reports the WebKit record with the artwork.
  - **Password in the Keychain** (1830695): `secret_store` seam, migration
    on first read, Settings says where it lives.
  - **Browser opt-in at the launch seam** (6d9cda6): 30-odd non-browser
    tests were hidden by a module-text skip; default suite 3204/0/207.
  - **Installed app is still v0.36.0.** Next: full gate, push, CI, then
    `scripts/build_release.sh && scripts/install_local.sh`, reconnect the
    fleet, check the menubar tiles and the CLI's mac-less refusal on the
    new daemon, and the Keychain migration on the real config.ini.
- **2026-09-12 — v0.36.0 RELEASED & INSTALLED LOCALLY: one struct per panel, the
  six user-reported defects, prompt-free rebuilds.** Detail: the v0.36.0
  CHANGELOG stanza; design rule: ROADMAP "per-device aggregate". Signing:
  "Divoom Local Signing" (self-signed) signs every bundle via
  `scripts/codesign_identity.sh`; rebuild + `scripts/install_local.sh`
  prompt-free on this machine.

## Open threads / next up

1. **Step 5, browser e2e under load** (ROADMAP v0.37 plan, the one open
   step): measured 2026-09-12 with the browser subset under a CPU burner;
   numbers in the ROADMAP entry. CI never ran the browser subset at all
   (the "GUI e2e" step runs pytest without `--run-browser`).
2. **`examples/` documents the bleak facade** -- library docs, or retire in
   favour of daemon-client examples. Not decided.
3. **Menubar tile visual check** on the real tray, after the next install.
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
