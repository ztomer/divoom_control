#!/usr/bin/env python3
"""check_launchd_jobs.py — a launchd job that points at a deleted file is a FINDING.

THE FAILURE THIS EXISTS FOR (2026-09-14 → 2026-10-20, 36 days).
`com.divoom.monthlybest` ran `divoom_lib/monthly_best_daemon.py` every
86400 s. Commit `6a4f91a` (2026-09-14) moved that file to
`examples/divoom_legacy/`, and the job kept running against the empty path:
exit status 2, 29 × "can't open file ... [Errno 2] No such file or
directory", last written 2026-10-19 20:50, into `test_reports/` — a log
nobody read. The estate-wide survey found it on 2026-10-20; NOTHING in this
repo could, because THE JOB'S DEFINITION LIVED OUTSIDE THE REPO: it was in
`~/Library/LaunchAgents/`, installed by `scripts/install_daemon.sh`, which
`34045c0` (2026-08-30) deleted from this repo as superseded. A file the repo
does not hold is a file no gate in the repo can fail over.

So the declaration moved IN: `docs/launchd_jobs.json` is this repo's list of
the launchd jobs it installs, with repo-relative paths, and this gate holds
three things together:

  1. THE DECLARATION IS REAL. Every path a declared job names must exist in
     the checkout. This is the check that would have turned `6a4f91a` RED:
     the declared script moved, and the job was pointing at nothing.
  2. THE DECLARATION IS TRUE. An installed launchd agent of this repo's that
     is not declared is a finding — the 2026-09-14 shape exactly: a job whose
     definition nobody in this repo can see.
  3. THE JOB IS ALIVE. A declared or installed job of this repo's must not
     be dead (launchd's last exit status non-zero while it is not running),
     and must not name a file that is gone.

The live half reads ONE machine's LaunchAgents, so it is the half that cannot
run in CI. Before it is trusted it runs ITSELF over fixtures — a healthy job,
a job naming a deleted file, a job whose last run failed, and an UNDECLARED
job of this repo's — and FAILS unless it flags exactly the three bad ones.
An instrument that cannot see the failure is not a gate, and this is the
calibration that proves it can.

WHAT IT DOES NOT DO. It does not decide whether a job SHOULD exist — that is
the owner's call, and `docs/ROADMAP.md` carries the question with the
evidence. It does not fix another repo's job: another repo's DEAD job is
reported as a warning, not a failure, because a gate that fails on another
repo's problem is a gate that cries wolf and gets switched off.

HONEST SCOPE:
  * One machine's LaunchAgents. A job installed on another host is invisible.
  * "This repo's business" is the `com.divoom.` label namespace (the app's
    bundle id is `com.divoom.control`) plus any argument pointing inside this
    checkout. Another repo's job is not judged: a dead one, or one whose
    program is gone, is REPORTED as a warning and is not this repo's to fix.
    A gate that fails on another repo's problem is a gate that gets switched
    off.
  * A job that is RUNNING is not dead, whatever its last exit status was.
  * Paths under /tmp are not checked for existence: a socket path is absent
    between runs, and a gate that cries wolf is a gate nobody runs.
"""
from __future__ import annotations

import json
import plistlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok, warn  # noqa: E402
from _empty_scope import scope_is_empty  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The app's bundle id is com.divoom.control; a job of this repo's carries a
# label in that namespace.
LABEL_PREFIX = "com.divoom."
DECLARATION = REPO / "docs" / "launchd_jobs.json"
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
# A socket path is absent between runs; "the file is gone" is not a finding.
VOLATILE_PREFIXES = ("/tmp/", "/var/folders/", "/private/var/folders/")


@dataclass(frozen=True)
class Job:
    """One launchd agent, as its plist declares it."""

    path: Path
    label: str
    args: tuple[str, ...]
    disabled: bool

    @property
    def program(self) -> str:
        return self.args[0] if self.args else ""


def read_jobs(agents_dir: Path) -> list[Job]:
    """Every agent in `agents_dir`, read from its plist.

    A plist that does not parse is skipped, not fatal: launchd refuses to
    load a malformed agent too, and the live check reports "installed but not
    loaded" for it.
    """
    jobs: list[Job] = []
    if not agents_dir.is_dir():
        return jobs
    for path in sorted(agents_dir.glob("*.plist")):
        try:
            with path.open("rb") as handle:
                data = plistlib.load(handle)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        args = data.get("ProgramArguments") or []
        if not args and isinstance(data.get("Program"), str):
            # launchd runs `Program` when there is no ProgramArguments.
            args = [data["Program"]]
        jobs.append(
            Job(
                path=path,
                label=str(data.get("Label") or path.stem),
                args=tuple(str(a) for a in args),
                disabled=bool(data.get("Disabled", False)),
            )
        )
    return jobs


def launchctl_status(text: str) -> dict[str, tuple[str, str]]:
    """`launchctl list` output -> label -> (pid, last exit status).

    A job that is running has a pid; a job that has stopped has "-" and the
    status of its last run.
    """
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = (p.strip() for p in parts)
        if label == "Label":
            continue
        out[label] = (pid, status)
    return out


def read_launchctl_status() -> dict[str, tuple[str, str]]:
    """The live `launchctl list`, or an empty map when it cannot be read."""
    try:
        done = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if done.returncode != 0:
        return {}
    return launchctl_status(done.stdout)


def in_scope(job: Job, repo_root: Path) -> bool:
    """Is this job this repo's business?

    The label namespace, or any argument pointing inside this checkout — a
    job that runs something out of this repo's tree is this repo's business
    whatever it is called.
    """
    if job.label.startswith(LABEL_PREFIX):
        return True
    root = f"{repo_root}/"
    return any(a.startswith(root) for a in job.args)


def is_volatile(path: str) -> bool:
    """A path that is legitimately absent between runs (a socket)."""
    return path.startswith(VOLATILE_PREFIXES)


def load_declaration(path: Path) -> tuple[list[dict], list[str]]:
    """(declared jobs, problems) from this repo's declaration file.

    A MISSING declaration is a problem, not an empty list: the declaration
    is the gate's subject, and a subject that is gone is not a clean tree.
    """
    if not path.is_file():
        return [], [
            f"{path} is missing — this repo's declaration of the launchd jobs it "
            f"installs is the gate's subject, and it is gone"
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], [f"{path} does not parse: {exc}"]
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return [], [f"{path} has no 'jobs' list"]
    return [j for j in jobs if isinstance(j, dict)], []


def declared_paths(job: dict) -> list[str]:
    """The repo-relative paths a declared job names."""
    paths: list[str] = []
    program = job.get("program")
    if isinstance(program, str) and program:
        paths.append(program)
    for arg in job.get("arguments") or []:
        if isinstance(arg, str) and arg:
            paths.append(arg)
    return paths


def check(
    repo_root: Path,
    agents_dir: Path,
    statuses: dict[str, tuple[str, str]],
    declaration_path: Path,
) -> tuple[list[str], list[str], dict[str, int]]:
    """(findings, warnings, counts) for this repo's launchd jobs."""
    findings: list[str] = []
    warnings: list[str] = []
    declared, problems = load_declaration(declaration_path)
    findings.extend(problems)

    counts = {"declared": len(declared)}

    # 1. The declaration is real: every path a declared job names exists.
    for job in declared:
        label = str(job.get("label") or "(unnamed)")
        for rel in declared_paths(job):
            target = repo_root / rel
            if not target.exists():
                findings.append(
                    f"declared job {label}: names {rel}, which does not exist — "
                    f"the file moved or was deleted, and the job would fail every "
                    f"time it ran"
                )

    installed = read_jobs(agents_dir)
    counts["installed"] = len(installed)
    mine = [j for j in installed if in_scope(j, repo_root)]
    counts["mine"] = len(mine)
    declared_labels = {str(j.get("label")) for j in declared}

    for job in installed:
        if job.disabled:
            continue
        scope = in_scope(job, repo_root)
        # 2. A PROGRAM that does not exist: that job can never start. Fatal
        #    for this repo's jobs; another repo's is reported, not fatal (see
        #    the note on warnings below).
        program = job.program
        missing_program = (
            program.startswith("/")
            and not is_volatile(program)
            and not Path(program).exists()
        )
        if missing_program:
            message = (
                f"{job.label}: runs {program}, which does not exist — the job "
                f"can never start"
            )
            if scope:
                findings.append(message)
            else:
                warnings.append(f"{message} (another repo's job)")
        # 3. A path INSIDE this checkout that does not exist: the 36-day
        #    failure, whatever the job is called.
        root = f"{repo_root}/"
        for arg in job.args[1:]:
            if arg.startswith(root) and not is_volatile(arg) and not Path(arg).exists():
                findings.append(
                    f"{job.label}: names {arg}, which does not exist — the file "
                    f"moved or was deleted"
                )
        if not scope:
            continue
        # 4. A job of this repo's that nobody declared: the definition is
        #    outside the repo, so no gate in CI can see it.
        if job.label not in declared_labels:
            findings.append(
                f"{job.label}: installed at {job.path} but NOT declared in "
                f"{declaration_path.name} — a launchd job whose definition is "
                f"outside the repo is the 2026-09-14 shape"
            )
        # 5. Dead: launchd's last exit status, with no process running.
        state = statuses.get(job.label)
        if state is None:
            findings.append(
                f"{job.label}: installed at {job.path} but not loaded by launchd — "
                f"it will not run until it is bootstrapped"
            )
        else:
            pid, status = state
            if pid == "-" and status not in ("0", ""):
                findings.append(
                    f"{job.label}: dead — launchd's last exit status is {status}"
                )
    # Another repo's DEAD job: reported, not fatal. It is not this repo's to
    # fix, and a gate that fails on another repo's problem gets switched off.
    for job in installed:
        if job.disabled or in_scope(job, repo_root):
            continue
        state = statuses.get(job.label)
        if state is None:
            continue
        pid, status = state
        if pid == "-" and status not in ("0", ""):
            warnings.append(
                f"{job.label} (another repo's): dead — launchd's last exit "
                f"status is {status}"
            )
    return findings, warnings, counts


def _write_plist(path: Path, label: str, args: list[str]) -> None:
    path.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": args}))


def _write_declaration(path: Path, jobs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jobs": jobs}, indent=2), encoding="utf-8")


def self_test() -> list[str]:
    """Prove the checker can SEE the failures, before it is trusted to report one.

    A checker that cannot fail is not a gate. The live half cannot run on CI,
    so the fixtures are what runs everywhere: they must produce exactly the
    three findings below, and none on the healthy job.
    """
    problems: list[str] = []
    # The fixtures live INSIDE the checkout (under the gitignored `scratch/`),
    # not in the system temp directory: a temp path on macOS is under
    # /var/folders, which this tool treats as volatile, and a fixture whose
    # own paths are volatile cannot exercise the rule about a path inside
    # the checkout.
    fixtures_dir = REPO / "scratch"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=fixtures_dir) as tmp:
        root = Path(tmp)
        agents = root / "LaunchAgents"
        agents.mkdir()
        repo = root / "repo"
        (repo / "divoom_lib").mkdir(parents=True)
        script = repo / "divoom_lib" / "live_daemon.py"
        script.write_text("# present\n")
        deleted = repo / "divoom_lib" / "deleted_daemon.py"
        declaration = repo / "docs" / "launchd_jobs.json"

        _write_plist(agents / "com.divoom.healthy.plist", "com.divoom.healthy",
                     [sys.executable, str(script)])
        _write_plist(agents / "com.divoom.missing.plist", "com.divoom.missing",
                     [sys.executable, str(deleted)])
        _write_plist(agents / "com.divoom.failed.plist", "com.divoom.failed",
                     [sys.executable, str(script)])
        _write_plist(agents / "com.divoom.undeclared.plist", "com.divoom.undeclared",
                     [sys.executable, str(script)])
        _write_declaration(
            declaration,
            [
                {"label": "com.divoom.healthy", "program": "divoom_lib/live_daemon.py"},
                {"label": "com.divoom.missing",
                 "program": "divoom_lib/deleted_daemon.py"},
                {"label": "com.divoom.failed", "program": "divoom_lib/live_daemon.py"},
            ],
        )
        statuses = {
            "com.divoom.healthy": ("-", "0"),
            "com.divoom.missing": ("-", "0"),
            "com.divoom.failed": ("-", "2"),
            "com.divoom.undeclared": ("-", "0"),
        }

        findings, _warnings, counts = check(repo, agents, statuses, declaration)
        if counts.get("declared") != 3 or counts.get("mine") != 4:
            problems.append(
                f"the self-test saw {counts.get('declared')} declared and "
                f"{counts.get('mine')} in-scope jobs, not 3 and 4 — the checker's "
                f"scope is not what it claims"
            )
        if len(findings) != 4:
            problems.append(
                f"the self-test produced {len(findings)} findings for 4 broken "
                f"jobs: {findings}"
            )
        else:
            if not any("deleted_daemon.py" in f and "does not exist" in f
                       for f in findings):
                problems.append(
                    "the self-test did NOT flag the job whose file was deleted — "
                    "this checker cannot see the 36-day failure"
                )
            if not any("exit status is 2" in f for f in findings):
                problems.append(
                    "the self-test did NOT flag the job whose last run failed"
                )
            if not any("NOT declared" in f for f in findings):
                problems.append(
                    "the self-test did NOT flag the job nobody declared"
                )
        healthy = [j for j in read_jobs(agents) if j.label == "com.divoom.healthy"]
        if healthy:
            healthy_findings, _w, _c = check(repo, agents, statuses, declaration)
            healthy_only = [f for f in healthy_findings if "healthy" in f]
            if healthy_only:
                problems.append(
                    f"the self-test flagged a HEALTHY job: {healthy_only}"
                )
    return problems


def main() -> int:
    problems = self_test()
    if problems:
        err("[launchd-jobs] the checker itself is broken — it cannot be trusted")
        for p in problems:
            info(f"  {p}")
        return 1

    findings, warnings, counts = check(
        REPO, AGENTS_DIR, read_launchctl_status(), DECLARATION
    )
    if AGENTS_DIR.is_dir() and scope_is_empty(
        "launchd-jobs", counts["installed"], unit="launchd agents"
    ):
        return 1
    for w in warnings:
        warn(f"[launchd-jobs] {w}")
    if findings:
        err(f"[launchd-jobs] {len(findings)} finding(s) — "
            f"{counts['declared']} declared job(s), {counts['mine']} of this "
            f"repo's installed")
        for f in findings:
            info(f"  {f}")
        return 1
    ok(f"[launchd-jobs] OK — {counts['declared']} declared job(s), "
       f"{counts['mine']} of this repo's installed, none dead, and the checker "
       f"proved it can see one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
