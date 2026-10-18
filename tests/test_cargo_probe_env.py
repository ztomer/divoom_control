"""A probe crate's cargo build must stay inside the directory its tool owns.

`tools/render_tray_icon.py` compiles a scratch crate in a
fresh temp dir. The house `~/.cargo/config.toml` sends every build's
intermediates to `{cargo-cache-home}/build/{workspace-path-hash}`, and a fresh
temp dir is a fresh hash, so each run left a build dir under `~/.cargo/build`
that nothing collected: 112 of them, every one fingerprint
`probe-b31fe2907f4634b8`. The fix is `tools/_cargo_env.py`; these tests hold it
in place, independent of how the machine running them configures cargo.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from _cargo_env import probe_env  # noqa: E402

needs_cargo = pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is needed")


def test_both_build_directories_land_inside_the_root(tmp_path):
    env = probe_env(tmp_path, base={"PATH": "/bin"})
    assert env["CARGO_BUILD_BUILD_DIR"] == str(tmp_path / "build")
    assert env["CARGO_TARGET_DIR"] == str(tmp_path / "target")
    assert env["PATH"] == "/bin", "the rest of the environment is passed through"


def test_a_callers_own_build_directories_are_kept(tmp_path):
    mine = {"CARGO_BUILD_BUILD_DIR": "/gate/build", "CARGO_TARGET_DIR": "/gate/target"}
    assert probe_env(tmp_path, base=mine) == mine
    # An empty value names no directory; cargo would fall back to its config.
    empty = probe_env(tmp_path, base={"CARGO_BUILD_BUILD_DIR": ""})
    assert empty["CARGO_BUILD_BUILD_DIR"] == str(tmp_path / "build")


def _leaky_config(parent: Path, leak: Path) -> None:
    """The house config's shape, scoped to `parent`: builds of crates below it
    go to `leak/<workspace-path-hash>`, outside the crate's own directory."""
    (parent / ".cargo").mkdir(parents=True)
    (parent / ".cargo" / "config.toml").write_text(
        f'[build]\nbuild-dir = "{leak.as_posix()}/{{workspace-path-hash}}"\n'
    )


@needs_cargo
def test_the_tray_icon_probe_leaves_no_build_behind(monkeypatch, tmp_path):
    parent, leak = tmp_path / "tmp", tmp_path / "leak"
    _leaky_config(parent, leak)
    # A caller with no build dir of its own -- the case that leaked.
    monkeypatch.delenv("CARGO_BUILD_BUILD_DIR", raising=False)
    monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)

    # Calibration: without the fix, cargo really would build into `leak`.
    # If a cargo release stops honouring the config, this fails instead of
    # the assertion below passing over nothing.
    control = parent / "control"
    (control / "src").mkdir(parents=True)
    (control / "src" / "main.rs").write_text("fn main() {}\n")
    (control / "Cargo.toml").write_text(
        '[package]\nname = "control"\nversion = "0.0.0"\nedition = "2024"\n'
    )
    meta = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--no-deps"],
        capture_output=True, text=True, cwd=control, timeout=120, check=True,
        stdin=subprocess.DEVNULL,
    )
    assert json.loads(meta.stdout)["build_directory"].startswith(str(leak)), meta.stdout

    monkeypatch.setattr(tempfile, "tempdir", str(parent))
    render = pytest.importorskip("render_tray_icon")
    assert render.rust_glyphs(), "the probe did not build and draw"

    leaked = sorted(p.relative_to(leak) for p in leak.glob("**/.fingerprint/probe-*"))
    assert not leaked, f"the probe's build outlived its temp dir: {leaked}"
    assert not [p for p in parent.iterdir() if p.name not in {".cargo", "control"}], (
        "the probe's temp dir was not removed"
    )


# ── the class: every probe build a tool spawns goes through probe_env ──────
_CARGO_BUILD = re.compile(r"""\[\s*["']cargo["']\s*,\s*["'](?:build|run|test|check|clippy)["']""")


def _unguarded_builds(src: str) -> list[int]:
    """Lines spawning a cargo build whose call (to its closing paren) has no
    `probe_env(`. Paren-matched from the `subprocess` call, not line-windowed."""
    hits = []
    for m in _CARGO_BUILD.finditer(src):
        start = src.rfind("subprocess.", 0, m.start())
        depth, end = 0, len(src)
        for i in range(src.index("(", start), len(src)):
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            if depth == 0:
                end = i
                break
        if "probe_env(" not in src[start:end]:
            hits.append(src.count("\n", 0, m.start()) + 1)
    return hits


def test_the_class_scanner_sees_an_unguarded_build():
    bad = 'r = subprocess.run(\n    ["cargo", "run", "--quiet"], cwd=d,\n)\n'
    good = 'r = subprocess.run(\n    ["cargo", "build"], cwd=d,\n    env=probe_env(d),\n)\n'
    assert _unguarded_builds(bad) == [2]
    assert _unguarded_builds(good) == []


def test_every_python_cargo_build_in_tools_and_scripts_uses_probe_env():
    files = sorted((REPO / "tools").glob("*.py")) + sorted((REPO / "scripts").rglob("*.py"))
    scanned = [f for f in files if _CARGO_BUILD.search(f.read_text(encoding="utf-8"))]
    # Not vacuous: the two probe builds this test was written for are in scope.
    assert {f.name for f in scanned} >= {"render_tray_icon.py", "mem_gauge_compare.py"}
    bad = {
        str(f.relative_to(REPO)): lines
        for f in scanned
        if (lines := _unguarded_builds(f.read_text(encoding="utf-8")))
    }
    assert not bad, f"cargo builds without probe_env (tools/_cargo_env.py): {bad}"
