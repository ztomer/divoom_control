"""No compiled binary is tracked, and every build output lands on an ignored path.

`nowplaying/native/libnp_helper.dylib` was committed AND rebuilt in place by
`scripts/build_nowplaying_helper.sh`, which `build.sh` and `build_release.sh`
both run. A committed build output drifts from its source, and the commit says
nothing about it. Measured 2026-10-08: two builds of `np_helper.m` at HEAD are
byte-identical, but the committed copy differs from them in 9,931 bytes. It
has an extra ObjC class name and a different `__text`, so it was built from
some other version of the source and committed in passing (it rode along in
`ecc5d50` and `2491a3c`). Every correct build since has shown it as modified.
That had to be reverted by hand three times while cutting v0.41.1, and
`scripts/release.sh` refuses a dirty tree.

The class is "a build step writes a tracked file". A compiled artefact in git
is the usual shape of it, so the first test refuses any. It checks by magic
number as well as by suffix, because a Mach-O or ELF file needs no extension.
The second test pins the one producer this repo has: its output path must be
ignored, so the build cannot dirty the tree again.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BINARY_SUFFIXES = (".dylib", ".so", ".a", ".o", ".dll", ".exe", ".node", ".pyd")
# Mach-O (thin, both byte orders, 32/64), fat/universal, and ELF.
BINARY_MAGIC = (
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\x7fELF",
)

# Outputs written by the repo's own build scripts, which must never be tracked.
BUILD_OUTPUTS = ("nowplaying/native/libnp_helper.dylib",)


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True,
                         capture_output=True).stdout.decode()
    paths = [p for p in out.split("\0") if p]
    assert paths, "git lists no tracked files: the scan would pass over nothing"
    return paths


def compiled(paths: list[str], root: Path = REPO) -> list[str]:
    """Paths that are compiled binaries, by suffix or by leading magic bytes."""
    found = []
    for rel in paths:
        path = root / rel
        if rel.endswith(BINARY_SUFFIXES):
            found.append(rel)
            continue
        try:
            with path.open("rb") as fh:
                head = fh.read(4)
        except (FileNotFoundError, IsADirectoryError):
            continue
        if head in BINARY_MAGIC:
            found.append(rel)
    return found


def test_no_compiled_binary_is_tracked() -> None:
    bad = compiled(tracked())
    assert not bad, (
        "compiled binaries are tracked; build them, ignore the output, and "
        f"`git rm --cached` them: {bad}"
    )


def test_every_build_output_is_ignored() -> None:
    for rel in BUILD_OUTPUTS:
        assert rel not in tracked(), f"{rel} is a build output but is tracked"
        ignored = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel],
                                 cwd=REPO).returncode == 0
        assert ignored, f"{rel} is a build output but .gitignore does not ignore it"


def test_the_magic_check_sees_an_extensionless_binary(tmp_path: Path) -> None:
    (tmp_path / "helper").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 28)
    (tmp_path / "notes").write_bytes(b"plain text")
    (tmp_path / "lib.dylib").write_bytes(b"")
    assert compiled(["helper", "notes", "lib.dylib", "missing"], tmp_path) == [
        "helper", "lib.dylib",
    ]
