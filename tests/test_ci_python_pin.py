"""P1.10: CI and the local gate read the Python version from one committed source.

Both jobs used to pin `python-version: "3.14"` by hand while the house (and the
local gate) run 3.15, so CI tested a different interpreter than the one the
code actually runs on. The version now lives in one committed file
(`.python-version`) that both CI jobs and the local gate read.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"
VERSION_FILE = REPO / ".python-version"


def test_committed_python_version_file_exists():
    assert VERSION_FILE.is_file(), ".python-version is missing"
    text = VERSION_FILE.read_text().strip()
    assert text, ".python-version is empty"
    # a concrete major.minor, not a range
    assert re.fullmatch(r"\d+\.\d+", text), f"bad version: {text!r}"


def test_workflow_reads_version_from_the_committed_file():
    text = WORKFLOW.read_text()
    assert "python-version-file: .python-version" in text, (
        "CI must read the version from .python-version, not a hand-kept literal"
    )
    # no hand-kept 3.14 literal in a setup-python block
    assert 'python-version: "3.14"' not in text, "stale hand-kept 3.14 pin remains"


def test_local_gate_reads_the_same_source():
    text = (REPO / "scripts" / "py_ci.sh").read_text()
    assert ".python-version" in text, "py_ci.sh must read .python-version"
