"""DV.SHIPKIT: `goh ship --bump patch` can release this repo.

goh refused divoom-control ("tags releases but declares no GOH_SHIP_RELEASE"). The kit it names,
`scripts/ship_release.sh`, does what `scripts/release.sh` cannot do for itself: bump the five version
places, cut CHANGELOG's Unreleased, commit, push (release.sh refuses a tag off origin/main), wait for
that commit's CI, and only then exec release.sh.

SEAMS: `gh` on PATH is the CI door (a stub here, serving canned check runs), and `scripts/release.sh` in
the fixture is a stub that records when it ran and the version it read. Nothing here touches GitHub, tags
or builds a DMG.

DV.CIADVISORY (owner, 2026-11-11: "we're not hostage to github's capacity"): the macOS `gate` job runs
the same ./tools/gate.sh the pre-push gate already passed, so it is advisory (reported, never blocking);
`linux-all-features`, which local cannot reproduce, still blocks while pending or red. Both directions
are rows below, for this kit and for release.sh's own ci_gate.

TEETH (each watched red): make `gate` blocking again and the advisory rows go red; make it ignore a red
Linux job and the blocking rows go red; drop the `git push` and the pushed-sha rows go red; call release.sh before
the CI wait and the ordering row goes red; ignore the CI helper's exit code and the red-CI and throttled
rows go red; drop a crate from bump_version.CRATES and the version-places rows go red; delete the two
.gatesrc lines and the declaration rows go red.
"""

from __future__ import annotations

import json
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
# `gh api repos/o/n/commits/SHA/check-runs`: serves STUB_CHECKS (files joined by ":", one per call, the
# last repeating) or, when STUB_GH_ERR is set, that text on stderr with exit 1 (a throttled GitHub).
GH_STUB = """#!/usr/bin/env python3
import os, sys
if sys.argv[1:2] == ["auth"]:
    sys.exit(0)
with open(os.environ["STUB_LOG"], "a") as f:
    f.write("gh " + " ".join(sys.argv[1:]) + "\\n")
if os.environ.get("STUB_GH_ERR"):
    sys.stderr.write(os.environ["STUB_GH_ERR"] + "\\n")
    sys.exit(1)
files = os.environ["STUB_CHECKS"].split(":")
counter = os.environ["STUB_CHECKS"].split(":")[0] + ".n"
n = int(open(counter).read()) if os.path.exists(counter) else 0
open(counter, "w").write(str(n + 1))
sys.stdout.write(open(files[min(n, len(files) - 1)]).read())
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
    (w / "scripts" / "lib").mkdir()
    for name in ("ship_release.sh", "bump_version.py", "lib/ci_jobs.py"):
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


def checks(tmp: Path, name: str, **jobs: str | None) -> str:
    """A check-runs answer file: each job's conclusion, or None for a job still running."""
    runs = [
        {"name": job.replace("_", "-"), "status": "completed" if c else "in_progress", "conclusion": c}
        for job, c in jobs.items()
    ]
    path = tmp / f"checks-{name}.json"
    path.write_text(json.dumps({"check_runs": runs}))
    return str(path)


def ship(
    w: Path,
    version: str,
    *,
    ci: str | None = None,
    gh_err: str = "",
    summary: str = "the thing is fixed",
    timeout_s: str = "0.5",
) -> subprocess.CompletedProcess[str]:
    """CI is the check-runs files the stub gh serves (":"-joined); default is both jobs green."""
    stub = w.parent / "bin"
    stub.mkdir(exist_ok=True)
    gh = stub / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    ci = ci or checks(w.parent, "green", gate="success", linux_all_features="success")
    env = {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "GOH_DIR": str(GOH),
        "GOH_SHIP_SUMMARY": summary,
        "STUB_LOG": str(w.parent / "stub.log"),
        "STUB_CHECKS": ci,
        "STUB_GH_ERR": gh_err,
        "DIVOOM_CI_POLL_S": "0.05",
        "DIVOOM_CI_TIMEOUT_S": timeout_s,
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
    assert log(work) == [f"gh api repos/o/n/commits/{head}/check-runs", "release.sh 1.0.1"]


def test_a_resumed_ship_does_not_bump_twice(work):
    assert ship(work, "1.0.1").returncode == 0
    before = git(work, "rev-parse", "HEAD")
    r = ship(work, "1.0.1")
    assert r.returncode == 0, out(r)
    assert git(work, "rev-parse", "HEAD") == before
    assert log(work)[-1] == "release.sh 1.0.1"


def released(work: Path) -> bool:
    return any(line.startswith("release.sh") for line in log(work))


def test_red_ci_stops_before_release(work):
    r = ship(work, "1.0.1", ci=checks(work.parent, "red", gate="success", linux_all_features="failure"))
    assert r.returncode == 1
    assert "CI is not green" in out(r)
    assert "linux-all-features" in out(r)
    assert not released(work)


def test_throttled_github_is_exit_75_not_a_green(work):
    r = ship(work, "1.0.1", gh_err="gh: API rate limit exceeded for user (HTTP 403)")
    assert r.returncode == 75
    assert "throttled" in out(r)
    assert not released(work)


# ── DV.CIADVISORY: the macOS `gate` job duplicates the local gate; only the Linux job can block ────────


@pytest.mark.parametrize("gate", [None, "failure", "cancelled"])
def test_an_advisory_gate_job_never_blocks_a_ship(work, gate):
    """The 0.45.2 and 0.45.3 ships sat on GitHub's slow macOS runner; it is reported, not waited for."""
    ci = checks(work.parent, "adv", gate=gate, linux_all_features="success")
    r = ship(work, "1.0.1", ci=ci)
    assert r.returncode == 0, out(r)
    assert released(work)
    assert "advisory" in out(r) and "gate" in out(r)


@pytest.mark.parametrize("linux", [None, "failure"])
def test_the_linux_job_blocks_a_ship_whatever_the_gate_job_says(work, linux):
    ci = checks(work.parent, "lin", gate="success", linux_all_features=linux)
    r = ship(work, "1.0.1", ci=ci)
    assert r.returncode == 1, out(r)
    assert not released(work)
    assert "linux-all-features" in out(r)


def test_a_pending_linux_job_is_waited_for_then_released(work):
    pending = checks(work.parent, "p", gate=None, linux_all_features=None)
    done = checks(work.parent, "d", gate=None, linux_all_features="success")
    r = ship(work, "1.0.1", ci=f"{pending}:{done}", timeout_s="5")
    assert r.returncode == 0, out(r)
    assert sum(line.startswith("gh ") for line in log(work)) == 2
    assert released(work)


def test_a_commit_with_no_linux_job_yet_is_not_a_green(work):
    r = ship(work, "1.0.1", ci=checks(work.parent, "g", gate="success"))
    assert r.returncode == 1
    assert not released(work)


def test_the_advisory_job_names_are_declared_once_with_the_owners_ruling():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ci_jobs", REPO / "scripts" / "lib" / "ci_jobs.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.ADVISORY) == {"gate"}
    assert "hostage to github's capacity" in mod.RULING
    for script in ("ship_release.sh", "release.sh"):
        text = (REPO / "scripts" / script).read_text()
        assert "ci_jobs.py" in text and "ADVISORY =" not in text and '"gate"' not in text and "'gate'" not in text


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
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "GOH_DIR": str(GOH),
        "STUB_LOG": str(w.parent / "stub.log"),
        "STUB_CHECKS": ci,
        "DIVOOM_RELEASE_CI_ONLY": "1",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        ["bash", "scripts/release.sh"],
        cwd=w, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, check=False,
    )  # fmt: skip


@pytest.mark.parametrize("gate", [None, "failure"])
def test_release_sh_does_not_block_on_an_advisory_gate_job(release_work, gate):
    r = release(release_work, checks(release_work.parent, "a", gate=gate, linux_all_features="success"))
    assert r.returncode == 0, out(r)
    assert "advisory" in out(r) and "gate" in out(r)


def test_release_sh_refuses_a_red_linux_job(release_work):
    r = release(release_work, checks(release_work.parent, "r", gate="success", linux_all_features="failure"))
    assert r.returncode == 1, out(r)
    assert "linux-all-features" in out(r)


def test_release_sh_refuses_a_pending_linux_job(release_work):
    r = release(release_work, checks(release_work.parent, "p", gate="success", linux_all_features=None))
    assert r.returncode == 1, out(r)
    assert "still running" in out(r)


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
