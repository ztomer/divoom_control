"""Each panel's hot-channel verdict, as the daemon recorded it (U.5).

The daemon writes ONE record per panel -- every path that updates a panel's
hot art writes it, failures included: the Update Hot Channel button, Sync Now
and the daily schedule (``divoomd/src/hot_verdict.rs``). It lives in
``~/.config/divoom-control/hotchannel_state.json`` under ``panels``::

    {"panels": {"<panel id>": {"at": 1793468518, "by": "schedule",
                               "outcome": "failed", "error": "could not connect",
                               "offered": 5, "fetched": 0, "delivered": 0}}}

The GUI only READS it; ``hot_verdict.js`` turns an entry into the words.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

def _state_path() -> Path:
    # Honour HOME as read now (tests move it), not as read at import.
    override = os.environ.get("DIVOOM_HOT_VERDICTS")
    if override:
        return Path(override)
    return Path.home() / ".config" / "divoom-control" / "hotchannel_state.json"


def all_verdicts() -> dict:
    """Every panel's verdict, ``{panel id: entry}`` (never raises)."""
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    panels = data.get("panels") if isinstance(data, dict) else None
    if not isinstance(panels, dict):
        return {}
    return {k: v for k, v in panels.items() if isinstance(v, dict)}


def get(address: str) -> dict:
    """The verdict for the panel ``address`` names, matched without regard to
    letter case as the daemon keys it, or ``{}`` when it has none."""
    if not address:
        return {}
    panels = all_verdicts()
    if address in panels:
        return panels[address]
    low = address.lower()
    return next((v for k, v in panels.items() if k.lower() == low), {})
