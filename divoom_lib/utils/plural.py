"""A count meets its noun: `counted(3, "file")` is `3 files`, never a hedged "file" plus parenthesised s.

The house helper is `tui.lib.counted` / `tui.lib.noun` in gates_of_heck, and `goh plural-hedge`
(GOH.PLURALHEDGE) refuses the hedge in a string literal. The shipped code (the library, the client,
the GUI) cannot import goh at runtime, so this is its dependency-free twin with the same contract;
the gates and scripts take goh's own through `tools/_tui.py`. Pinned by tests/test_plural.py.
"""

from __future__ import annotations


def noun(n: int, singular: str, plural: str | None = None) -> str:
    """The noun for a count of `n`: exactly one is singular; `plural` defaults to singular + s."""
    return singular if n == 1 else (plural or f"{singular}s")


def counted(n: int, singular: str, plural: str | None = None) -> str:
    """`1 file`, `0 files`, `3 files`."""
    return f"{n} {noun(n, singular, plural)}"
