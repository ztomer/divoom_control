"""ci_local.sh leaves `target/debug/divoomd` BLE-free (queue D.BLEDBG).

`divoomd`'s default features include `ble`, so `cargo test --locked` and
`cargo build -p divoomd --locked` (the CI-mirroring steps) and the build inside
`scripts/py_ci.sh` all uplift a BLE-enabled binary to `target/debug/divoomd`.
Every later local run or probe then got a BLE build nobody asked for (seen by
D.TAP19). The tooling documents `--no-default-features` as the daemon's dev
build (scripts/gui_pov.py, tools/render_widget_backdrops.py).

The fix cannot be an ordering trick: goh's proven-step cache can skip a
trailing "rebuild BLE-free" step while a BLE step re-runs. So each BLE-building
step carries its own restore: `scripts/ble_free_after.sh CMD...` runs CMD and
then rebuilds the BLE-free daemon whatever CMD's status, and `py_ci.sh`
traps the same on exit.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATESRC = ROOT / ".gatesrc"
WRAPPER = ROOT / "scripts" / "ble_free_after.sh"
PY_CI = ROOT / "scripts" / "py_ci.sh"
RESTORE = ["build", "-p", "divoomd", "--no-default-features", "--locked"]


def _steps() -> list[str]:
    m = re.search(r"^GOH_CI_STEPS='([^']*)'", GATESRC.read_text(), re.MULTILINE)
    assert m, "no GOH_CI_STEPS in .gatesrc"
    return m.group(1).split(":")


def _builds_default_features(step: str) -> bool:
    """A cargo build/test/run step that compiles divoomd WITH its `ble` default
    into this tree's target/debug."""
    return bool(re.match(r"cargo (build|test|run)\b", step)) and not re.search(
        r"--no-default-features|--target-dir|--release", step
    )


def test_every_ble_building_ci_step_restores_the_ble_free_daemon() -> None:
    bare = [s for s in _steps() if _builds_default_features(s)]
    assert not bare, f"steps leave a BLE daemon in target/debug: {bare}"
    wrapped = [s for s in _steps() if s.startswith("./scripts/ble_free_after.sh ")]
    assert any("cargo test --locked" in s for s in wrapped)
    assert any("cargo build -p divoomd --locked" in s for s in wrapped)


def test_py_ci_restores_on_exit_before_it_builds_the_ble_daemon() -> None:
    text = PY_CI.read_text()
    assert re.search(r"^\s+\"\$ROOT/scripts/ble_free_after\.sh\" --restore", text, re.MULTILINE), (
        "py_ci.sh's EXIT trap must run scripts/ble_free_after.sh --restore"
    )
    trap = re.search(r"^trap restore_ble_free EXIT$", text, re.MULTILINE)
    assert trap, "py_ci.sh must trap EXIT into restore_ble_free"
    build = re.search(r"^cargo build -p divoomd --locked$", text, re.MULTILINE)
    assert build and trap.start() < build.start(), "the trap must precede the BLE build"


def _fake_cargo(tmp_path: Path, rc: int) -> tuple[dict[str, str], Path]:
    log = tmp_path / "calls.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    cargo = bindir / "cargo"
    # The first call is the wrapped command and answers FAKE_RC; later ones succeed.
    cargo.write_text(
        f'#!/bin/sh\necho "$*" >> "{log}"\n[ "$(wc -l < "{log}")" -eq 1 ] && exit "${{FAKE_RC:-0}}"\nexit 0\n'
    )
    cargo.chmod(cargo.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_RC=str(rc))
    return env, log


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(WRAPPER), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def test_wrapper_rebuilds_ble_free_after_a_passing_command(tmp_path: Path) -> None:
    env, log = _fake_cargo(tmp_path, 0)
    r = _run(["cargo", "test", "--locked"], env)
    assert r.returncode == 0, r.stderr
    assert log.read_text().splitlines() == ["test --locked", " ".join(RESTORE)]


def test_wrapper_rebuilds_even_when_the_command_fails_and_keeps_its_status(tmp_path: Path) -> None:
    env, log = _fake_cargo(tmp_path, 7)
    r = _run(["cargo", "test", "--locked"], env)
    assert r.returncode == 7, "the command's own status must survive the restore"
    assert log.read_text().splitlines()[-1] == " ".join(RESTORE)


def test_wrapper_restore_flag_only_rebuilds(tmp_path: Path) -> None:
    env, log = _fake_cargo(tmp_path, 0)
    env["FAKE_RC"] = "0"
    log.write_text("seed\n")  # the wrapped-command slot is not used by --restore
    r = _run(["--restore"], env)
    assert r.returncode == 0, r.stderr
    assert log.read_text().splitlines() == ["seed", " ".join(RESTORE)]


def test_a_failed_restore_fails_the_step(tmp_path: Path) -> None:
    """Leaving a BLE daemon behind is the defect; a green step that did so is a lie."""
    env, log = _fake_cargo(tmp_path, 0)
    log.write_text("seed\n")
    (tmp_path / "bin" / "cargo").write_text("#!/bin/sh\nexit 3\n")
    r = _run(["--restore"], env)
    assert r.returncode == 3


def _fake_py_ci_tools(tmp_path: Path, *, pytest_rc: int, restore_rc: int) -> tuple[dict[str, str], Path]:
    """py_ci.sh's own tools, faked: python3 answers the version probe and runs a
    pytest that exits `pytest_rc`; cargo's BLE build passes and its BLE-free
    restore exits `restore_rc`."""
    log = tmp_path / "calls.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    py = ROOT.joinpath(".python-version").read_text().strip()
    tools = {
        "python3": (
            "#!/bin/sh\n"
            f'echo "python3 $*" >> "{log}"\n'
            f'[ "$1" = "-c" ] && {{ echo "{py}"; exit 0; }}\n'
            f"exit {pytest_rc}\n"
        ),
        "cargo": (
            "#!/bin/sh\n"
            f'echo "cargo $*" >> "{log}"\n'
            f'case "$*" in *--no-default-features*) exit {restore_rc};; esac\n'
            "exit 0\n"
        ),
    }
    for name, body in tools.items():
        tool = bindir / name
        tool.write_text(body)
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", NO_COLOR="1")
    return env, log


def _run_py_ci(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(PY_CI)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def test_py_ci_fails_when_its_restore_fails_after_a_green_suite(tmp_path: Path) -> None:
    """A green py_ci that left the BLE daemon behind is the lie D.BLEDBG removed."""
    env, log = _fake_py_ci_tools(tmp_path, pytest_rc=0, restore_rc=3)
    r = _run_py_ci(env)
    calls = log.read_text().splitlines()
    assert "cargo " + " ".join(RESTORE) in calls, calls
    assert r.returncode == 3, (r.returncode, r.stderr[-400:])


def test_py_ci_keeps_the_suites_status_over_a_failed_restore(tmp_path: Path) -> None:
    env, log = _fake_py_ci_tools(tmp_path, pytest_rc=5, restore_rc=3)
    r = _run_py_ci(env)
    assert "cargo " + " ".join(RESTORE) in log.read_text().splitlines()
    assert r.returncode == 5, (r.returncode, r.stderr[-400:])


def test_py_ci_passes_when_the_suites_and_the_restore_do(tmp_path: Path) -> None:
    env, log = _fake_py_ci_tools(tmp_path, pytest_rc=0, restore_rc=0)
    r = _run_py_ci(env)
    assert r.returncode == 0, r.stderr[-400:]
    assert log.read_text().splitlines()[-1] == "cargo " + " ".join(RESTORE)
