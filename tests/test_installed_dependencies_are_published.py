"""The browser suites run on the PUBLISHED dependencies, not on a hand-edited copy.

P1.22 (D.CIB85): CI was red on main for a release while this machine stayed
green, because this machine's fpgen had been edited in place in site-packages
(a one-line `'!' -> 0` fix for Python 3.15). CI installs the published wheel.
A local gate that runs on a privately repaired dependency passes over exactly
what a fresh install breaks on, and nothing said so.

So every file pip recorded for the [e2e] closure (camoufox and everything it
requires) must still hash to its RECORD entry. A file the repo deliberately
supersedes at runtime is listed in SUPERSEDED with the module that replaces it;
an entry whose superseding module is gone fails, so the list cannot outlive
its reason.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata as md
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: (distribution, RECORD path) -> (the repo module that replaces it at runtime,
#: the sha256 of the ONE known edit it excuses). Empty: the one entry it held
#: excused the dev machine's in-place edit of fpgen/unpacker.py
#: (`if s == '!': return 0`), and that edit is gone -- the published fpgen 1.3.0
#: was reinstalled and every consumer decodes through a shim (D.REV3,
#: 2026-11-07). An entry is added only with its reason, and deleted when the
#: edit it excuses stops existing.
SUPERSEDED: dict[tuple[str, str], tuple[str, str]] = {}

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _closure(root: str) -> set[str]:
    seen: set[str] = set()
    todo = [root]
    while todo:
        name = todo.pop().lower().replace("_", "-")
        if name in seen:
            continue
        try:
            requires = md.requires(name) or []
        except md.PackageNotFoundError:
            continue
        seen.add(name)
        for req in requires:
            if "extra ==" in req:
                continue
            m = _NAME.match(req)
            if m:
                todo.append(m.group(1))
    return seen


def modified_files(dists: set[str]) -> list[tuple[str, str, str]]:
    """Every (distribution, file, actual sha256) whose bytes no longer match its RECORD hash."""
    bad = []
    for name in sorted(dists):
        dist = md.distribution(name)
        for f in dist.files or []:
            if not f.hash or f.hash.mode != "sha256":
                continue
            path = Path(f.locate())
            if not path.is_file():
                bad.append((name, str(f), "missing"))
                continue
            digest = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode()
            if digest != f.hash.value:
                bad.append((name, str(f), digest))
    return bad


def test_every_superseding_module_exists() -> None:
    for key, (module, _) in SUPERSEDED.items():
        assert (REPO / module).is_file(), f"{key} is excused by {module}, which is gone: delete the entry"


def test_the_e2e_dependencies_are_the_published_ones() -> None:
    pytest.importorskip("camoufox")
    dists = _closure("camoufox")
    assert {"camoufox", "fpgen", "playwright"} <= dists, dists
    bad = [(d, f) for d, f, digest in modified_files(dists) if SUPERSEDED.get((d, f), (None, None))[1] != digest]
    assert not bad, (
        "installed dependencies differ from what pip installed -- this machine runs code CI does not: "
        f"{bad}. Reinstall them (pip install --force-reinstall --no-deps <dist>)."
    )


def test_the_check_sees_an_edited_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calibration: the hash comparison goes red on a byte changed after install."""
    pytest.importorskip("camoufox")
    dist = md.distribution("camoufox")
    target = next(f for f in dist.files or [] if f.hash and str(f).endswith(".py"))
    real_locate = type(target).locate
    copy = tmp_path / "edited.py"
    copy.write_bytes(Path(target.locate()).read_bytes() + b"\n# edited\n")
    monkeypatch.setattr(type(target), "locate", lambda self: copy if str(self) == str(target) else real_locate(self))
    assert ("camoufox", str(target)) in [(d, f) for d, f, _ in modified_files({"camoufox"})]
