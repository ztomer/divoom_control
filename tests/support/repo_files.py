"""The files a repo-wide test should look at: what git would commit.

Walking the tree with `Path.rglob` also walks everything git ignores -- nested
`.claude/worktrees/` checkouts, scratch output, build trees, venvs -- so a scan
that should see one copy of a file sees two, or reads a dependency's sources as
the repo's. `test_applescript_launch_gate` failed exactly that way on
2026-10-05 when an agent's worktree sat inside the checkout, and the emoji scan
was silently reading the whole second copy too. Ask git instead: tracked files
plus untracked files that are not ignored, so a brand-new file is still caught
before it is staged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def repo_files(root: Path, suffixes: tuple[str, ...] | None = None) -> list[Path]:
    """Tracked + untracked-not-ignored files under `root`, sorted.

    Fails loudly outside a git checkout rather than returning an empty list: a
    scan over nothing would pass every assertion it makes.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, check=True,
    ).stdout.decode()
    paths = [root / rel for rel in out.split("\0") if rel]
    if not paths:
        raise RuntimeError(f"git lists no files under {root}")
    return sorted(
        p for p in paths
        if p.is_file() and (suffixes is None or p.suffix in suffixes)
    )
