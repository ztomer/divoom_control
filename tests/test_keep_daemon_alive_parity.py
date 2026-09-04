"""`[gui] keep_daemon_alive` is parsed in two languages — they must agree.

**R72 P3.3.** Auditing the Rust menubar against the round's invariant found it
otherwise clean: `daemon.rs` is a lean socket client, and its dependency list
(`tray-icon`, `tao`, `serde_json`, one CFRunLoop binding) contains no transport,
device, HTTP or image crate, so it *cannot* duplicate daemon work. The one thing
it does read for itself is this flag.

That makes **three** independent parsers of `config.ini`:

  GUI      `divoom_lib/lifecycle_config.py`, via `configparser.getboolean`
  daemon   `divoomd/src/cloud_store.rs`, hand-rolled, `[divoom]` only
  menubar  `divoom-menubar/src/launch.rs`, hand-rolled, `[gui]` only

They read different sections, so they do not fight over values. What they CAN
disagree about is what counts as true — and the consequence is concrete: the
GUI decides whether to leave the daemon running on exit, and the menubar decides
whether to kill it. Disagree, and the daemon either dies under a GUI that
expected it alive, or survives when the user asked for a clean shutdown.

They agree today. This pins that, the same way `check_hotchannel_parity.py`
pins the other shared file — written while the two still match, which is the
only cheap time to write it.
"""
from __future__ import annotations

import configparser
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCH_RS = REPO / "divoom-menubar" / "src" / "launch.rs"


def rust_true_words() -> set[str]:
    """The literals the menubar accepts as true, read from the match arm.

    Takes a WINDOW after `matches!(` rather than trying to balance parentheses:
    the first `)` belongs to `v.trim()`, so a lazy `\(.*?\)` captures nothing
    useful. The calibration test below is what caught that -- the first version
    of this parser returned an empty set and the comparison would have been
    between two empty-ish sets if configparser had ever changed.
    """
    src = LAUNCH_RS.read_text(encoding="utf-8")
    i = src.find("keep_daemon_alive")
    assert i != -1, "keep_daemon_alive not found in launch.rs"
    j = src.find("matches!(", i)
    assert j != -1, "the truthiness match! is gone from keep_daemon_alive"
    window = src[j:j + 400]
    return set(re.findall(r'"([a-z0-9]+)"', window))


def test_the_menubar_accepts_exactly_configparsers_true_words():
    rust = rust_true_words()
    python = {k for k, v in configparser.ConfigParser.BOOLEAN_STATES.items() if v}
    assert rust == python, (
        f"keep_daemon_alive truthiness diverged.\n"
        f"  menubar accepts: {sorted(rust)}\n"
        f"  configparser:    {sorted(python)}\n"
        f"The GUI decides whether to leave the daemon running; the menubar "
        f"decides whether to kill it. Disagreement means the daemon dies under "
        f"a GUI that expected it alive, or survives a requested shutdown.")


def test_the_scan_actually_finds_the_words():
    """Calibration: an empty parse would make the test above pass vacuously
    against an empty set only if configparser were empty too -- but a regex that
    silently matched nothing is still worth catching directly."""
    assert len(rust_true_words()) >= 4, rust_true_words()


def test_both_sides_default_to_false():
    """The safe default is SHARED lifecycle: the daemon goes when the GUI goes.

    A default that diverged would leak a daemon on every quit for one of the two
    readers, which is invisible until someone counts processes.
    """
    src = LAUNCH_RS.read_text(encoding="utf-8")
    assert "default false" in src.lower(), "menubar no longer documents the default"
    # The Rust returns false on a missing file, missing section and missing key.
    assert src.count("return false;") >= 2, src.count("return false;")

    from divoom_lib.lifecycle_config import DEFAULT

    assert DEFAULT is False, DEFAULT
