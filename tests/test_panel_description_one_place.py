"""One description of a panel, and one place that keeps it (P3.4).

The daemon knows what each panel is: its model, its size, its chassis, the
features the vendor app enables for that model, and the screens the app offers
it. Before this round the web UI kept a second answer for two of those --
the chassis family, decided from the model with its own regexes, and the
FM-radio and VJ-channel abilities, decided from the DEVICE NAME -- and the
CLI kept a third, a per-model capability table of its own.

Those derivations were not merely redundant: the name-based one was WRONG.
The app offers the FM radio to the Timebox and the Tiivoo 2 and to no other
panel, and the web UI offered it to every panel whose name contained "tivoo"
or "ditoo" -- the exact opposite. So the checks below are not "the code moved";
they are "the wrong answer cannot come back".

They read the sources, so they are cheap and they run without a browser; the
behaviour they guard is covered by the browser suite and by the daemon's own
tests (`divoomd/tests/panel_model_status.rs`).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "divoom_gui" / "web_ui"
PANEL_FACTS = WEB / "panel_facts.js"
CHANNELS = WEB / "channels_grids.js"
CONNECTION = WEB / "connection_events.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_web_ui_does_not_decide_the_chassis_from_the_model():
    """The chassis is the daemon's: which product the panel is, and how big."""
    src = _read(PANEL_FACTS)
    assert "chassisOf" not in src, "the web UI decides the chassis family again"
    assert "const CHASSIS" not in src, "the web UI keeps a chassis table of its own"
    assert "dev.chassis" in src, "the web UI does not read the daemon's chassis"


def test_the_web_ui_does_not_decide_a_panel_ability_from_its_name():
    """The FM radio and the VJ channel are per-panel facts, and the daemon's.

    The old rule read the device's NAME and matched "tivoo"/"ditoo" for the
    radio and "timebox"/"evo" for VJ. The app's own per-model statements say
    otherwise on both counts.
    """
    src = _read(CHANNELS)
    for guess in ("tivoo", "ditoo", "timebox", "evo"):
        assert not re.search(rf'includes\(\s*"{guess}"', src), (
            f"the web UI still decides a panel ability from a name containing {guess!r}"
        )
    assert 'feature("radio")' in src, "the FM card does not read the daemon's radio"
    assert 'feature("vj")' in src, "the VJ card does not read the daemon's vj"


def test_the_channel_cards_follow_the_panel_not_the_name():
    """The caller hands over the PANEL, so the cards can read its facts."""
    src = _read(CONNECTION)
    assert "updateChannelButtonsVisibility(name)" not in src, (
        "the channel cards are still told a device NAME"
    )
    assert "updateChannelButtonsVisibility(address)" in src, (
        "the channel cards are not told which panel they are about"
    )


def test_the_bridge_carries_the_whole_description():
    """What the GUI hands the web UI is the daemon's description, whole."""
    from divoom_gui.panels import PANEL_FIELDS

    for field in ("model", "width", "height", "chassis", "features", "screens"):
        assert field in PANEL_FIELDS, f"{field} is not carried to the web UI"


def test_the_cli_carries_no_capability_table():
    """The CLI reads the daemon's description; it keeps no table of its own."""
    src = _read(REPO / "divoom_lib" / "cli_device_verbs.py")
    assert "def _capabilities" not in src, "the CLI has a capability table of its own"
    assert "capabilities_for" not in src, "the CLI looks a model up in a table of its own"
    assert "device_status" in src, "the CLI does not ask the daemon what the panel is"


def test_the_python_table_is_the_daemons_and_not_a_second_answer():
    """The retired library's table is held to the daemon's, row by row.

    `tests/test_panel_features_parity.py` does the comparison; this is the
    floor: the columns that were wrong (the radio, the microphone, the alarm)
    must still be there to be compared.
    """
    from divoom_lib.models.capabilities import DEVICE_CAPABILITIES

    assert DEVICE_CAPABILITIES, "the retired table is empty"
    for field in ("has_fm", "has_mic", "has_alarm", "has_sd"):
        assert hasattr(DEVICE_CAPABILITIES["DITOO"], field), field
