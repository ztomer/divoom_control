# Agent rules — divoom-control

Shared rules for any coding agent working in this repo (opencode, Claude, etc.).

## CORE RULE: keep the session handoff updated after every round

This project is worked across multiple agents/sessions (opencode + Claude) that
**share this git working tree**. They CANNOT share a live session (separate
conversation stores), so the handoff is file-based. **On entry, read
`docs/SESSION_HANDOFF.md`.** After **each round of work**, before you stop, you
MUST update the handoff so the *next* session — including the opencode session
`ses_184471307ffeCUHgzv9w51O0oA` — can pick up without re-deriving state:

1. **docs/SESSION_HANDOFF.md** — update "Current state" + "Open threads / next
   up". This is the canonical living state both tools read first.
2. **CHANGELOG.md** — add/extend the round's entry (what shipped, where, why).
3. **docs/ROADMAP.md** — record what shipped and what is still open. This is the
   ONE forward-looking document; per-round `PLANNING_ROUNDn.md` files are pruned
   to git history once their round ships (house rule: a per-feature plan
   graveyard rots and misleads later sessions). Write a round plan while a round
   is in flight if it helps, then prune it on the way out.
4. **Commit** the work with a clear, scoped message (one logical change per
   commit) so `git log` is a faithful, readable history of the round.
5. **Tests green** before you call a round done (`python3 -m pytest`), and state
   the pass/skip counts in the handoff + CHANGELOG.

The git history + `docs/SESSION_HANDOFF.md` + CHANGELOG ARE the cross-session
memory. Treat them as the source of truth; do not rely on conversation context
surviving. (Claude Code reads `CLAUDE.md` which points here; opencode reads this
`AGENTS.md` directly.)

**Also read `docs/CHANNEL_ARCHITECTURE.md` on entry** — hard-won invariants (image
pipeline, 0x8B protocol, dual-impl anti-drift, "ACK ≠ success", when to use C).
These are lessons paid for in real shipped bugs; don't relearn them.

> To resume the opencode session for context: `opencode export <sessionID>`
> dumps it as JSON (`info` + `messages`).

## Project conventions

- **Device protocol truth**: the decompiled APK (`references/apk/decompiled_src/`)
  + `references/divoom-refs/` (futpib, hass-divoom, …). Don't invent command
  IDs/enums — cite the source. NOTE: `references/apk/APK_INTELLIGENCE_REPORT.md`
  is a convenience summary and has been **wrong** on details — verify against the
  decompiled source. See `docs/CHANNEL_ARCHITECTURE.md`.
- **GUI**: PyWebView. Python bridge in `divoom_gui/api/tools.py` (+ mixins); web
  UI in `divoom_gui/web_ui/` (modular css/js; large views live in templates per
  domain, e.g. `alarms_editor.js`, `templates_tools.js`).
- **Hardware**: macOS Bluetooth TCC is per responsible-process; drive real BLE
  by launching via Terminal (`open *.command`). See `docs/DEVICE_VALIDATION_PLAN.md`.
- **Tests**: hardware tests are gated/skip by default (`tests/conftest.py`);
  prefer the mock-device E2E (`tests/test_e2e_mock_device.py`) for wire checks.
- **Build discipline**: delete dead code; document the decision, not just the
  code; foundation before cutover; test before you trust.

## Release rule — CI must be green to cut a release

Cutting a release (`scripts/release.sh`) is only allowed when **GitHub CI is
green for the commit being tagged** (`check-runs` on HEAD all pass). The ONE
exception is **credit depletion** (GitHub Actions billing exhaustion) — that is a
money wall, not a code signal, so it does not block.

### CI is back up (2026-08-23) — `scripts/ci_local.sh` is still the pre-push gate

**Superseded state:** from 2026-08-17 GitHub Actions credits were exhausted and
CI always failed. That is no longer true — `a7a699f` re-enabled `tests.yml` and
it runs green on `main`. **A red check is a code signal again.**

**This repo is PUBLIC, and GitHub Actions on standard runners is FREE for public
repositories.** No credits are consumed by `divoom_control`, so "we are out of
credits" is not a reason to skip CI here — whatever the state of the account's
private-repo minutes. Verified 2026-08-23: runs 32663891706 and 32666052786 both
executed and went green while the account was believed to be out of credits.
Check `gh run list` before concluding CI is unavailable; the belief has now
outlived the fact twice, and the last time it did, v0.23.0 shipped on a red CI.

**`./scripts/ci_local.sh` remains the pre-push gate** regardless: it mirrors
`.github/workflows/tests.yml` job-for-job (house gates, Rust core without BLE,
Rust with BLE, the Python suite) and catches things before you spend a CI run.
Run it before every push and before any release.

**It runs on this machine only.** CI's `rust-core` and `rust-ble-linux` jobs run
on Ubuntu, so a **Linux-only failure is invisible locally** — v0.23.0 shipped
with a red `rust-core` for exactly that reason. A green `ci_local.sh` means "the
macOS-reachable jobs pass", never "CI would be green".

**And never assume a red CI is billing — read the failure.** The whole point of
the gate is that "red" and "out of credits" look identical from the outside. The
v0.23.0 run had 4 of 5 jobs GREEN and one real failure; treating it as billing
skipped a diagnosis that took two minutes.

**A step that cannot fail is not a gate.** `python -m camoufox fetch` exits 0
when it installs nothing (a GitHub API rate limit produced three 403s, "Synced 0
versions from 0 repos.", and a green step). Any CI step that INSTALLS or
GENERATES something must verify the artifact, not the exit code — and a retry
must loop on the verification, because looping on an exit code never retries a
failure that exits 0. See `tools/check_camoufox_installed.py`.

**Check which transport/environment a defect actually needs before writing its
test.** This round's body-drain regression test was first written against the
TCP fixture and passed with the fix REMOVED; the bug only reproduces on AF_UNIX.
A test on the wrong transport is a green light bolted over the bug.

Do NOT mistake the pre-commit hook for CI. It is deliberately narrow so commits
stay fast, and is weaker in three ways: it checks only **staged** files, gates
only **divoomd** (never `divoom-menubar`), and runs **no tests**.

This is enforced structurally in `scripts/release.sh` (preflight `ci_gate`):
it aborts on a red or still-running check run, auto-allows a failure that reads
like credit/billing depletion, and refuses when CI status can't be verified.
`--skip-ci-check` is the manual override for the credit-depletion case only —
never use it to ship on a genuinely failing CI.
