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
  image) [ -f "$STUB_STATE/noimage" ] && exit 1; exit 0 ;;
  images) cat "$STUB_STATE/images" 2>/dev/null; exit 0 ;;
  run) echo "rustc 1.99.0 (stub)"; [ -f "$STUB_STATE/warn" ] && echo "warning: unused dependency plist"; exit 0 ;;
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


def _run(
    tmp_path: pathlib.Path, *, up: bool, busy: bool = False, state_files: dict[str, str] | None = None
) -> tuple[int, list[str], str]:
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
    for name, body in (state_files or {}).items():
        (state / name).write_text(body)
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


def _run_without_docker(tmp_path: pathlib.Path, hosted: bool) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "DIVOOM_SKIP_LINUX_ALL_FEATURES")}
    env.update({"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path), "NO_COLOR": "1"})
    if hosted:
        env["GITHUB_ACTIONS"] = "true"
    r = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=60, check=False,
    )  # fmt: skip
    return r.returncode, r.stdout + r.stderr


def test_no_docker_on_a_hosted_macos_runner_is_not_applicable(tmp_path):
    """divoom run 42916398583: the macOS-hosted runner has no docker, and the step was red for a
    reason no commit can fix. There, and only there, it says NOT APPLICABLE (78, goh's
    lib/not_applicable.py contract) and names the Linux job that runs it; the gate's local_ci
    accepts 78 on a hosted run only."""
    rc, out = _run_without_docker(tmp_path, hosted=True)
    assert rc == 78, out
    assert "NOT APPLICABLE on this hosted runner" in out and "linux-all-features" in out, out


def test_no_docker_on_the_owners_machine_stays_red(tmp_path):
    """The owner's machine is the judge of record: no docker there is the gate's failure."""
    rc, out = _run_without_docker(tmp_path, hosted=False)
    assert rc == 1, out
    assert "missing: docker" in out and "NOT APPLICABLE" not in out, out


def test_the_cargo_target_dir_is_a_named_volume_not_a_host_mount(tmp_path):
    """DV.LINTEXEC: 0.45.7's push went red at `Permission denied (os error 13)` executing
    /cache/target/debug/build/divoomd-9c4e6881eafa11a7/build-script-build. The target dir was a
    host directory bind-mounted through colima's virtiofs, and the linker's exec bit on that file
    never reached the host (mode 644 on both sides; the same link re-run minutes later was 755):
    the gate's verdict hung on macOS-side virtiofs setattr semantics, not on the code. Cargo's
    target dir is a docker NAMED volume, which lives on the VM's own Linux filesystem, so no
    build artifact the container execs ever crosses the host mount."""
    rc, calls, out = _run(tmp_path, up=True)
    assert rc == 0, out
    run = next(c for c in calls if c.startswith("docker run "))
    args = run.split()
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    target = [m for m in mounts if m.split(":")[1] == "/cache/target"]
    assert len(target) == 1, mounts
    source = target[0].split(":")[0]
    assert "/" not in source, f"cargo's target dir is a host bind mount: {source}"
    assert "-e CARGO_TARGET_DIR=/cache/target" in run, run
    assert not (tmp_path / "cache").exists(), "the gate still creates a host-side target cache"


def test_the_image_is_made_without_the_legacy_builder(tmp_path):
    """DV.LINTTIDY: `docker build` without buildx runs the deprecated legacy builder (docker
    prints "DEPRECATED: The legacy builder is deprecated and will be removed"), which house rule 17
    forbids building on. The lint image is the base plus one rustup component, made by running that
    one command in a container of the base and committing it: no builder at all, nothing to install
    (buildx is a brew plugin this machine and a CI runner need not have), and the same image."""
    rc, calls, out = _run(tmp_path, up=True, state_files={"noimage": ""})
    assert rc == 0, out
    assert not any(c.startswith(("docker build", "docker buildx", "docker image build")) for c in calls), calls
    run = next(c for c in calls if c.startswith("docker run ") and "component add clippy" in c)
    assert "rust:1.100.0-trixie" in run, run
    commit = next(c for c in calls if c.startswith("docker commit "))
    assert commit.endswith("divoom-linux-lint:1.100.0-trixie"), commit
    # the build container is removed again, so a failed or finished build leaves nothing behind
    assert any(c.startswith("docker rm ") for c in calls), calls


def test_a_moved_base_tag_removes_the_images_it_replaced(tmp_path):
    """DV.LINTTIDY: raising BASE_TAG left divoom-linux-lint:1.99.1-trixie and rust:1.99.1-trixie
    (2.2 GB and the base under it) on the colima disk for good. The gate drops the lint images of its
    own repository whose tag is not the current one, and the `rust:<tag>` each was made from. Never a
    forced removal (an image a container or another image still uses survives), and never an image
    this gate did not make."""
    images = "1.100.0-trixie\n1.99.1-trixie\nlatest\n"
    rc, calls, out = _run(tmp_path, up=True, state_files={"images": images})
    assert rc == 0, out
    removed = [c for c in calls if c.startswith("docker rmi ")]
    assert "docker rmi divoom-linux-lint:1.99.1-trixie" in removed, calls
    assert "docker rmi rust:1.99.1-trixie" in removed, calls
    assert "docker rmi divoom-linux-lint:latest" in removed, calls
    assert not any("1.100.0" in c for c in removed), removed
    assert not any("-f" in c.split() or "--force" in c.split() for c in removed), removed
    # the lint image goes first: the base under it cannot be removed while it stands
    assert calls.index("docker rmi divoom-linux-lint:1.99.1-trixie") < calls.index("docker rmi rust:1.99.1-trixie")
    assert not any(c.startswith("docker rmi") and "rust:latest" in c for c in calls), calls


def test_no_stale_image_means_nothing_is_removed(tmp_path):
    rc, calls, out = _run(tmp_path, up=True, state_files={"images": "1.100.0-trixie\n"})
    assert rc == 0, out
    assert not any(c.startswith("docker rmi") for c in calls), calls


def test_a_cargo_warning_in_the_lint_log_is_red(tmp_path):
    """DV.LINTTIDY: `-D warnings` after `--` reaches rustc and clippy, not cargo's own manifest
    lints, so `warning: unused dependency plist` printed in a run the gate called OK. The gate reads
    its own log: any `warning` line is red, naming it."""
    rc, _, out = _run(tmp_path, up=True, state_files={"warn": ""})
    assert rc == 1, out
    assert "unused dependency" in out, out


def test_cargo_manifest_keeps_macos_only_crates_out_of_the_linux_build():
    """DV.LINTTIDY: `plist` and `rusqlite` are read only by `notification_db` and
    `macos_notifications`, both `#[cfg(target_os = "macos")]`; as plain dependencies Linux compiled
    (rusqlite bundles SQLite's C source) and linked crates nothing there calls."""
    import tomllib

    manifest = tomllib.loads((ROOT / "divoomd" / "Cargo.toml").read_text())
    plain = set(manifest["dependencies"])
    macos = set(manifest["target"]['cfg(target_os = "macos")']["dependencies"])
    for crate in ("plist", "rusqlite"):
        assert crate not in plain, f"{crate} is built on Linux, which never uses it"
        assert crate in macos, f"{crate} is gone from the macOS dependencies"
