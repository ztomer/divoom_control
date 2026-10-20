"""The shell half of the helper identity: `scripts/stop_helpers.sh`.

The identity files are read by two readers: `divoom_client/helper_identity.py`
(the app) and `scripts/stop_helpers.sh` (the callers that cannot run Python —
an uninstall script, an installer). Both apply the same rule, so the shell one
is tested against the same three properties:

  1. it stops the process the identity names;
  2. it leaves a process the identity does NOT name alone (the recycled-pid
     case: the pid is alive, but it started at a different moment);
  3. it clears the identity it acted on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from divoom_client import helper_identity

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stop_helpers.sh"


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        ["/bin/sleep", "120"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _wait_gone(proc: subprocess.Popen, timeout: float = 5.0) -> bool:
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _use(run_dir: Path, monkeypatch) -> None:
    """Point the identity writer AND the script at this test's directory."""
    monkeypatch.setenv(helper_identity.ENV_DIR, str(run_dir))


def _run_script(run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        env={**os.environ, "DIVOOM_IDENTITY_DIR": str(run_dir)},
    )


def test_the_script_stops_the_helper_the_identity_names(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.DAEMON, proc.pid, "/bin/sleep")
        done = _run_script(tmp_path)
        assert done.returncode == 0, done.stderr
        assert _wait_gone(proc), "the identified helper was not stopped"
        assert not helper_identity.identity_path(helper_identity.DAEMON).exists()
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_the_script_leaves_a_recycled_pid_alone(tmp_path, monkeypatch):
    """The pid is alive but it is NOT the helper the identity names."""
    _use(tmp_path, monkeypatch)
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.DAEMON, proc.pid, "/bin/sleep")
        path = helper_identity.identity_path(helper_identity.DAEMON)
        data = json.loads(path.read_text())
        data["started"] = "Mon Jan  1 00:00:00 1990"
        path.write_text(json.dumps(data))
        done = _run_script(tmp_path)
        assert done.returncode == 0, done.stderr
        time.sleep(0.2)
        os.kill(proc.pid, 0)  # still alive: the innocent process was not killed
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_the_script_is_a_no_op_without_identities(tmp_path):
    done = _run_script(tmp_path / "nothing-here")
    assert done.returncode == 0, done.stderr
    assert "nothing to stop" in done.stdout
