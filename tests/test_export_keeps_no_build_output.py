"""P1.17: the pre-push export carries no file a gate step itself produces.

`.gatesrc` named `target/debug/divoomd` in `GOH_EXPORT_KEEP` so the eleven
tests that SPAWN the daemon could find one in the export. But goh's proven
cache keys every step on the kept files' bytes, and six steps (`cargo build` /
`cargo test` with and without `ble`, the coverage run) rewrite that binary, so
each one moved its own key while it ran and was never recorded as proven --
"the tree or the gates moved while the step ran", re-run on every push
(measured 2026-11-01; one tree gave three keys).

The class: a build output declared as an input. The fix is that the step that
needs the daemon builds it, as CI's Python job does right before its pytest,
instead of borrowing a binary another step happened to leave behind (and that a
proven, skipped step would not leave at all).
"""

from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _export_keep() -> list[str]:
    out = subprocess.run(
        ["bash", "-c", 'set -a; . "$1"; printf %s "${GOH_EXPORT_KEEP-}"', "_",
         str(ROOT / ".gatesrc")],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, check=True,
    )
    return out.stdout.split()


def test_the_export_keeps_no_build_output():
    built = [k for k in _export_keep() if k == "target" or k.startswith("target/")]
    assert not built, (
        f"GOH_EXPORT_KEEP carries a build output into the export: {built} -- a "
        "step that rebuilds it moves its own proven key (P1.17)")


def test_the_python_step_builds_the_daemon_its_tests_spawn():
    script = (ROOT / "scripts" / "py_ci.sh").read_text()
    code = "\n".join(line for line in script.splitlines()
                     if not line.lstrip().startswith("#"))
    build = re.search(r"(?m)^\s*cargo build -p divoomd --locked\s*$", code)
    pytest = re.search(r"python3 -m pytest", code)
    assert build, "scripts/py_ci.sh must build the daemon the spawning tests run"
    assert pytest and build.start() < pytest.start(), (
        "the daemon must be built BEFORE the suite that spawns it")
