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
3. **docs/PLANNING_ROUNDn.md** — fill the "outcome / what shipped" section of the
   current round's plan (and create the next round's plan when starting one).
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

### CI is currently unavailable — use `scripts/ci_local.sh`

**As of 2026-08-17 GitHub Actions credits are exhausted, so CI always fails.**
That is the money wall the credit-depletion exception exists for, but it also
means **CI catches nothing right now** — a red check is not a code signal, and a
green one is unobtainable.

Until billing is restored, **`./scripts/ci_local.sh` is the gate**. It mirrors
`.github/workflows/tests.yml` job-for-job (house gates, Rust core without BLE,
Rust with BLE, the Python suite). Run it before every push and before any
release.

Do NOT mistake the pre-commit hook for CI. It is deliberately narrow so commits
stay fast, and is weaker in three ways: it checks only **staged** files, gates
only **divoomd** (never `divoom-menubar`), and runs **no tests**.

This is enforced structurally in `scripts/release.sh` (preflight `ci_gate`):
it aborts on a red or still-running check run, auto-allows a failure that reads
like credit/billing depletion, and refuses when CI status can't be verified.
`--skip-ci-check` is the manual override for the credit-depletion case only —
never use it to ship on a genuinely failing CI.
