"""The Linux `--all-features` gate starts the container runtime it needs, and
stops only what it started (owner ruling OW.27, 2026-10-31).

The pre-push step `scripts/check_linux_all_features.sh` was red whenever docker
happened to be down: "docker is installed but not running (start it, e.g.
`colima start`)". A gate that is red for a reason that is not the code is a
gate people learn to skip. So it starts colima when docker is not answering,
and stops it again on the way out -- only if this run started it, and not
while another container is running on it.

Driven with stub `docker` and `colima` executables on PATH (the `COLIMA`
seam names the stub), so both directions are proven on any machine, with no
container runtime at all.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_linux_all_features.sh"

# `docker info` answers only once the state file says the runtime is up;
# `docker run` prints a toolchain line and succeeds (the lint itself is not
# what is under test); every call is logged.
DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
case "$1" in
  info) [ -f "$STUB_STATE/up" ] ;;
  ps) [ -f "$STUB_STATE/busy" ] && echo abc123; exit 0 ;;
  image) exit 0 ;;
  run) echo "rustc 1.99.0 (stub)"; exit 0 ;;
  *) exit 0 ;;
esac
"""
COLIMA = """#!/usr/bin/env bash
echo "colima $*" >> "$STUB_LOG"
case "$1" in
  start) touch "$STUB_STATE/up" ;;
  stop) rm -f "$STUB_STATE/up" ;;
esac
"""


def _run(tmp_path: pathlib.Path, *, up: bool, busy: bool = False) -> tuple[int, list[str], str]:
    bin_dir = tmp_path / "bin"
    state = tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    for name, body in (("docker", DOCKER), ("colima-stub", COLIMA)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    if up:
        (state / "up").touch()
    if busy:
        (state / "busy").touch()
    log = tmp_path / "calls.log"
    log.touch()
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "STUB_LOG": str(log),
            "STUB_STATE": str(state),
            "COLIMA": "colima-stub",
            "DIVOOM_LINUX_LINT_CACHE": str(tmp_path / "cache"),
            "TMPDIR": str(tmp_path),
            # The leases live here, never in the machine's real state dir.
            "GOH_CONTAINER_STATE": str(tmp_path / "runtime_state"),
            "NO_COLOR": "1",
        }
    )
    env.pop("DIVOOM_SKIP_LINUX_ALL_FEATURES", None)
    r = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    return r.returncode, log.read_text().splitlines(), r.stdout + r.stderr


def test_docker_down_starts_colima_and_stops_it_after(tmp_path):
    rc, calls, out = _run(tmp_path, up=False)
    assert rc == 0, out
    assert "colima start" in calls, calls
    assert calls[-1] == "colima stop", calls
    assert calls.index("colima start") < calls.index("colima stop")


def test_docker_up_is_left_alone(tmp_path):
    rc, calls, out = _run(tmp_path, up=True)
    assert rc == 0, out
    assert not any(c.startswith("colima") for c in calls), calls


def test_a_runtime_someone_else_is_using_is_not_stopped(tmp_path):
    """Started here, but another container appeared on it meanwhile: leave it."""
    rc, calls, out = _run(tmp_path, up=False, busy=True)
    assert rc == 0, out
    assert "colima start" in calls and "colima stop" not in calls, calls
    assert "leaving colima-stub running" in out, out
