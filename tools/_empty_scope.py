"""Shared guard: a gate that inspected nothing has not passed, it has abstained.

`gates_of_heck/checks/check_empty_scope.py` runs every gate against a skeleton
tree and fails any that reports success having looked at zero files. The reason
is a ratchet argument: a renamed directory or a changed file convention retires
a gate in silence, and "0 files, all clean" is indistinguishable from "0 files,
because I can no longer find any". A ceiling met by an empty population is met
by nobody.

Six of this repo's gates had that hole on 2026-09-07. They are fixed with ONE
helper rather than six copies, so the next `tools/check_*.py` inherits the guard
instead of re-earning it -- and so the wording of the failure, which is what a
future reader has to act on, exists in one place.

`--staged` scopes are exempt by design: a commit that touches no file of the
kind a gate polices legitimately has nothing to inspect, and failing there would
make the pre-commit hook fire on unrelated work.
"""
from __future__ import annotations


def scope_is_empty(gate: str, count: int, *, staged: bool = False, unit: str = "files") -> bool:
    """True (having explained itself) when a FULL-tree run inspected nothing.

    Callers report failure their own way — `return 1`, `sys.exit(1)` — so this
    only decides and prints, and never exits on the caller's behalf.
    """
    if staged or count > 0:
        return False
    print(f"✗ [{gate}] inspected 0 {unit} — the scope is gone, not clean.")
    print(f"    Something this gate depends on moved: a directory rename, a changed")
    print(f"    file convention, or a `git ls-files` pattern that no longer matches.")
    print(f"    Fix the scope; do not let a gate report compliance over an empty set.")
    return True
