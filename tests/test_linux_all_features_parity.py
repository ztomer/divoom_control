"""CI's Linux `--all-features` clippy runs in the LOCAL gate too, with the same flags.

CI's `rust-core` job is the only thing that has ever compiled the daemon's
Linux BLE backend (`ble` -> btleplug -> bluer -> dbus -> libdbus-sys) with the
feature ON:

    cargo clippy -p divoomd --all-targets --all-features -- -D warnings

`scripts/check_linux_build.sh` covers the NO-BLE half (the `ble` feature needs
the system dbus-1.pc, which zig cannot supply), so the `--all-features` half
ran in CI and nowhere else: a Linux-only clippy finding was invisible until a
push went red on the runner. The `.gatesrc` comment named the gap and left it
as a note.

This pins the local script's clippy line to CI's, flag for flag, the way
tests/test_linux_lint_parity.py pins the no-BLE half -- so the two cannot
drift apart again, and so a local green means something about CI's Linux lint.

The command is READ OUT of the workflow rather than copied here: a copy is a
second place to update, and the day someone adds `--all-features` to CI and
forgets the local script, this test is the thing that notices.
"""

from __future__ import annotations

import pathlib
import re
import shlex

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
SCRIPT = ROOT / "scripts" / "check_linux_all_features.sh"


def _ci_all_features_lint() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    # The step's `run:` line is not adjacent to its `name:` (comments sit
    # between them), so the search spans the comment lines too.
    match = re.search(
        r"- name: cargo clippy \(divoomd, all targets/features, deny warnings\)\n"
        r"(?:\s*#.*\n)*"
        r"\s*run: (cargo clippy .+)",
        text,
    )
    assert match, "rust-core's all-features clippy step is gone; re-point this test"
    return shlex.split(match.group(1))[2:]  # drop `cargo clippy`


def _script_clippy_args() -> list[str]:
    match = re.search(
        r"^CI_CLIPPY_ARGS=\((.+)\)$", SCRIPT.read_text(encoding="utf-8"), re.M
    )
    assert match, "CI_CLIPPY_ARGS is gone from scripts/check_linux_all_features.sh"
    return shlex.split(match.group(1))


def test_local_linux_lint_uses_ci_flags_exactly() -> None:
    assert _script_clippy_args() == _ci_all_features_lint()


def test_ci_lint_denies_warnings_and_covers_the_ble_feature() -> None:
    """The parity above only means something while the flags are the strict ones.

    `--all-features` is the whole point (it is what turns the `ble` feature on,
    and the `ble` feature is what pulls the Linux-only dbus stack in), and
    `-D warnings` is what makes a Linux-only WARNING red -- the class that
    shipped to CI 19 times out of 20 while the local gate stayed green.
    """
    args = _ci_all_features_lint()
    assert "--all-features" in args
    assert "--all-targets" in args
    assert args[-3:] == ["--", "-D", "warnings"]
    assert args[:2] == ["-p", "divoomd"]


def test_the_lint_runs_in_the_local_gate() -> None:
    """The script must be a GOH_CI_STEPS step, or it is a gate nobody runs.

    A gate that exists but is not in the local step list is the exact shape
    the house rule #3 rejects: it runs when somebody remembers.
    """
    gatesrc = (ROOT / ".gatesrc").read_text(encoding="utf-8")
    assert "scripts/check_linux_all_features.sh" in gatesrc, (
        "the Linux --all-features lint is not in GOH_CI_STEPS"
    )
