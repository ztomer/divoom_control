"""The Python coverage floor means the number it advertises (R71 P0.4).

**The defect this pins.** `scripts/py_ci.sh` advertised a 90% floor. coverage.py
compares `round(total, precision) < fail_under` with precision defaulting to 0,
so a total of 89.50 rounded up to 90 and passed. Measured coverage on a clean
tree was exactly 89.50% -- the gate had been green on a 0.01-point margin
against a floor it claimed was a full point higher, and the R70 changelog line
"coverage 89% -> 90%, floor raised to match" described a threshold nothing ever
enforced.

That is the same shape as the finding that created R71 P0 (a hook that ran four
checks while appearing to run eighteen): a gate believed to be stricter than it
is. Neither was caught by a test, because both were green -- and a gate's
green tells you nothing about what it would have refused.

**What these tests do NOT do.** They do not run the suite or measure coverage;
that is `py_ci.sh`'s job and it takes ~7.5 minutes. They pin the *configuration*
and the *comparison semantics*, which is where the lie lived.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PY_CI = REPO / "scripts" / "py_ci.sh"

should_fail_under = pytest.importorskip("coverage.results").should_fail_under


def _py_ci_text() -> str:
    return PY_CI.read_text()


def _setting(name: str) -> str:
    """Pull a shell scalar assignment out of py_ci.sh."""
    m = re.search(rf'^{name}="?\$?\{{?[A-Z_]*:?-?([0-9.]+)\}}?"?$', _py_ci_text(), re.M)
    assert m, f"could not find {name} in {PY_CI}"
    return m.group(1)


def test_floor_and_precision_are_both_set():
    """A floor without an explicit precision is a floor that rounds."""
    floor = float(_setting("COV_MIN"))
    precision = int(_setting("COV_PRECISION"))
    assert 0 < floor <= 100, floor
    assert precision >= 2, (
        f"precision {precision} lets the floor round up to itself; the whole "
        "defect was precision 0 turning 89.50 into a passing 90"
    )


def test_precision_is_actually_passed_to_pytest():
    """Setting a variable nothing reads is the failure-path-no-op shape.

    COV_PRECISION could sit in the file looking authoritative while the pytest
    invocation ignores it and silently uses precision 0 again.
    """
    text = _py_ci_text()
    assert "--cov-precision" in text, "COV_PRECISION is set but never passed to pytest"
    assert '--cov-precision="$COV_PRECISION"' in text, (
        "--cov-precision is present but not wired to COV_PRECISION"
    )
    assert '--cov-fail-under="$COV_MIN"' in text


def test_the_advertised_floor_is_the_enforced_floor():
    """A total just under the advertised number must FAIL.

    Under the old config (floor 90, precision 0) this was false for the whole
    half-point band [89.5, 90). That band is the bug.
    """
    floor = float(_setting("COV_MIN"))
    precision = int(_setting("COV_PRECISION"))

    # Comfortably under the floor: must fail.
    assert should_fail_under(floor - 0.5, floor, precision)
    # Exactly at the floor: must pass.
    assert not should_fail_under(floor, floor, precision)
    # A tenth under: must fail. This is the assertion the old config flunked.
    assert should_fail_under(floor - 0.1, floor, precision), (
        f"a total of {floor - 0.1} passes a floor of {floor} -- the floor is "
        "still rounding its way to green"
    )


def test_old_configuration_would_fail_this_suite():
    """Calibration: prove these tests can tell the two configs apart.

    If this passes with the OLD numbers too, the tests above are decoration.
    """
    old_floor, old_precision = 90.0, 0
    assert not should_fail_under(89.50, old_floor, old_precision), (
        "the historical defect no longer reproduces, so these tests are no "
        "longer pinning what they claim to pin"
    )
    # ...and the current config does not have that hole.
    floor = float(_setting("COV_MIN"))
    precision = int(_setting("COV_PRECISION"))
    assert should_fail_under(89.49, floor, precision) or floor <= 89.49


def test_floor_is_not_quietly_lowered_to_nothing():
    """A ratchet that can be set to 0 is not a ratchet.

    Guards the lazy fix for a red floor: dropping it rather than earning it.
    """
    assert float(_setting("COV_MIN")) >= 85.0, (
        "the Python coverage floor has been lowered below 85%; if that was "
        "deliberate, say the number out loud in the CHANGELOG and move this "
        "bound with it"
    )
