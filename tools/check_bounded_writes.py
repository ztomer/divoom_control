#!/usr/bin/env python3
"""check_bounded_writes.py — every client-socket write goes through the seam.

A peer that stops READING is the case nothing else in the daemon catches. It is
not idle (we have data for it) and it has not closed (no EOF); its socket buffer
absorbs writes until it fills, after which `write_all` blocks forever. Whatever
the stalled task was holding -- a connection permit, a subscription slot -- is
then held for the life of the process.

That was fixed twice, badly, before it was fixed structurally. The first fix
bounded the two writes inside the subscriber `select!` and left the ten others
unbounded, including the EVICTION NOTICE -- written to the one client we have
already concluded is not draining its socket, so of the ten it was the likeliest
to block, inside the very path that exists to reclaim a stalled client.

So the deadline now lives in one `write_line` seam, and this gate is what keeps
it there: a counter or a test can only observe the paths that go THROUGH the
seam, and a new `write_all` added beside it is exactly what neither can see.

SCOPE, stated rather than implied: this gate reads `socket_server.rs`, the
client transport, AND every submodule under `socket_server/` (the subscriber
pump, the accept loops). The seam lives in `socket_server.rs`, so in a
submodule ANY `write_all` is a violation. Until P2.6 split the accept loops
out, the gate read the one file and the pump beside it was invisible to it --
a split for the line cap silently shrank the gate's subject. It makes no claim about `mcp.rs` (stdio) or `socket_bind.rs`
(a probe with its own timeout) -- different resources, different failure modes.
Widening it would need a seam in those files first.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _empty_scope import scope_is_empty  # noqa: E402
from _srcscan import strip_rust_comments  # noqa: E402
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TARGET = Path("divoomd/src/socket_server.rs")
SUBMODULES = Path("divoomd/src/socket_server")
SEAM = "async fn write_line"
WRITE = re.compile(r"\.write_all\s*\(")


def seam_span(src: str) -> tuple[int, int] | None:
    """Byte range of the seam function's body, by brace matching."""
    at = src.find(SEAM)
    if at < 0:
        return None
    open_brace = src.find("{", at)
    if open_brace < 0:
        return None
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return (open_brace, i)
    return None


def audit(text: str) -> tuple[list[int], int]:
    """(offending line numbers, total write_all sites) over comment-stripped source."""
    src = strip_rust_comments(text)
    span = seam_span(src)
    if span is None:
        # The seam itself is gone. That is not "no violations"; it is the
        # violation, and the loudest form of it.
        return ([0], 0)
    lo, hi = span
    bad, total = [], 0
    for m in WRITE.finditer(src):
        total += 1
        if not lo <= m.start() <= hi:
            bad.append(src.count("\n", 0, m.start()) + 1)
    return (bad, total)


def audit_submodule(text: str) -> list[int]:
    """Line numbers of every write_all in a submodule (no seam lives there)."""
    src = strip_rust_comments(text)
    return [src.count("\n", 0, m.start()) + 1 for m in WRITE.finditer(src)]


def submodules() -> list[Path]:
    return sorted((REPO / SUBMODULES).glob("*.rs"))


def self_test() -> int:
    """Prove the gate can fail, in both directions, before it is believed."""
    clean = (REPO / TARGET).read_text()
    bad_lines, total = audit(clean)
    checks = [
        ("the tree as committed passes", not bad_lines and total >= 1),
        (
            "a write_all outside the seam fails",
            bool(audit(clean + "\nfn extra() { s.write_all(b\"x\"); }\n")[0]),
        ),
        (
            "a write_all in a COMMENT passes",
            not audit(clean + "\n// s.write_all(b\"x\");\n")[0],
        ),
        (
            "a write_all in a submodule fails",
            bool(audit_submodule("fn x() { s.write_all(b\"x\"); }\n")),
        ),
        ("the submodules are read at all", len(submodules()) >= 2),
        (
            # NOT `write_line_renamed`: that still CONTAINS the seam string, so
            # the first version of this probe changed nothing and reported the
            # gate as broken. A probe that does not produce the symptom is a
            # false finding, and it accuses working code.
            "a deleted seam fails",
            bool(audit(clean.replace(SEAM, "async fn emit_bytes"))[0]),
        ),
    ]
    for name, passed in checks:
        (ok if passed else err)(f"[bounded-writes:self-test] {name}")
    return 0 if all(p for _, p in checks) else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    path = REPO / TARGET
    if not path.exists():
        err(f"[bounded-writes] {TARGET} is gone — fix this gate's scope, do not delete it")
        return 1
    bad_lines, total = audit(path.read_text())
    found = [(TARGET, ln) for ln in bad_lines]
    for sub in submodules():
        found += [(sub.relative_to(REPO), ln) for ln in audit_submodule(sub.read_text())]
    if found:
        err(f"[bounded-writes] {len(found)} unbounded write(s) in the socket server")
        for where, ln in found:
            info(
                f"{where}:{ln}: write_all outside `write_line` — a peer that stops "
                f"reading blocks this write forever and pins whatever the task holds. "
                f"Route it through `write_line`, which applies WRITE_TIMEOUT."
            )
        return 1
    if scope_is_empty("bounded-writes", total, unit="write sites"):
        return 1
    ok(
        f"[bounded-writes] OK — {total} write site(s), all inside the WRITE_TIMEOUT seam; "
        f"{len(submodules())} submodule(s) hold none"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
