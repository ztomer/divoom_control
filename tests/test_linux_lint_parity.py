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


def _ci_no_ble_lint() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"- name: Lint core without BLE\n\s+run: (cargo clippy .+)", text)
    assert match, "rust-core's 'Lint core without BLE' step is gone; re-point this test"
    return shlex.split(match.group(1))[2:]  # drop `cargo clippy`


def _script_lint_args() -> list[str]:
    match = re.search(r"^CI_LINT_ARGS=\((.+)\)$", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, "CI_LINT_ARGS is gone from scripts/check_linux_build.sh"
    return shlex.split(match.group(1))


def test_linux_cross_lint_uses_ci_flags_exactly() -> None:
    assert _script_lint_args() == _ci_no_ble_lint()


def test_ci_lint_denies_warnings() -> None:
    """The parity above is only worth having while CI's lint actually denies warnings."""
    args = _ci_no_ble_lint()
    assert args[-3:] == ["--", "-D", "warnings"]
    assert "--all-targets" in args
