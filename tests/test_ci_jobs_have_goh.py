"""Every CI job that runs the Python suite has gates_of_heck, and says where.

Three tests in `test_linux_all_features_runtime.py` source goh's
`lib/container_runtime.sh`. CI's `test` job ran `pytest` with no goh checkout,
so the script looked for `$HOME/Projects/gates_of_heck` -- a developer's path
-- and the job was red on all three (2026-11-01). Other goh-dependent tests
(`test_repo_gates.py`) skip when goh is absent, so the same hole also hid them
from CI. The class: a job that runs a suite needing goh, with no goh in it.
"""

from __future__ import annotations

import pathlib
import re

import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"


# `tools/gate.sh --full` runs the suite too (GOH_CI_STEPS), and is the one command CI runs.
_PYTEST = re.compile(r"(?m)(python3? -m pytest|^\s*pytest|tools/gate\.sh --full)\b")


def _runs_pytest(step: dict) -> bool:
    return bool(_PYTEST.search(str(step.get("run", ""))))


def _goh_checkout_index(steps: list[dict]) -> int | None:
    for i, step in enumerate(steps):
        uses = str(step.get("uses", ""))
        repo = (step.get("with") or {}).get("repository", "")
        if uses.startswith("actions/checkout") and repo.endswith("/gates_of_heck"):
            return i
    return None


def test_every_pytest_job_checks_out_goh_first_and_names_it():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    seen = 0
    bad = []
    for name, job in jobs.items():
        steps = job.get("steps", [])
        for i, step in enumerate(steps):
            if not _runs_pytest(step):
                continue
            seen += 1
            at = _goh_checkout_index(steps)
            if at is None or at > i:
                bad.append(f"{name}: '{step.get('name')}' runs before any goh checkout")
                continue
            path = (steps[at].get("with") or {}).get("path", "")
            env = {**(job.get("env") or {}), **(step.get("env") or {})}
            if path not in str(env.get("GOH_DIR", "")):
                bad.append(f"{name}: '{step.get('name')}' does not set GOH_DIR to the checkout")
    assert seen, "no job runs pytest: the scan is looking at the wrong file"
    assert not bad, "\n".join(bad)
