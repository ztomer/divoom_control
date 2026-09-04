"""Regression tests for tools/repo_gates.sh — layer 3 of the pre-push gate.

**What these pin, and why it is worth pinning.** Until R71 P0.1,
`tools/gate.sh --full` ran `structural.sh` and nothing else: four checks
(emoji, conflict markers, file length, disk hygiene). The rust and python
layers were commented out, so `pre-push` ran no clippy, no tests, neither
coverage floor, and none of the nine `tools/check_*.py` gates — the 17-step
list in `.gatesrc` executed only when a human typed `./scripts/ci_local.sh`.

That hole was invisible because *nothing failed*. A gate that is not wired in
reports nothing at all, which from the outside is indistinguishable from a gate
that is wired in and passing. So the wiring itself needs a test, or it can be
un-commented back out and no suite would notice.

**The wiring test uses the recursion guard as its probe.** Running
`gate.sh --full` for real means running the whole CI, which is not something a
unit test can do. But presetting `DIVOOM_IN_REPO_GATES` makes `repo_gates.sh`
abort immediately with exit 2 — so if `gate.sh --full` reaches it, we see that
exact failure in milliseconds, and if the layer-3 line is ever deleted the test
goes green-path and fails the assertion. One mechanism, two properties.

Both directions are pinned throughout: `--staged` must NOT reach layer 3 (the
pre-commit hook stays deliberately narrow), and fast mode must both announce
what it skipped and actually skip it.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
REPO_GATES = REPO / "tools" / "repo_gates.sh"
GATE = REPO / "tools" / "gate.sh"

# The gate scripts shell out to gates_of_heck for the TUI and the structural
# layer. Where it is absent (a bare CI image), these tests have nothing to
# describe -- skip honestly rather than assert on a broken environment.
GOH = Path(os.environ.get("GOH_DIR", Path.home() / "Projects" / "gates_of_heck"))
requires_goh = pytest.mark.skipif(
    not (GOH / "tui" / "lib.sh").is_file(),
    reason=f"gates_of_heck not present at {GOH}",
)


def _run(script: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.pop("DIVOOM_GATE_FAST", None)
    e.pop("DIVOOM_IN_REPO_GATES", None)
    e.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=REPO, env=e, capture_output=True, text=True, timeout=120,
    )


def test_repo_gates_is_executable_and_parses():
    """A layer that cannot execute is a layer that silently does nothing."""
    assert REPO_GATES.is_file(), "tools/repo_gates.sh is missing"
    assert os.access(REPO_GATES, os.X_OK), "tools/repo_gates.sh is not executable"
    r = subprocess.run(["bash", "-n", str(REPO_GATES)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@requires_goh
def test_recursion_guard_fires():
    """Re-entry aborts loudly instead of fork-bombing the push."""
    r = _run(REPO_GATES, "--dry-run", DIVOOM_IN_REPO_GATES="1")
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}\n{r.stdout}{r.stderr}"
    assert "re-entered" in (r.stdout + r.stderr)


@requires_goh
def test_gate_full_reaches_layer_three():
    """THE wiring test. If `--full` stops at structural.sh again, this fails.

    The guard is preset, so reaching repo_gates.sh costs milliseconds instead
    of a full CI run — and its exit 2 is proof of arrival that a green run
    could not give us (a green `--full` looks identical whether layer 3 ran or
    was commented out, which is exactly how the hole survived).
    """
    r = _run(GATE, "--full", DIVOOM_IN_REPO_GATES="1")
    combined = r.stdout + r.stderr
    assert "re-entered" in combined, (
        "tools/gate.sh --full did not reach tools/repo_gates.sh — layer 3 is "
        f"not wired.\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )
    assert r.returncode != 0


@requires_goh
def test_gate_staged_does_not_reach_layer_three():
    """Pre-commit stays narrow: staged scope must not run the whole CI."""
    r = _run(GATE, "--staged", DIVOOM_IN_REPO_GATES="1")
    assert "re-entered" not in (r.stdout + r.stderr), (
        "tools/gate.sh --staged reached layer 3; the pre-commit hook is "
        "supposed to be the fast, staged-only scope"
    )


@requires_goh
def test_default_run_includes_the_python_suite():
    """The baseline the fast-mode test is a delta against."""
    r = _run(REPO_GATES, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "py_ci.sh" in r.stdout, r.stdout


@requires_goh
def test_fast_mode_announces_and_actually_skips():
    """Honest placeholder: the skip is SAID, not merely done.

    Both halves matter. An announcement without the skip is a lie in the other
    direction, and a skip without the announcement is the silent fast path this
    whole layer exists to prevent.
    """
    r = _run(REPO_GATES, "--dry-run", DIVOOM_GATE_FAST="1")
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "SKIPPING" in combined, f"fast mode did not announce itself:\n{combined}"
    assert "py_ci.sh" not in r.stdout, (
        "fast mode announced a skip it did not perform:\n" + r.stdout
    )


@requires_goh
def test_no_env_var_can_skip_the_gate_entirely():
    """There is no silent full-bypass variable, and there should not be.

    `git push --no-verify` is the bypass, and its virtue is that the person
    typing it knows they bypassed. This pins the absence of a quieter one:
    guessable names must not turn the gate into a no-op.
    """
    baseline = _run(REPO_GATES, "--dry-run").stdout
    steps = re.search(r"(\d+) step\(s\)", baseline)
    assert steps, f"could not read the step count:\n{baseline}"

    for name in ("DIVOOM_GATE_SKIP", "DIVOOM_SKIP_GATE", "SKIP_GATE", "NO_GATE"):
        r = _run(REPO_GATES, "--dry-run", **{name: "1"})
        assert f"{steps.group(1)} step(s)" in r.stdout, (
            f"{name}=1 changed the step list; a silent full-bypass variable is "
            f"exactly the hole R71 P0 closed.\n{r.stdout}")
