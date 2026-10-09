"""No script builds or mounts a disk image through a deprecated `hdiutil` verb.

macOS 27 deprecates `hdiutil create`, `attach`, `detach` and `convert` in favour
of `diskutil image create from` / `diskutil image attach` / `diskutil eject`.
`scripts/build_release.sh` printed the warning on every DMG for a release before
anyone read it; the warning is the only notice before the verb disappears and
the release build stops at its last step (engineering rule #17).

The scan covers what git would commit, so a new helper script is caught before
it is staged.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.support.repo_files import repo_files

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPRECATED = re.compile(r"\bhdiutil\s+(create|attach|detach|convert)\b")
SCRIPT_SUFFIXES = (".sh", ".py", ".yml", ".yaml")


def offenders(paths: list[Path], root: Path = REPO_ROOT) -> list[str]:
    """`path:line` for every non-comment line invoking a deprecated verb."""
    found = []
    for path in paths:
        if path == Path(__file__).resolve():
            continue
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if DEPRECATED.search(line):
                found.append(f"{path.relative_to(root)}:{n}")
    return found


def test_no_script_uses_a_deprecated_hdiutil_verb():
    paths = repo_files(REPO_ROOT, SCRIPT_SUFFIXES)
    assert any(p.name == "build_release.sh" for p in paths), "scan saw no build script"
    bad = offenders(paths)
    assert not bad, f"deprecated hdiutil verb (use `diskutil image ...`): {bad}"


def test_the_scan_catches_the_line_it_replaced(tmp_path: Path):
    script = tmp_path / "build.sh"
    script.write_text(
        '# hdiutil create in a comment is fine\n'
        'hdiutil create -volname "X" -srcfolder s -ov -format UDZO x.dmg\n'
        'diskutil image create from --format UDZO s x.dmg\n'
    )
    assert offenders([script], tmp_path) == ["build.sh:2"]
