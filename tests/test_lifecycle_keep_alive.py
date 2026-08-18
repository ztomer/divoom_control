"""R40 §9 — daemon (menu bar) keep-alive lifecycle.

Covers: the persisted flag, the pure decision helpers, and the menubar client
routing a shutdown event to its callback. All event-driven — no polling
anywhere in the path.

The daemon's-own shutdown-broadcast test (which spins up a real archived
divoom_daemon.daemon.DivoomDaemon) moved to
archive/tests/ (removed in R66; in git history) test_lifecycle_keep_alive.py.
"""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import lifecycle_config as lc
from divoom_daemon.daemon_protocol import EVENT_SHUTDOWN


# ── flag persistence ──────────────────────────────────────────────────────

def test_flag_defaults_false_and_roundtrips(tmp_path):
    p = tmp_path / "config.ini"
    assert lc.get_keep_daemon_alive(p) is False          # default
    assert lc.set_keep_daemon_alive(True, p) is True
    assert lc.get_keep_daemon_alive(p) is True
    assert lc.set_keep_daemon_alive(False, p) is True
    assert lc.get_keep_daemon_alive(p) is False


def test_flag_read_tolerates_missing_and_garbage(tmp_path):
    assert lc.get_keep_daemon_alive(tmp_path / "nope.ini") is False
    bad = tmp_path / "bad.ini"
    bad.write_text("[gui]\nkeep_daemon_alive = not-a-bool\n")
    assert lc.get_keep_daemon_alive(bad) is False
    # preserves an existing unrelated section
    other = tmp_path / "o.ini"
    other.write_text("[gui]\ntimeout = 9\n")
    lc.set_keep_daemon_alive(True, other)
    import configparser
    c = configparser.ConfigParser(); c.read(other)
    assert c.get("gui", "timeout") == "9"
    assert c.getboolean("gui", "keep_daemon_alive") is True


# ── pure decision helpers (shared lifecycle ↔ NOT keep-alive) ──────────────

@pytest.mark.parametrize("keep,expect", [(False, True), (True, False)])
def test_decision_helpers(keep, expect):
    assert lc.should_follow_daemon_shutdown(keep) is expect
    assert lc.should_stop_daemon_on_dashboard_quit(keep) is expect
    assert lc.should_stop_daemon_on_menubar_quit(keep) is expect


# ── quit_menubar_on_exit flag + its decision helper ────────────────────────

def test_quit_menubar_flag_defaults_true_and_roundtrips(tmp_path):
    p = tmp_path / "config.ini"
    assert lc.get_quit_menubar_on_exit(p) is True           # default
    assert lc.set_quit_menubar_on_exit(False, p) is True
    assert lc.get_quit_menubar_on_exit(p) is False
    assert lc.set_quit_menubar_on_exit(True, p) is True
    assert lc.get_quit_menubar_on_exit(p) is True


def test_quit_menubar_read_tolerates_missing_and_garbage(tmp_path):
    assert lc.get_quit_menubar_on_exit(tmp_path / "nope.ini") is True
    bad = tmp_path / "bad.ini"
    bad.write_text("[gui]\nquit_menubar_on_exit = not-a-bool\n")
    assert lc.get_quit_menubar_on_exit(bad) is True
    # the two lifecycle flags coexist in the same section without clobbering
    both = tmp_path / "both.ini"
    lc.set_keep_daemon_alive(True, both)
    lc.set_quit_menubar_on_exit(False, both)
    assert lc.get_keep_daemon_alive(both) is True
    assert lc.get_quit_menubar_on_exit(both) is False


@pytest.mark.parametrize("keep,quit_mb,expect", [
    (False, True, True),    # shared lifecycle + opted in → terminate menu bar
    (False, False, False),  # shared but user keeps the tray → leave it
    (True, True, False),    # keep-alive (independent) → never terminate
    (True, False, False),
])
def test_should_quit_menubar_on_exit(keep, quit_mb, expect):
    assert lc.should_quit_menubar_on_exit(keep, quit_mb) is expect

# The three menubar-client lifecycle tests that lived here (shutdown dispatch,
# follow-on-dropped-subscription, resubscribe-on-transient-drop) exercised the
# removed pyobjc menubar. Their behaviour now lives in the native Rust agent and
# is pinned by divoom-menubar/src/resubscribe.rs (R53.39 guard) and
# daemon.rs -- see R66 Phase 1.
