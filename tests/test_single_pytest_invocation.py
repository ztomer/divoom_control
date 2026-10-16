"""P1.5: `tests/` and `examples/tests/` collect in ONE invocation.

`examples/tests/conftest.py` re-exports `tests/conftest.py` with a star import so
the legacy suite shares the opt-in flags and fixtures "imported, not copied".
That also re-exported `pytest_addoption`, so a run naming both directories loaded
the hook twice and pytest aborted before collecting a single test:

    ValueError: option names {'--run-hardware'} already added

CI runs the two directories separately (`scripts/py_ci.sh`), so only a person
running both hit it -- and the error named the OPTION, not the cause. The
registration is now idempotent, and this test is the contract.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_tests_and_examples_tests_collect_in_one_invocation():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "examples/tests",
         "--collect-only", "-q"],
        cwd=REPO,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert proc.returncode == 0, (
        "collecting tests/ and examples/tests/ together failed:\n"
        + proc.stdout[-2000:]
        + proc.stderr[-2000:]
    )
