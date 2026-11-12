"""DV.SHIPKIT: `goh ship --bump patch` can release this repo.

goh refused divoom-control ("tags releases but declares no GOH_SHIP_RELEASE"). The kit it names,
`scripts/ship_release.sh`, does what `scripts/release.sh` cannot do for itself: bump the five version
places, cut CHANGELOG's Unreleased, commit, push (release.sh refuses a tag off origin/main), wait for
that commit's CI, and only then exec release.sh.

SEAMS: DIVOOM_LOOPCTL names the CI door (a stub here, answering loopctl's exit codes), and
`scripts/release.sh` in the fixture is a stub that records when it ran and the version it read. Nothing
here touches GitHub, tags or builds a DMG.

DV.CIDOOR: both scripts read CI only through `loopctl.py ci SHA --repo divoom-control` (`--wait` in the
kit, one read in release.sh's ci_gate). loopctl judges the jobs, with .gatesrc's LOOP_CI_ADVISORY
naming the macOS `gate` job as reported-never-blocking (DV.CIADVISORY); its own tests pin that
judgement, these pin the call and every exit code: 0 green, 1 red or unread, 3 pending, 4 no CI,
75 throttled. Only 0 releases.

TEETH (each watched red): treat exit 3 or 4 as green and the not-green rows go red; drop `--wait` and
the call-shape row goes red; drop the `git push` and the pushed-sha rows go red; call release.sh before
the CI wait and the ordering row goes red; ignore the door's exit code and the not-green and throttled
rows go red; drop a crate from bump_version.CRATES and the version-places rows go red; delete the
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
# DV.CIDOOR: loopctl's CI door, stubbed. It records its argv and answers with the exit codes in STUB_CI_RC
# (":"-joined, one per call, the last repeating): 0 green, 1 red or unread, 3 pending, 4 no CI, 75 throttled.
LOOPCTL_STUB = """#!/usr/bin/env python3
import os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write("loopctl " + " ".join(sys.argv[1:]) + "\\n")
codes = os.environ["STUB_CI_RC"].split(":")
counter = os.environ["STUB_LOG"] + ".n"
n = int(open(counter).read()) if os.path.exists(counter) else 0
open(counter, "w").write(str(n + 1))
print("stub verdict " + codes[min(n, len(codes) - 1)])
sys.exit(int(codes[min(n, len(codes) - 1)]))
"""


def loopctl_stub(tmp: Path) -> str:
    path = tmp / "loopctl.py"
    path.write_text(LOOPCTL_STUB)
    return str(path)


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
    (w / "scripts" / "lib").mkdir()
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
    w: Path,
    version: str,
    *,
    ci: str = "0",
    summary: str = "the thing is fixed",
) -> subprocess.CompletedProcess[str]:
    """CI is the exit codes the stub loopctl answers with (":"-joined); default green."""
    env = {
        **os.environ,
        "GOH_DIR": str(GOH),
        "GOH_SHIP_SUMMARY": summary,
        "STUB_LOG": str(w.parent / "stub.log"),
        "STUB_CI_RC": ci,
        "DIVOOM_LOOPCTL": loopctl_stub(w.parent),
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
    assert log(work) == [f"loopctl ci {head} --repo divoom-control --wait", "release.sh 1.0.1"]


def test_a_resumed_ship_does_not_bump_twice(work):
    assert ship(work, "1.0.1").returncode == 0
    before = git(work, "rev-parse", "HEAD")
    r = ship(work, "1.0.1")
    assert r.returncode == 0, out(r)
    assert git(work, "rev-parse", "HEAD") == before
    assert log(work)[-1] == "release.sh 1.0.1"


def released(work: Path) -> bool:
    return any(line.startswith("release.sh") for line in log(work))


@pytest.mark.parametrize(("rc", "says"), [("1", "red"), ("3", "pending"), ("4", "no CI")])
def test_a_ci_that_is_not_green_stops_before_release(work, rc, says):
    """loopctl's door: 1 red or unread, 3 still pending when --wait's bound ran out, 4 no CI at all
    (this repo HAS CI, so a commit without any is no verdict). None of them is a green."""
    r = ship(work, "1.0.1", ci=rc)
    assert r.returncode == 1, out(r)
    assert "CI is not green" in out(r) and says in out(r)
    assert "stub verdict " + rc in out(r)  # loopctl's own verdict line reaches the log
    assert not released(work)


def test_throttled_github_is_exit_75_not_a_green(work):
    r = ship(work, "1.0.1", ci="75")
    assert r.returncode == 75
    assert "throttled" in out(r)
    assert not released(work)


def test_the_ci_door_is_loopctl_and_the_advisory_job_is_declared_in_gatesrc():
    """DV.CIDOOR: the jobs are judged by loopctl, which reads .gatesrc's LOOP_CI_ADVISORY; the
    scripts name no job and no GitHub API path, and the old reader is gone."""
    assert not (REPO / "scripts" / "lib" / "ci_jobs.py").exists()
    script = '. ./.gatesrc >/dev/null 2>&1; printf "%s" "$LOOP_CI_ADVISORY"'
    done = subprocess.run(
        ["bash", "-c", script], cwd=REPO, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL
    )
    assert done.stdout == "gate: runs the same ./tools/gate.sh the local pre-push gate already passed"
    for name in ("ship_release.sh", "release.sh"):
        text = (REPO / "scripts" / name).read_text()
        assert "loopctl.py" in text and " ci " in text and "--repo divoom-control" in text
        assert "check-runs" not in text and "ci_jobs" not in text and '"gate"' not in text


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


# ── release.sh's own ci_gate (the by-hand release) reads the same jobs the same way ────────────────────


@pytest.fixture
def release_work(tmp_path: Path) -> Path:
    """A clone carrying the REAL release.sh and its libs, HEAD on origin/main, version 9.9.9."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    w = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(w))
    git(w, "checkout", "-q", "-b", "main")
    (w / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "release.sh", w / "scripts" / "release.sh")
    for lib in (REPO / "scripts" / "lib").iterdir():
        shutil.copy(lib, w / "scripts" / "lib" / lib.name)
    (w / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.9.9"\n')
    (w / ".gatesrc").write_text("GOH_TAG_VERSION_SOURCES='pyproject:pyproject.toml'\n")
    git(w, "add", ".")
    git(w, "commit", "-q", "-m", "base")
    git(w, "push", "-q", "origin", "main")
    return w


def release(w: Path, ci: str) -> subprocess.CompletedProcess[str]:
    """Run release.sh up to and including ci_gate (DIVOOM_RELEASE_CI_ONLY stops there)."""
    stub = w.parent / "bin"
    stub.mkdir(exist_ok=True)
    gh = stub / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n")  # preflight's `gh auth status` only
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "GOH_DIR": str(GOH),
        "STUB_LOG": str(w.parent / "stub.log"),
        "STUB_CI_RC": ci,
        "DIVOOM_LOOPCTL": loopctl_stub(w.parent),
        "DIVOOM_RELEASE_CI_ONLY": "1",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        ["bash", "scripts/release.sh"],
        cwd=w, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, check=False,
    )  # fmt: skip


def test_release_sh_asks_the_door_once_and_proceeds_on_green(release_work):
    r = release(release_work, "0")
    assert r.returncode == 0, out(r)
    head = git(release_work, "rev-parse", "HEAD")
    assert log(release_work) == [f"loopctl ci {head} --repo divoom-control"]


@pytest.mark.parametrize(("rc", "code"), [("1", 1), ("3", 1), ("4", 1), ("75", 75)])
def test_release_sh_refuses_a_ci_that_is_not_green(release_work, rc, code):
    r = release(release_work, rc)
    assert r.returncode == code, out(r)
    assert "stub verdict " + rc in out(r)


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
