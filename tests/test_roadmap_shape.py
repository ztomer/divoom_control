"""docs/ROADMAP.md is a plan a gate can read, not prose that rots.

The roadmap is the ONE forward-looking document (AGENTS.md), so its failure
modes are the ones a backlog has: shipped work lingering as "OPEN" beside open
work, items with no definition of done, dependencies on things that no longer
exist, and paths to files that were deleted rounds ago. On 2026-10-05 it had
all four -- 49 of its 119 cited paths did not resolve, and an MCP item asked
for a tool that had shipped five releases earlier. These checks make each of
those a red test instead of a reader's discovery.

The shape it enforces, inside the "## Plan" section:

    ### Phase 2 — theme
    #### P2.1 — title
    **Status:** OPEN | BLOCKED (on ...) | DECISION (owner) | WATCH
    **Done when:** a condition someone can check
    **Depends on:** P1.3, P2.0          (optional)

Shipped work leaves the plan (CHANGELOG records it), so SHIPPED/DONE/CLOSED is
not a status. A dependency may only point at the same or an EARLIER phase,
which is what makes the phase order mean something.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.support.repo_files import repo_files

REPO = Path(__file__).resolve().parent.parent
ROADMAP = REPO / "docs" / "ROADMAP.md"

STATUSES = ("OPEN", "BLOCKED", "DECISION", "WATCH")
ITEM_RE = re.compile(r"^#### (P(\d+)\.(\d+)) — \S", re.M)
CODE_EXT = (".rs", ".py", ".js", ".sh", ".swift", ".css", ".html", ".toml", ".yml")


def _plan(text: str) -> str:
    m = re.search(r"^## Plan\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m is not None, "ROADMAP.md has no '## Plan' section"
    return m.group(1)


def _items(plan: str) -> dict[str, tuple[int, str]]:
    """item id -> (phase, body)."""
    heads = list(ITEM_RE.finditer(plan))
    out: dict[str, tuple[int, str]] = {}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(plan)
        body = plan[h.end():end]
        body = re.split(r"^#{1,4} (?!#)", body, maxsplit=1, flags=re.M)[0]
        assert h.group(1) not in out, f"duplicate roadmap item id {h.group(1)}"
        out[h.group(1)] = (int(h.group(2)), body)
    return out


def check_items(text: str) -> list[str]:
    plan = _plan(text)
    items = _items(plan)
    if not items:
        return ["the Plan section holds no '#### P<phase>.<n> — title' items"]
    problems = []
    for iid, (phase, body) in items.items():
        st = re.search(r"^\*\*Status:\*\*\s*(\S+)", body, re.M)
        if st is None:
            problems.append(f"{iid}: no **Status:** line")
        elif st.group(1).rstrip(".,") not in STATUSES:
            problems.append(f"{iid}: status {st.group(1)!r} is not one of {STATUSES}"
                            " (shipped work leaves the plan)")
        done = re.search(r"^\*\*Done when:\*\*\s*(.+)", body, re.M)
        if done is None or len(done.group(1).strip()) < 10:
            problems.append(f"{iid}: no **Done when:** condition")
        dep = re.search(r"^\*\*Depends on:\*\*\s*(.+)", body, re.M)
        for ref in re.findall(r"P\d+\.\d+", dep.group(1) if dep else ""):
            if ref not in items:
                problems.append(f"{iid}: depends on {ref}, which is not an item")
            elif items[ref][0] > phase:
                problems.append(f"{iid} (phase {phase}) depends on {ref} "
                                f"from a LATER phase {items[ref][0]}")
    return problems


def check_paths(text: str, tracked: set[str]) -> list[str]:
    roots = {t.split("/", 1)[0] for t in tracked}
    dirs = {str(p) for t in tracked for p in Path(t).parents}
    problems = []
    for tok in sorted({m.group(1) for m in re.finditer(r"`([^`\s]+)`", text)}):
        path = re.sub(r"(:\d+(-\d+)?)+$", "", tok).rstrip(".,")
        if "/" not in path or not re.fullmatch(r"[\w.\-/]+", path):
            continue
        first = path.split("/", 1)[0]
        if first in roots:
            if path not in tracked and path.rstrip("/") not in dirs:
                problems.append(f"`{tok}` does not exist")
        elif path.endswith(CODE_EXT):
            problems.append(f"`{tok}` is not repo-relative (write the path from the "
                            "repo root, or name an outside crate without a slash)")
    return problems


def test_plan_items_have_status_done_when_and_ordered_dependencies():
    problems = check_items(ROADMAP.read_text())
    assert not problems, "ROADMAP.md plan items:\n  " + "\n  ".join(problems)


def test_every_cited_repo_path_exists():
    tracked = {p.relative_to(REPO).as_posix() for p in repo_files(REPO)}
    problems = check_paths(ROADMAP.read_text(), tracked)
    assert not problems, "ROADMAP.md cites paths that do not resolve:\n  " + "\n  ".join(problems)


# ---------------------------------------------------------------- calibration

GOOD = """## Plan
### Phase 1 — one
#### P1.1 — first
**Status:** OPEN
**Done when:** the census prints counts by kind
### Phase 2 — two
#### P2.1 — second
**Status:** BLOCKED (on a capture)
**Done when:** the endpoint answers RC=0
**Depends on:** P1.1
## Next section
"""


def test_a_well_formed_plan_passes():
    assert check_items(GOOD) == []


@pytest.mark.parametrize("bad, expect", [
    (GOOD.replace("**Status:** OPEN", "**Status:** SHIPPED"), "not one of"),
    (GOOD.replace("**Done when:** the census prints counts by kind\n", ""), "Done when"),
    (GOOD.replace("**Depends on:** P1.1", "**Depends on:** P9.9"), "not an item"),
    (GOOD.replace("#### P1.1 — first", "#### P3.1 — first").replace("P1.1", "P3.1"), "LATER phase"),
    ("## Plan\nnothing here\n", "holds no"),
])
def test_each_rule_bites(bad, expect):
    assert any(expect in p for p in check_items(bad)), check_items(bad)


def test_path_rule_bites_on_a_deleted_file_and_a_crate_relative_one():
    tracked = {"divoomd/src/daemon.rs", "docs/ROADMAP.md"}
    text = "`divoomd/src/daemon.rs:12` `divoomd/src/gone.rs` `live_jobs/render.rs` `Weather/SearchCity`"
    problems = check_paths(text, tracked)
    assert len(problems) == 2, problems
    assert any("gone.rs" in p and "does not exist" in p for p in problems)
    assert any("render.rs" in p and "repo-relative" in p for p in problems)
