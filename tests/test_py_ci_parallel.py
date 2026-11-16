"""py_ci.sh runs both of its pytest suites across xdist workers (CIP.DIVOOMCONTROL).

Profiled 2026-11-15 at load 66-97 on 16 cores: the push gate took 953 s and
py_ci.sh was the largest step at 327 s, because both of its suites ran on ONE
core. Back to back at load ~87 the main suite took 461 s serial and 72 s at
`-n 8`, both 2506 passed / 239 skipped, coverage 92.02% against 92.00%; the
examples suite 45 s -> 25 s at 1577 / 58 either way. The browser suites already
ran eight-wide (scripts/browser_e2e.sh). Same results, a fraction of the time
-- and a later edit that drops the flag would put the gate back over its
budget with nothing saying so, which is what this test is for.

The worker count is DIVOOM_PY_WORKERS (default 8), the same shape as
DIVOOM_BROWSER_WORKERS; 0 means in-process, which pytest-xdist reads as serial.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_CI = ROOT / "scripts" / "py_ci.sh"


def _run_py_ci(tmp_path: Path, extra_env: dict[str, str] | None = None) -> list[str]:
    """Run py_ci.sh with python3 and cargo faked; return the pytest command lines."""
    log = tmp_path / "calls.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    py = ROOT.joinpath(".python-version").read_text().strip()
    tools = {
        "python3": f'#!/bin/sh\necho "python3 $*" >> "{log}"\n[ "$1" = "-c" ] && {{ echo "{py}"; exit 0; }}\nexit 0\n',
        "cargo": f'#!/bin/sh\necho "cargo $*" >> "{log}"\nexit 0\n',
    }
    for name, body in tools.items():
        tool = bindir / name
        tool.write_text(body)
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", NO_COLOR="1")
    env.pop("DIVOOM_PY_WORKERS", None)
    env.update(extra_env or {})
    r = subprocess.run(
        ["bash", str(PY_CI)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert r.returncode == 0, r.stderr[-400:]
    return [c for c in log.read_text().splitlines() if c.startswith("python3 -m pytest")]


def _workers(call: str) -> str | None:
    words = call.split()
    return words[words.index("-n") + 1] if "-n" in words else None


def test_both_suites_run_eight_wide_by_default(tmp_path: Path) -> None:
    calls = _run_py_ci(tmp_path)
    assert len(calls) == 2, calls
    assert [_workers(c) for c in calls] == ["8", "8"], calls


def test_the_worker_count_is_the_callers_to_set(tmp_path: Path) -> None:
    calls = _run_py_ci(tmp_path, {"DIVOOM_PY_WORKERS": "0"})
    assert [_workers(c) for c in calls] == ["0", "0"], calls


def test_the_coverage_floor_still_binds_the_parallel_run(tmp_path: Path) -> None:
    main = _run_py_ci(tmp_path)[0]
    assert "--cov-fail-under=" in main and "--cov=divoom_gui" in main and "--cov=divoom_client" in main, main
