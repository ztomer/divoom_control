"""No kill-by-name exemption is left `unreviewed` (queue D.KBNA).

`kill_by_name_allow.json` was seeded with the survivors of the first scan, each
honestly `unreviewed`. Every one has since been replaced by a kill of a process
the script owns (an identity file, the holder of the app's lock or socket, a pid
recorded at launch). An entry that stays must be a decision: `legitimate`, with
the reason written down.
"""

import json
from pathlib import Path

ALLOW = Path(__file__).resolve().parents[1] / "kill_by_name_allow.json"


def test_every_entry_is_a_recorded_decision():
    entries = json.loads(ALLOW.read_text())["entries"]
    undecided = [e for e in entries if e.get("status") != "legitimate" or len(e.get("reason", "")) < 20]
    assert undecided == [], f"unreviewed or unexplained kill-by-name entries: {undecided}"


def test_the_gatesrc_comment_does_not_carry_a_count():
    """A hard-coded count drifts the moment an entry goes; the file is the count."""
    import re

    text = (ALLOW.parent / ".gatesrc").read_text()
    assert not re.search(r"\(\d+ entries", text)
