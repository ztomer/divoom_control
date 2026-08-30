# CLAUDE.md — divoom-control

This project is worked by **multiple agents** (Claude Code + opencode) that share
this git tree. The rules are tool-agnostic and live in **`AGENTS.md`** — read it.

## CORE RULE (same as AGENTS.md)

After **each round of work**, before stopping, update the cross-session handoff so
the next agent (Claude or opencode) can continue:

1. Update **`docs/SESSION_HANDOFF.md`** — "Current state" + "Open threads".
2. Add/extend the round's **`CHANGELOG.md`** entry, and record shipped/open
   work in **`docs/ROADMAP.md`** (the one forward-looking doc — per-round
   planning files are pruned to git history once the round ships).
3. **Commit** each logical change with a clear message; keep tests green
   (`python3 -m pytest`) and note pass/skip counts.

The git history + `SESSION_HANDOFF.md` + CHANGELOG are the cross-session memory —
do not rely on conversation context surviving.

To read the opencode session: `opencode export ses_184471307ffeCUHgzv9w51O0oA`.

See `AGENTS.md` for the full project conventions (protocol truth, GUI layout,
hardware/Bluetooth, tests, build discipline).
