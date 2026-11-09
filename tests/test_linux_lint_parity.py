"""The local Linux cross-lint runs CI's Linux clippy flags, flag for flag.

CI went red on 19 of 20 main runs (2026-10) with a Linux-only `unused import`
while the local pre-push gate stayed green: scripts/check_linux_build.sh ran
`clippy --no-default-features` without `--all-targets` or `-D warnings`, so a
warning -- the class CI denies -- passed locally as long as it compiled. This
pins the script's CI_LINT_ARGS to the rust-core job's "Lint core without BLE"
step, so the two cannot drift apart again without this going red.
"""

from __future__ import annotations

import pathlib
import re
import shlex

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
SCRIPT = ROOT / "scripts" / "check_linux_build.sh"


def _script_lint_args() -> list[str]:
    match = re.search(r"^CI_LINT_ARGS=\((.+)\)$", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, "CI_LINT_ARGS is gone from scripts/check_linux_build.sh"
    return shlex.split(match.group(1))


def test_ci_runs_the_gate_that_runs_the_script() -> None:
    """CI execs `tools/gate.sh --full` (CI.PUBLIC2): the script's flags are CI's, by construction."""
    assert "run: ./tools/gate.sh --full" in WORKFLOW.read_text(encoding="utf-8")


def test_ci_lint_denies_warnings() -> None:
    """The lint is only worth running while it actually denies warnings."""
    args = _script_lint_args()
    assert args[-3:] == ["--", "-D", "warnings"]
    assert "--all-targets" in args
