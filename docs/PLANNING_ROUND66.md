# Planning Round 66 — repo restructure: retire `native-port/`, one Rust workspace, drop dead code

**Status**: shipped (2026-08-17)
**Started**: 2026-08-17
**Predecessor**: R65 (house Rust gate + v0.22.21 release)

## Why this round

The repo's layout still describes the *migration* that produced it, not the
system it produced. `native-port/` reads as an experiment but holds a shipped
binary; `divoom_daemon/` holds no daemon; `archive/` holds 12k LOC nobody runs
but three CI gates still scan. Three independent Cargo crates mean three
`target/` dirs and a CI that never builds one of them.

None of this is a bug. All of it is friction that every future session pays.

## Ground truth (measured 2026-08-17, at c3c4f8d)

The shipped `Divoom.app` is: Python pywebview GUI + Rust `divoomd` daemon +
Rust `divoom-menubar` tray.

| Component | Lang | LOC | Files | Status |
|---|---|---|---|---|
| `divoomd/` | Rust | 17,203 | 95 | **Core** — owns BLE, protocol, dispatch |
| `native-port/divoom-menubar/` | Rust | 1,266 | 17 | **Shipped** — tray agent |
| `divoom_lib/` | Python | 19,912 | 113 | Live — library, CLI, MCP |
| `divoom_gui/` | Python | 16,335 | 137 | Live — thin daemon client |
| `divoom_daemon/` | Python | 1,750 | 7 | Live, but is the socket **client** |
| `divoom_menubar/` | Python | 648 | 3 | **Dead** — superseded, still ships |
| `archive/` | Python | 11,969 | 63 | **Dead** — archived Python daemon server |
| `native-port/spike-ble/` | Rust | ~250 | 7 | **Dead** — Phase-1 port spike |

Note for future sessions: `native-port/` is **not** where the core lives. It is
1,266 LOC of tray agent plus dead weight. Its 1.6 GB on disk is `target/`.

## The five problems

1. **`native-port/` is a migration-era name holding production code.** One
   shipped binary, one dead spike, three codegen scripts.
2. **No Cargo workspace.** Three independent crates → three `target/` dirs
   (2.9 GB + 1.3 GB + 248 MB) and three `Cargo.lock` files.
3. **CI never builds `divoom-menubar`.** `rust-core`/`rust-ble` are both
   `working-directory: divoomd`. No fmt, clippy, build, or test reaches the tray
   agent — a gate-parity hole of exactly the kind R65 closed for `divoomd`.
4. **`divoom_daemon/` is misnamed.** Its own module docstring opens
   `"""CLIENT LIBRARY — the Rust divoomd binary is the sole shipping daemon.`
   README spends a paragraph explaining the name. It is the most-imported
   shared Python module.
5. **`ARCHITECTURE.md` contradicts `README.md`.** Its headline section, "Three
   packages (R17)", still says `divoom_daemon/` is "the SINGLE owner of the
   device connection" — false since the Rust cutover (2026-07-13). `AGENTS.md`
   directs every agent to read it on entry.

Secondary: `archive/` is not excluded from `tools/check_file_size.py`,
`check_no_emoji.py`, or `check_no_allow.py`, so dead code is gated on every CI
run. `.divoom_last_working_char.json` (runtime state) is tracked in git.
`docs/SESSION_HANDOFF.md` and `docs/README.md` both link to
`docs/archive/rounds/`, which does not exist.

## Plan

### Phase 0 — reclaim disk (no commit)
Remove the two fully-merged worktrees under `.claude/worktrees/` (both are
strict ancestors of `main`, 0 unique commits, clean trees) and their merged
branches; `cargo clean` the three target dirs. ~9 GB.

### Phase 1 — delete dead code (three commits)
1. `native-port/spike-ble/` — superseded by `divoomd`; recoverable from git.
2. `divoom_menubar/` — plus its three live references: `setup_app.py` packages
   list, `pyproject.toml` `packages.find`, `divoom_lib/cli_commands.py:380`.
   Stops shipping dead code inside the DMG.
3. `archive/` — plus untrack `.divoom_last_working_char.json`. Verify first
   that no collected test imports it (`testpaths = ["tests"]`, so
   `archive/tests/` is already uncollected).

### Phase 2 — one Cargo workspace
Root `Cargo.toml`: `members = ["divoomd", "divoom-menubar"]`, `resolver = "2"`.

Two traps:
- **`exclude` is mandatory.** `references/` holds three gitignored Cargo
  projects. Without excluding them every cargo invocation in the repo fails
  with "current package believes it's in a workspace when it's not".
- **CI's per-package flags must stay per-package.** `rust-core` runs
  `cargo build --no-default-features` to gate the no-BLE core; under a
  workspace that would apply to every member. Pin to `-p divoomd`.

### Phase 3 — retire the `native-port/` name
`git mv native-port/divoom-menubar divoom-menubar` and
`git mv native-port/gen_*.py scripts/codegen/`. Touch points (all enumerated):
`.gitignore:61`, `build.sh:50,54`, `run.sh:32`, `divoom.spec:41`,
`setup_app.py:66`, `divoom_gui/gui_main.py:414`,
`tests/test_gui_main_bootstrap.py:262`, `scripts/build_release.sh:57`,
`tools/check_file_size.py:26` (comment), plus doc-comment paths in
`divoomd/src/commands.rs`, `divoomd/src/framing.rs`,
`divoomd/tests/framing_parity.rs`, `divoomd/tests/native_encode_parity.rs`.

The workspace simplifies most of these: binary paths collapse from
`native-port/divoom-menubar/target/release/…` to `target/release/…`.

**Rejected alternative:** grouping both crates under `rust/`. Cleaner root, but
adds 28 more reference edits across 21 files for `divoomd/` and buys nothing
Phase 2 does not already deliver.

### Phase 4 — rename `divoom_daemon/` → `divoom_client/`
Mechanical but widest blast radius: ~30 test files, GUI, CLI, `pyproject.toml`
packaging, `[tool.coverage.run] source`. Own commit, one `git grep` sweep to
verify. Deferrable without blocking 1-3.

### Phase 5 — close the gate gap, fix the docs
- `rust-core` fmt/clippy → `--workspace` so the tray agent is finally gated.
- Rewrite `ARCHITECTURE.md`'s "Three packages" section to the real topology
  (README is already correct — make ARCHITECTURE match rather than contradict).
- Fix the dead `docs/archive/rounds/` links in `docs/README.md` +
  `docs/SESSION_HANDOFF.md`.

### Phase 6 — drop macOS Intel (x86_64) support

Apple no longer ships or supports Intel Macs; neither do we. The shipped app,
the DMG, and the C accelerator become **Apple silicon only**.

**Scope boundary — this is macOS Intel, NOT x86_64 wholesale.** `divoom_lib` and
`divoomd` still support **Linux x86_64** (README, the `rust-core` /
`rust-ble-linux` CI jobs, BlueZ). So:

- `divoom_lib/native_src/compact.c` — the non-NEON `memcpy` fallback **stays**;
  it serves Linux x86_64. Do not delete it.
- `scripts/build_libdivoom.sh` — the `x86_64 -> -msse2` branch **stays for
  Linux** but must **fail loudly on Darwin/x86_64** rather than silently
  producing an unsupported Intel dylib.
- `setup_app.py` / `divoom.spec` — assert arm64; never emit `universal2`.
- `README.md` — "Requires macOS 11 (Big Sur) or later" is now wrong on its own;
  state **Apple silicon required**.
- Homebrew cask (`ztomer/homebrew-tap`, separate repo) — declare `arm64` only,
  so Intel users get a clean "unsupported" rather than a broken install.

Acceptance: a Darwin/x86_64 build attempt fails with a clear message; the
produced `Divoom.app` reports arm64-only (`lipo -archs`); Linux x86_64 CI jobs
stay green.

## Verification per phase

`python3 -m pytest -q` (record pass/skip), `cargo test --workspace`,
`cargo clippy --workspace --all-targets -- -D warnings`,
`python3 tools/check_file_size.py && python3 tools/check_no_emoji.py &&
python3 tools/check_no_allow.py`, and a `./build.sh && ./run.sh` smoke before
the round is called done.

## Outcome / what shipped

All six phases shipped, plus the camoufox migration. 12 commits, net
**-14,240 LOC** (188 files, 2,935 insertions / 17,175 deletions).

| Phase | Commit | Result |
|---|---|---|
| 0 | — | 9.2 GB reclaimed (worktrees + orphaned target dirs) |
| 1 | `7cbc713`, `43a3f92`, `11f6e9a` | spike-ble, divoom_menubar/, archive/ removed (~12.6k LOC) |
| 2 | `bc1c0f5` | Cargo workspace; divoom-menubar gated for the first time |
| 3 | `b5c7319` | native-port/ retired; binary-path class fixed |
| 4 | `bc2316e` | divoom_daemon/ -> divoom_client/ (159 refs) |
| 5 | `b99c18d` | CI workspace parity; ARCHITECTURE/docs made true |
| 6 | `3dd42ea` | 64-bit only, macOS Apple-silicon only |
| camoufox | `08d3878`, `a548be2` | 15 e2e suites migrated; guard fixed; 2 races fixed |

### What the round actually found

The layout work was the stated goal; the value was in the gates that reported
success while checking something narrower than they claimed. Every one of these
was invisible to a green suite:

1. **`divoom-menubar` had never been formatted** — CI (`working-directory:
   divoomd`) and the pre-commit hook (`"$root/divoomd"`) both scoped to one
   crate. `cargo fmt --all` from the new workspace root produced 129 insertions
   across all four of its source files.
2. **4-parent path arithmetic** in `native_encode.rs` and `spp.rs`. The
   workspace moved the binary one level shallower. `find_encoder_lib()` returns
   `Option`, so it degrades silently to no native encoder; `spp.rs` would point
   at a nonexistent bridge. Fixed as a class (`divoomd/src/paths.rs`).
3. **The e2e skip guard did not guard** — `importorskip` checks the module, not
   the browser binary. That is what made this round's first baseline show 69
   failures that looked like real regressions.
4. **The arch `*)` fallback warned and built anyway**, so a 32-bit host produced
   an untested binary.
5. **Two e2e tests waited on a proxy signal** and asserted on a different one;
   passing was a Chromium timing coincidence.
6. **`ARCHITECTURE.md` claimed the Python package owned the device** ~5 weeks
   after that stopped being true, while `AGENTS.md` sends every agent to read it.

### Deviations from the plan

- **Phase 6 (drop macOS Intel) was added mid-round** at the user's request, and
  applied house-wide: `ZoneTilerWM` was the only other project still building
  universal, on branch `drop-intel-macos`. Recorded as standing rule #3 in
  `~/.claude/CLAUDE.md` + the `target-platform-policy` skill.
- **`scripts/ci_local.sh` was added** (not in the original plan) because GitHub
  Actions credits ran out mid-round, making CI a dead signal.
- **The `rust/` grouping alternative stayed rejected** — Phase 2 delivered the
  gate parity that was the real motivation.

### Open / carried forward

- **The CI workflow changes are VERIFIED — CLOSED 2026-08-23.** Run
  32663891706 was green on all five jobs. The premise of the original note was
  also wrong: this repo is PUBLIC, and GitHub Actions on standard runners is
  free for public repositories, so no credits were ever being consumed here.
  (Original note: "Actions credits are exhausted; the YAML parses and every
  command was proven locally via `ci_local.sh`, but the workflow itself has not
  run. Re-check when billing is restored.")
- **Not released.** The round is layout + gates, no user-facing behaviour change;
  `pyproject.toml` stays at 0.22.21. `release.sh`'s `ci_gate` cannot verify green
  CI while billing is out (the documented credit-depletion exception).
