# CLAUDE.md — divoom-control

This project is worked by **multiple agents** (Claude Code + opencode) that share
this git tree. The rules are tool-agnostic and live in **`AGENTS.md`** — read it.

## CORE RULE (same as AGENTS.md)

On entry, read **`docs/ROADMAP.md`** (what is open) and `git log --oneline`.
After **each round of work**, before stopping, leave the tree so the next agent
(Claude or opencode) can continue:

1. Record shipped/open work in **`docs/ROADMAP.md`** — the ONE forward-looking
   doc. There is no separate handoff file; per-round plans are pruned to git
   history once the round ships.
2. Add/extend the round's **`CHANGELOG.md`** entry (per-round narrative lives
   here).
3. **Commit** each logical change with a clear message; keep tests green
   (`python3 -m pytest`) and note pass/skip counts.

The git history + `docs/ROADMAP.md` + CHANGELOG are the cross-session memory —
do not rely on conversation context surviving.

To read an opencode session: `opencode session list` (newest first), then
`opencode export <id>`. Never hard-code a session id here — it rots when the
session is deleted (`tests/test_agent_docs_no_session_ids.py` enforces this).

See `AGENTS.md` for the full project conventions (protocol truth, GUI layout,
hardware/Bluetooth, tests, build discipline).
