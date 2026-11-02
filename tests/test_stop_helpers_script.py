"""The shell half of the helper identity: `scripts/stop_helpers.sh`.

The identity files are read by two readers: `divoom_client/helper_identity.py`
(the app) and `scripts/stop_helpers.sh` (the callers that cannot run Python —
an uninstall script, an installer). Both apply the same rule, so the shell one
is tested against the same three properties:

  1. it stops the process the identity names;
  2. it leaves a process the identity does NOT name alone (the recycled-pid
     case: the pid is alive, but it started at a different moment);
  3. it clears the identity it acted on;
  4. it stops the process HOLDING the app's endpoints (the daemon's socket, the
     GUI's lock), for the helper a build too old to write an identity left
     running, and no other process (queue D.KBNA: this replaced the by-name
     `pkill`s in install.sh and scripts/install_local.sh).
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
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


def _run_script(run_dir: Path, **endpoints: str) -> subprocess.CompletedProcess:
    """Run the script against THIS test's endpoints. The defaults name the
    owner's real socket and lock, which a running app holds: every call passes
    paths of its own (nothing there by default), or a test would stop the app."""
    nowhere = str(run_dir.parent / "no-such-endpoint")
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        env={**os.environ, "DIVOOM_IDENTITY_DIR": str(run_dir),
             "DIVOOM_GUI_LOCK": endpoints.get("lock", nowhere),
             "DIVOOM_DAEMON_SOCKETS": endpoints.get("sockets", nowhere)},
        check=False,
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


HOLDER = textwrap.dedent("""
    import fcntl, os, signal, socket, sys, time
    kind, path = sys.argv[1], sys.argv[2]
    if kind == "socket":
        s = socket.socket(socket.AF_UNIX); s.bind(path); s.listen(1)
    else:
        fh = open(path, "w"); fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("up", flush=True)
    time.sleep(120)
""")


@contextlib.contextmanager
def _holder(kind: str, path: Path):
    """A process holding ``path`` (a bound socket, or a flock'd file)."""
    with subprocess.Popen([sys.executable, "-c", HOLDER, kind, str(path)],
                          stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True) as proc:
        try:
            assert proc.stdout.readline().strip() == "up"
            yield proc
        finally:
            proc.kill()


def _short_dir() -> Path:
    """A unix socket path must fit in ~100 bytes; pytest's tmp_path may not."""
    return Path(tempfile.mkdtemp(prefix="dvm-", dir="/tmp"))


def test_the_script_stops_the_holder_of_the_daemon_socket_and_the_gui_lock(tmp_path):
    work = _short_dir()
    sock, lock = work / "d.sock", work / "gui.lock"
    bystander = _spawn_sleeper()
    try:
        with _holder("socket", sock) as daemon, _holder("lock", lock) as gui:
            done = _run_script(tmp_path, sockets=str(sock), lock=str(lock))
            assert done.returncode == 0, done.stderr
            assert _wait_gone(daemon), "the process holding the daemon socket was not stopped"
            assert _wait_gone(gui), "the process holding the GUI lock was not stopped"
            os.kill(bystander.pid, 0)  # holds nothing: left alone
    finally:
        bystander.kill()
        bystander.wait(timeout=5)
        shutil.rmtree(work, ignore_errors=True)


def test_the_script_leaves_a_socket_with_no_holder_alone(tmp_path):
    work = _short_dir()
    stale = work / "stale.sock"
    stale.write_text("")  # a path nobody holds
    bystander = _spawn_sleeper()
    try:
        done = _run_script(tmp_path, sockets=str(stale))
        assert done.returncode == 0, done.stderr
        os.kill(bystander.pid, 0)
        assert "nothing to stop" in done.stdout
    finally:
        bystander.kill()
        bystander.wait(timeout=5)
        shutil.rmtree(work, ignore_errors=True)
