"""DV.SHIPKIT: `goh ship --bump patch` can release this repo.

goh refused divoom-control ("tags releases but declares no GOH_SHIP_RELEASE"). The kit it names,
`scripts/ship_release.sh`, does what `scripts/release.sh` cannot do for itself: bump the five version
places, cut CHANGELOG's Unreleased, commit, push (release.sh refuses a tag off origin/main), wait for
that commit's CI, and only then exec release.sh.

SEAMS: `GOH_LOOPCTL` is the CI door (a stub here), and `scripts/release.sh` in the fixture is a stub
that records when it ran and the version it read. Nothing here touches GitHub, tags or builds a DMG.

TEETH (each watched red): drop the `git push` and the pushed-sha rows go red; call release.sh before
the CI wait and the ordering row goes red; ignore loopctl's exit code and the red-CI and throttled
rows go red; drop a crate from bump_version.CRATES and the version-places rows go red; delete the two
.gatesrc lines and the declaration rows go red.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GOH = Path(os.environ.get("GOH_DIR") or Path.home() / "Projects" / "gates_of_heck")

CHANGELOG = """# Changelog

## Unreleased

- **A thing is fixed (X.1).** It was broken; now it is not.

## v1.0.0 — the first release (2026-01-01)

- **First.** It shipped.
"""
LOCK = """[[package]]
name = "divoom-menubar"
version = "1.0.0"

[[package]]
name = "divoomd"
version = "1.0.0"

[[package]]
name = "nowplaying"
version = "1.0.0"
"""
RELEASE_STUB = """#!/usr/bin/env bash
REPO="o/n"
V="$(sed -n 's/^version = "\\(.*\\)"/\\1/p' pyproject.toml)"
echo "release.sh $V" >> "$STUB_LOG"
"""
LOOPCTL_STUB = """import os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write("loopctl " + " ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("STUB_CI_RC", "0")))
"""


def git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    return done.stdout.strip()


@pytest.fixture
def work(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    w = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(w))
    git(w, "checkout", "-q", "-b", "main")
    (w / "scripts").mkdir()
    for name in ("ship_release.sh", "bump_version.py"):
        shutil.copy(REPO / "scripts" / name, w / "scripts" / name)
    (w / "scripts" / "release.sh").write_text(RELEASE_STUB)
    (w / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    for crate in ("divoomd", "divoom-menubar"):
        (w / crate).mkdir()
        (w / crate / "Cargo.toml").write_text(f'[package]\nname = "{crate}"\nversion = "1.0.0"\n')
    (w / "Cargo.lock").write_text(LOCK)
    (w / "CHANGELOG.md").write_text(CHANGELOG)
    git(w, "add", ".")
    git(w, "commit", "-q", "-m", "base")
    git(w, "push", "-q", "origin", "main")
    return w


def ship(
    w: Path, version: str, *, ci_rc: int = 0, summary: str = "the thing is fixed"
) -> subprocess.CompletedProcess[str]:
    loopctl = w.parent / "loopctl.py"
    loopctl.write_text(LOOPCTL_STUB)
    env = {
        **os.environ,
        "GOH_DIR": str(GOH),
        "GOH_LOOPCTL": str(loopctl),
        "GOH_SHIP_SUMMARY": summary,
        "STUB_LOG": str(w.parent / "stub.log"),
        "STUB_CI_RC": str(ci_rc),
        "NO_COLOR": "1",
    }
    return subprocess.run(
        ["bash", "scripts/ship_release.sh", version],
        cwd=w, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, check=False,
    )  # fmt: skip


def log(w: Path) -> list[str]:
    p = w.parent / "stub.log"
    return p.read_text().splitlines() if p.exists() else []


def out(r: subprocess.CompletedProcess[str]) -> str:
    return r.stdout + r.stderr


def test_bumps_every_version_place_cuts_the_changelog_and_commits(work):
    r = ship(work, "1.0.1")
    assert r.returncode == 0, out(r)
    assert 'version = "1.0.1"' in (work / "pyproject.toml").read_text()
    for crate in ("divoomd", "divoom-menubar"):
        assert 'version = "1.0.1"' in (work / crate / "Cargo.toml").read_text()
    lock = (work / "Cargo.lock").read_text()
    assert lock.count('version = "1.0.1"') == 2
    assert 'name = "nowplaying"\nversion = "1.0.0"' in lock  # the standalone library keeps its own
    text = (work / "CHANGELOG.md").read_text()
    assert "## v1.0.1" in text and "the thing is fixed" in text
    assert text.index("## Unreleased") < text.index("## v1.0.1") < text.index("## v1.0.0")
    assert git(work, "log", "-1", "--format=%s") == "chore(release): version 1.0.1 - the thing is fixed"


def test_pushes_the_release_commit_then_waits_for_its_ci_then_releases(work):
    r = ship(work, "1.0.1")
    assert r.returncode == 0, out(r)
    head = git(work, "rev-parse", "HEAD")
    assert git(work, "rev-parse", "origin/main") == head == git(work.parent / "origin.git", "rev-parse", "main")
    assert log(work) == [f"loopctl ci {head} --repo o/n --wait", "release.sh 1.0.1"]


def test_a_resumed_ship_does_not_bump_twice(work):
    assert ship(work, "1.0.1").returncode == 0
    before = git(work, "rev-parse", "HEAD")
    r = ship(work, "1.0.1")
    assert r.returncode == 0, out(r)
    assert git(work, "rev-parse", "HEAD") == before
    assert log(work)[-1] == "release.sh 1.0.1"


def test_red_ci_stops_before_release(work):
    r = ship(work, "1.0.1", ci_rc=1)
    assert r.returncode == 1
    assert "CI is not green" in out(r)
    assert not any(line.startswith("release.sh") for line in log(work))


def test_throttled_github_is_exit_75_not_a_green(work):
    r = ship(work, "1.0.1", ci_rc=75)
    assert r.returncode == 75
    assert "throttled" in out(r)
    assert not any(line.startswith("release.sh") for line in log(work))


def test_refuses_a_dirty_tree_before_changing_anything(work):
    (work / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n# edit\n')
    r = ship(work, "1.0.1")
    assert r.returncode != 0
    assert "uncommitted" in out(r)
    assert log(work) == []


def test_refuses_a_side_branch(work):
    git(work, "checkout", "-q", "-b", "side")
    r = ship(work, "1.0.1")
    assert r.returncode != 0
    assert "not the branch main" in out(r)


def test_refuses_a_version_that_is_not_above_the_current_one(work):
    r = ship(work, "0.9.0")
    assert r.returncode != 0
    assert "not above" in out(r)
    assert 'version = "1.0.0"' in (work / "pyproject.toml").read_text()


def test_refuses_a_lockfile_missing_a_product_crate(work):
    (work / "Cargo.lock").write_text(LOCK.replace('name = "divoomd"', 'name = "other"'))
    git(work, "commit", "-q", "-am", "lock")
    r = ship(work, "1.0.1")
    assert r.returncode != 0
    assert "no version line found in Cargo.lock (divoomd)" in out(r)


def test_refuses_an_empty_unreleased(work):
    (work / "CHANGELOG.md").write_text(
        CHANGELOG.replace("- **A thing is fixed (X.1).** It was broken; now it is not.\n", "")
    )
    git(work, "commit", "-q", "-am", "empty")
    r = ship(work, "1.0.1")
    assert r.returncode != 0
    assert log(work) == []


def test_gatesrc_declares_the_kit_the_way_goh_reads_it():
    script = '. ./.gatesrc >/dev/null 2>&1; printf "%s|%s" "$GOH_SHIP_RELEASE" "$GOH_SHIP_RELEASE_PUSHES"'
    done = subprocess.run(
        ["bash", "-c", script], cwd=REPO, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL
    )
    assert done.stdout == "scripts/ship_release.sh {version}|1"
    assert (REPO / "scripts" / "ship_release.sh").stat().st_mode & 0o111


def test_the_real_release_sh_still_names_the_repo_the_kit_reads():
    text = (REPO / "scripts" / "release.sh").read_text()
    assert subprocess.run(
        ["sed", "-n", 's/^REPO="\\([^"]*\\)".*/\\1/p'], input=text, capture_output=True, text=True, check=True
    ).stdout.split() == ["ztomer/divoom_control"]
