"""The launchd gate must bite — this is the one that catches a job that died.

The 36-day failure (2026-09-14 → 2026-10-20): `com.divoom.monthlybest` ran a
file that commit `6a4f91a` moved to `examples/divoom_legacy/`, and the job
exited 2 every day into a log nobody read. Nothing in this repo could see it,
because the job's definition lived in `~/Library/LaunchAgents/` — outside the
repo, where no gate looks.

`tools/check_launchd_jobs.py` is that gate, and `docs/launchd_jobs.json` is
this repo's declaration of the launchd jobs it installs. These tests are its
both-directions proof: the broken job must be a finding, and a healthy job
must not be — and the tool's own self-test (which runs on CI, where there is
no LaunchAgents) must be able to fail, or the CI step would be a step that
cannot fail.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "tools" / "check_launchd_jobs.py"
DECLARATION = REPO / "docs" / "launchd_jobs.json"


def _load():
    spec = importlib.util.spec_from_file_location("_launchd_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def gate():
    return _load()


@pytest.fixture()
def tree():
    """A fixture tree INSIDE the checkout.

    A temp path on macOS is under /var/folders, which the tool treats as
    volatile (a socket path is legitimately absent between runs) — and a
    fixture whose own paths are volatile cannot exercise the rule about a job
    that names a path inside the checkout.
    """
    scratch = REPO / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=scratch))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _plist(path: Path, label: str, args: list[str]) -> None:
    import plistlib

    path.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": args}))


def _declaration(path: Path, jobs: list[dict]) -> Path:
    target = path / "docs" / "launchd_jobs.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"jobs": jobs}, indent=2), encoding="utf-8")
    return target


def test_the_declaration_file_exists_and_is_the_repo_s_own(gate):
    """The subject of the gate lives in the repo — that is the whole fix."""
    assert DECLARATION.is_file(), (
        f"{DECLARATION} is missing: the declaration of this repo's launchd jobs "
        f"is the gate's subject, and it must be in the repo"
    )
    data = json.loads(DECLARATION.read_text(encoding="utf-8"))
    assert isinstance(data.get("jobs"), list)


def test_every_declared_job_names_files_that_exist(gate):
    """What would have turned 6a4f91a red: the declared script moved."""
    data = json.loads(DECLARATION.read_text(encoding="utf-8"))
    for job in data["jobs"]:
        for rel in gate.declared_paths(job):
            assert (REPO / rel).exists(), f"declared job {job.get('label')} names {rel}, which is gone"


def test_a_declared_job_whose_file_was_deleted_is_a_finding(gate, tree):
    repo = tree / "repo"
    (repo / "divoom_lib").mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    declaration = _declaration(repo, [
        {"label": "com.divoom.monthlybest",
         "program": "divoom_lib/monthly_best_daemon.py"},
    ])
    findings, _warnings, _counts = gate.check(repo, agents, {}, declaration)
    assert any("monthly_best_daemon.py" in f and "does not exist" in f
               for f in findings), findings


def test_an_installed_job_nobody_declared_is_a_finding(gate, tree):
    """The 2026-09-14 shape: a job whose definition is outside the repo."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.divoom.monthlybest.plist", "com.divoom.monthlybest",
           [sys.executable])
    declaration = _declaration(repo, [])
    findings, _warnings, counts = gate.check(
        repo, agents, {"com.divoom.monthlybest": ("-", "0")}, declaration)
    assert counts["mine"] == 1
    assert any("NOT declared" in f for f in findings), findings


def test_an_installed_job_naming_a_deleted_file_is_a_finding(gate, tree):
    repo = tree / "repo"
    (repo / "divoom_lib").mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.divoom.monthlybest.plist", "com.divoom.monthlybest",
           [sys.executable, str(repo / "divoom_lib" / "monthly_best_daemon.py")])
    declaration = _declaration(repo, [
        {"label": "com.divoom.monthlybest",
         "program": "divoom_lib/monthly_best_daemon.py"},
    ])
    findings, _warnings, _counts = gate.check(
        repo, agents, {"com.divoom.monthlybest": ("-", "0")}, declaration)
    assert any("monthly_best_daemon.py" in f and "does not exist" in f
               for f in findings), findings


def test_a_dead_job_of_this_repo_is_a_finding(gate, tree):
    """Exit status 2 with no process running: the job is dead."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.divoom.monthlybest.plist", "com.divoom.monthlybest",
           [sys.executable])
    declaration = _declaration(repo, [
        {"label": "com.divoom.monthlybest", "program": "tools/x.py"},
    ])
    findings, _warnings, _counts = gate.check(
        repo, agents, {"com.divoom.monthlybest": ("-", "2")}, declaration)
    assert any("dead" in f and "exit status is 2" in f for f in findings), findings


def test_a_running_job_is_not_dead(gate, tree):
    """A pid means it is running; its last exit status is history."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.divoom.monthlybest.plist", "com.divoom.monthlybest",
           [sys.executable])
    declaration = _declaration(repo, [
        {"label": "com.divoom.monthlybest", "program": "tools/x.py"},
    ])
    findings, _warnings, _counts = gate.check(
        repo, agents, {"com.divoom.monthlybest": ("4242", "2")}, declaration)
    assert not any("dead" in f for f in findings), findings


def test_a_healthy_declared_and_installed_job_is_not_a_finding(gate, tree):
    """Not always-red: without this, the findings above prove nothing."""
    repo = tree / "repo"
    (repo / "tools").mkdir(parents=True)
    script = repo / "tools" / "x.py"
    script.write_text("# present\n")
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.divoom.monthlybest.plist", "com.divoom.monthlybest",
           [sys.executable, str(script)])
    declaration = _declaration(repo, [
        {"label": "com.divoom.monthlybest", "program": "tools/x.py"},
    ])
    findings, _warnings, _counts = gate.check(
        repo, agents, {"com.divoom.monthlybest": ("-", "0")}, declaration)
    assert findings == [], findings


def test_a_disabled_job_is_not_a_finding(gate, tree):
    """A job the owner turned off is not a fault."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    import plistlib

    (agents / "com.divoom.monthlybest.plist").write_bytes(plistlib.dumps({
        "Label": "com.divoom.monthlybest",
        "ProgramArguments": ["/nonexistent/python3"],
        "Disabled": True,
    }))
    declaration = _declaration(repo, [])
    findings, _warnings, _counts = gate.check(repo, agents, {}, declaration)
    assert findings == [], findings


def test_another_repos_dead_job_is_a_warning_not_a_failure(gate, tree):
    """It is not this repo's to fix, and a gate that cries wolf gets switched off."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.someone.else.plist", "com.someone.else",
           [sys.executable])
    declaration = _declaration(repo, [])
    findings, warnings, _counts = gate.check(
        repo, agents, {"com.someone.else": ("-", "2")}, declaration)
    assert findings == [], findings
    assert any("com.someone.else" in w for w in warnings), warnings


def test_another_repos_job_with_a_gone_program_is_a_warning(gate, tree):
    """Same rule: reported, not fatal — the fix belongs to that repo."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.someone.else.plist", "com.someone.else",
           ["/nonexistent/binary"])
    declaration = _declaration(repo, [])
    findings, warnings, _counts = gate.check(repo, agents, {}, declaration)
    assert findings == [], findings
    assert any("can never start" in w for w in warnings), warnings


def test_this_repos_job_with_a_gone_program_is_a_failure(gate, tree):
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    _plist(agents / "com.divoom.monthlybest.plist", "com.divoom.monthlybest",
           ["/nonexistent/python3"])
    declaration = _declaration(repo, [
        {"label": "com.divoom.monthlybest", "program": "tools/x.py"},
    ])
    findings, _warnings, _counts = gate.check(
        repo, agents, {"com.divoom.monthlybest": ("-", "0")}, declaration)
    assert any("can never start" in f for f in findings), findings


def test_a_missing_declaration_is_a_finding_not_an_empty_list(gate, tree):
    """A subject that is gone is not a clean tree."""
    repo = tree / "repo"
    repo.mkdir(parents=True)
    agents = tree / "LaunchAgents"
    agents.mkdir()
    findings, _warnings, _counts = gate.check(
        repo, agents, {}, repo / "docs" / "launchd_jobs.json")
    assert any("is missing" in f for f in findings), findings


def test_the_self_test_passes_on_the_current_checker(gate):
    assert gate.self_test() == []


def test_the_self_test_can_fail(gate, monkeypatch):
    """The calibration must bite: a checker that cannot see a dead job is red."""
    monkeypatch.setattr(gate, "check", lambda *a, **k: ([], [], {}))
    problems = gate.self_test()
    assert problems, "the self-test accepted a checker that sees nothing"


def test_launchctl_output_is_parsed_into_pid_and_status(gate):
    text = ("PID\tStatus\tLabel\n"
            "-\t2\tcom.divoom.monthlybest\n"
            "4242\t0\tcom.ztomer.other\n")
    statuses = gate.launchctl_status(text)
    assert statuses["com.divoom.monthlybest"] == ("-", "2")
    assert statuses["com.ztomer.other"] == ("4242", "0")
    assert "Label" not in statuses


def test_a_socket_path_is_not_a_missing_file(gate):
    """A socket is absent between runs; that is not a deleted file."""
    assert gate.is_volatile("/tmp/divoom.sock")


def test_the_gate_is_wired_into_the_ci_steps_and_into_ci():
    """A gate nobody runs is not a gate (house rule #3)."""
    gatesrc = (REPO / ".gatesrc").read_text(encoding="utf-8")
    steps = re.search(r"^GOH_CI_STEPS='([^']*)'", gatesrc, re.MULTILINE)
    assert steps, "no GOH_CI_STEPS line in .gatesrc"
    assert "tools/check_launchd_jobs.py" in steps.group(1), (
        "the launchd gate is not in GOH_CI_STEPS — it would be a gate nobody runs"
    )
    workflow = (REPO / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8")
    assert "tools/check_launchd_jobs.py" in workflow, (
        "the launchd gate is not in CI — CI would not see it"
    )


class _Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.mark.parametrize(
    "run",
    [
        lambda *a, **k: _Done(returncode=1, stderr="Could not connect to launchd"),
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("launchctl")),
        lambda *a, **k: _Done(returncode=0, stdout="nothing the parser reads\n"),
    ],
    ids=["nonzero-exit", "cannot-run", "no-rows"],
)
def test_an_unreadable_launchctl_fails_closed(gate, run):
    """A `launchctl list` that failed is NOT "launchd has no jobs"."""
    with pytest.raises(gate.LaunchctlUnreadable):
        gate.read_launchctl_status(run=run)


def test_a_readable_launchctl_is_parsed(gate):
    text = "PID\tStatus\tLabel\n-\t0\tcom.apple.x\n"
    assert gate.read_launchctl_status(
        run=lambda *a, **k: _Done(stdout=text)) == {"com.apple.x": ("-", "0")}


def test_the_gate_is_red_when_launchctl_cannot_be_read(gate, tree, monkeypatch):
    """Where there are LaunchAgents to judge, an unreadable launchd is red."""
    agents = tree / "LaunchAgents"
    agents.mkdir(exist_ok=True)
    monkeypatch.setattr(gate, "AGENTS_DIR", agents)

    def unreadable(run=None):
        raise gate.LaunchctlUnreadable("`launchctl list` exited 1")

    monkeypatch.setattr(gate, "read_launchctl_status", unreadable)
    assert gate.main() == 1
