"""The agent entry docs must not carry a literal that rots.

AGENTS.md and CLAUDE.md are the first thing every session reads. Twice they
pointed at an opencode session (`ses_...`) by id, and the id outlived its
session: the pointer went on reading as an instruction after the thing it named
was deleted from the opencode DB. A session id ALWAYS rots, so the docs say how
to FIND the latest session (`opencode session list`) and never which one.

The same docs once required updating `docs/SESSION_HANDOFF.md`, a second
backlog beside `docs/ROADMAP.md`. That file was folded into the roadmap on
2026-10-05 and deleted; an instruction to update it would send the next agent
to recreate it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRY_DOCS = ("AGENTS.md", "CLAUDE.md")
SESSION_ID = re.compile(r"\bses_[0-9A-Za-z]{20,}")


def _read(name: str) -> str:
    path = ROOT / name
    # A missing doc must fail loudly, not pass the scans below over nothing.
    assert path.is_file(), f"{name} is missing; the scan would cover no text"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ENTRY_DOCS)
def test_entry_doc_names_no_opencode_session_id(name):
    hits = SESSION_ID.findall(_read(name))
    assert hits == [], (
        f"{name} hard-codes opencode session id(s) {hits}; ids die with their "
        "session. Say `opencode session list` (newest first), then "
        "`opencode export <id>`."
    )


@pytest.mark.parametrize("name", ENTRY_DOCS)
def test_entry_doc_says_how_to_find_the_latest_session(name):
    assert "opencode session list" in _read(name), (
        f"{name} lost the non-rotting instruction for finding a session"
    )


@pytest.mark.parametrize("name", ENTRY_DOCS)
def test_entry_doc_does_not_point_at_the_retired_handoff(name):
    assert "SESSION_HANDOFF" not in _read(name), (
        f"{name} references docs/SESSION_HANDOFF.md, which was folded into "
        "docs/ROADMAP.md (open work) and CHANGELOG.md (narrative) and deleted."
    )
