"""The Python gate gives one verdict whether or not a stray .venv exists (DC.VENV).

This repo declares no project environment (no uv.lock, no committed .venv). A
stray `uv run` here once made a ruff-less .venv, and goh's runner rule (a .venv
before the pinned interpreter) then drove ruff through it and refused the gate.
.gatesrc names GOH_PY_RUNNER, so the gate's tools resolve from the pinned
interpreter (the same one CI provisions from .python-version) and an untracked
.venv cannot change the verdict.
"""

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOH_DIR = Path(os.environ.get("GOH_DIR", Path.home() / "Projects" / "gates_of_heck"))
PY_STAGED = GOH_DIR / "gates" / "py_staged.sh"

pytestmark = pytest.mark.skipif(
    not PY_STAGED.is_file() or shutil.which("git") is None,
    reason=f"needs gates_of_heck at {GOH_DIR} and git",
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(ROOT / ".python-version", repo / ".python-version")
    # The repo's ceilings file is not in the fixture; the floor rule set is enough here.
    rc = (ROOT / ".gatesrc").read_text().splitlines()
    kept = [line for line in rc if not line.startswith("GOH_PY_LINT_CEILINGS=")]
    (repo / ".gatesrc").write_text("\n".join(kept) + "\n")
    (repo / "ok.py").write_text('print("ok")\n')
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, env=env, stdin=subprocess.DEVNULL)
    return repo


def _gate(repo: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GOH_PY")}
    env.pop("VIRTUAL_ENV", None)
    env["GOH_DIR"] = str(GOH_DIR)
    return subprocess.run(
        [str(PY_STAGED), "--all", "."],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def test_ruffless_venv_does_not_change_the_verdict(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    without = _gate(repo)
    assert without.returncode == 0, without.stdout + without.stderr

    venv.create(repo / ".venv", with_pip=False)  # the stray, ruff-less venv
    assert not (repo / ".venv" / "bin" / "ruff").exists()
    with_venv = _gate(repo)
    assert with_venv.returncode == without.returncode, with_venv.stdout + with_venv.stderr
    assert ".venv/bin/python" not in with_venv.stdout + with_venv.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
