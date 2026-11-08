"""D.RELTAG: a release tag can only name a commit that is on origin's main.

`scripts/release.sh` used to WARN when HEAD was not `main` and tag HEAD anyway,
so a tag could name a commit on a side branch or a commit that exists only on
this machine. The check lives once in `scripts/lib/release_branch_gate.sh` and
`release.sh` calls it before the CI wait, the build and the tag. It is a hard
failure (fail closed), never a warning:

  * HEAD must be the branch `main`;
  * after a fetch of origin, HEAD must be an ancestor of (or equal to)
    `origin/main`, so a local-only commit is refused;
  * a fetch that fails refuses too -- an unverifiable claim is not a pass.

SEAM: DIVOOM_RELEASE_GATE_ONLY stops release.sh right after the gate, so the
ACCEPT direction does not run the CI query, the DMG build or the push. `gh` is a
stub on PATH. Nothing here tags, pushes a tag or touches a device.

TEETH: every row was watched red against the old warn-only script. Make the gate
warn instead of die and the refuse rows go red; drop the call from release.sh and
the end-to-end rows go red; narrow the ancestor test to equality and the
behind-origin accept row goes red.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REFUSED = "release refused"


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    return out.stdout.strip()


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", name)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A clone of a bare origin, on main, carrying a copy of the release scripts."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "checkout", "-q", "-b", "main")
    (work / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "release.sh", work / "scripts" / "release.sh")
    for lib in (REPO / "scripts" / "lib").glob("*.sh"):
        shutil.copy(lib, work / "scripts" / "lib" / lib.name)
    (work / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.9.9"\n')
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "main")
    return work


def _release(work: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    gh = stub / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n")
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "DIVOOM_RELEASE_GATE_ONLY": "1",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        ["bash", "scripts/release.sh"],
        check=False,
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )


def _out(r: subprocess.CompletedProcess[str]) -> str:
    return r.stdout + r.stderr


def test_accepts_head_equal_to_origin_main(fixture_repo, tmp_path):
    r = _release(fixture_repo, tmp_path)
    assert r.returncode == 0, _out(r)
    assert REFUSED not in _out(r)


def test_accepts_head_behind_origin_main(fixture_repo, tmp_path):
    _commit(fixture_repo, "ahead")
    _git(fixture_repo, "push", "-q", "origin", "main")
    _git(fixture_repo, "reset", "-q", "--hard", "HEAD~1")  # an ancestor of origin/main
    r = _release(fixture_repo, tmp_path)
    assert r.returncode == 0, _out(r)


def test_refuses_a_side_branch(fixture_repo, tmp_path):
    _git(fixture_repo, "checkout", "-q", "-b", "side")
    _commit(fixture_repo, "side-only")
    r = _release(fixture_repo, tmp_path)
    assert r.returncode != 0
    assert REFUSED in _out(r)
    assert "side" in _out(r)


def test_refuses_a_side_branch_even_when_its_commit_is_on_main(fixture_repo, tmp_path):
    _git(fixture_repo, "checkout", "-q", "-b", "side")  # same commit as origin/main
    r = _release(fixture_repo, tmp_path)
    assert r.returncode != 0
    assert REFUSED in _out(r)


def test_refuses_a_local_only_commit_on_main(fixture_repo, tmp_path):
    _commit(fixture_repo, "local-only")
    r = _release(fixture_repo, tmp_path)
    assert r.returncode != 0
    assert REFUSED in _out(r)
    assert "origin/main" in _out(r)


def test_refuses_when_origin_cannot_be_fetched(fixture_repo, tmp_path):
    _git(fixture_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    r = _release(fixture_repo, tmp_path)
    assert r.returncode != 0
    assert REFUSED in _out(r)


def test_refuses_a_detached_head(fixture_repo, tmp_path):
    _git(fixture_repo, "checkout", "-q", "--detach")
    r = _release(fixture_repo, tmp_path)
    assert r.returncode != 0
    assert REFUSED in _out(r)


def test_release_sh_no_longer_only_warns():
    text = (REPO / "scripts" / "release.sh").read_text()
    assert "not main (the tag captures HEAD regardless)" not in text
    assert "release_branch_gate.sh" in text
