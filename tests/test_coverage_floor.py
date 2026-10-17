"""P1.4: the Python coverage floor tracks the last measurement.

`scripts/py_ci.sh` enforced 88.5 (lowered in v0.35.4 at a measured 88.74) and
never ratcheted back, so a floor that only moves down stops protecting
anything. The floor now equals the last measurement rounded down to 0.1, and
the script records when and at what value it was last measured, so a quiet move
is visible in the diff.
"""

import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "py_ci.sh"


def _floor_down(value: float, step: float = 0.1) -> float:
    return math.floor(round(value / step, 9)) * step


def test_coverage_floor_matches_last_measurement():
    text = SCRIPT.read_text()
    cov_min_match = re.search(r'COV_MIN="\$\{DIVOOM_PY_COV_MIN:-([\d.]+)\}"', text)
    assert cov_min_match, "COV_MIN default is missing or unparseable"
    floor = float(cov_min_match.group(1))

    measured_match = re.search(r"COV_LAST_MEASURED:\s*([\d.]+)\s+on\s+(\d{4}-\d{2}-\d{2})", text)
    assert measured_match, "script must record 'COV_LAST_MEASURED: <value> on <date>'"
    measured = float(measured_match.group(1))

    expected = _floor_down(measured, 0.1)
    assert floor == expected, (
        f"COV_MIN {floor} != floor({measured}, 0.1) = {expected}; "
        "ratchet the floor to the measurement or re-measure and update the record"
    )
