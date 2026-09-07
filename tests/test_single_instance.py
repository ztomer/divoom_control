"""Coverage for divoom_gui/single_instance.py.

Two defects are pinned here, both from the 2026-09-07 crash investigation:

  1. The focus path addressed the incumbent by LaunchServices NAME
     (`tell application "Python" to activate`), which launched TeX Live
     Utility's embedded Python 3.9.10 bundle -- app-translocated into $TMPDIR,
     dead in dyld, one crash report per attempt.
  2. The lock file was opened `"w"`, which truncates BEFORE flock decides
     anything, so the losing process erased the incumbent's pid on its way out.
     Nothing noticed, because nothing read the pid back yet. Fixing (1) without
     (2) would have produced a focus path that silently never focused.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_gui import single_instance  # noqa: E402


@pytest.fixture
def lockdir(tmp_path, monkeypatch):
    import tempfile as real_tempfile
    monkeypatch.setattr(real_tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(single_instance, "_GUI_LOCK_FH", None)
    return tmp_path


# ------------------------------------------------------------------ the lock

def test_lock_records_our_pid(lockdir):
    assert single_instance.ensure_single_instance() is True
    assert single_instance.running_gui_pid() == os.getpid()


def test_a_losing_contender_does_not_erase_the_incumbent_pid(lockdir):
    """Defect (2): `open(path, "w")` truncated before flock could refuse."""
    assert single_instance.ensure_single_instance() is True
    incumbent = single_instance.running_gui_pid()
    assert incumbent == os.getpid()

    # A second process would find the lock held. Simulate exactly that: the
    # contender opens the same path and is refused by flock.
    import fcntl as real_fcntl
    calls = []

    def refuse(fd, flags):
        calls.append(flags)
        raise BlockingIOError("already locked")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(real_fcntl, "flock", refuse)
        mp.setattr(single_instance, "_GUI_LOCK_FH", None)
        assert single_instance.ensure_single_instance() is False

    assert calls, "the contender must actually have tried to lock"
    assert single_instance.running_gui_pid() == incumbent, \
        "the loser truncated the lock file and lost the incumbent's pid"


def test_running_gui_pid_is_none_when_absent_or_junk(lockdir):
    assert single_instance.running_gui_pid() is None          # no file at all
    Path(single_instance.lock_path()).write_text("not-a-pid")
    assert single_instance.running_gui_pid() is None


# ----------------------------------------------------------------- the focus

def test_focus_addresses_the_pid_and_never_an_app_name(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: seen.append(a[0]) or None)

    single_instance.focus_running_gui(4242)

    assert len(seen) == 1
    argv = seen[0]
    assert argv[0] == "osascript"
    script = argv[2]
    assert "System Events" in script
    assert "unix id is 4242" in script
    # The defect, pinned as the CLASS rather than as the one name that bit us:
    # no application may be addressed by name except the faceless System Events
    # bridge, since a name is resolved by LaunchServices and can start anything.
    assert not re.search(r'application\s+(?:id\s+)?"(?!System Events")', script), script


def test_focus_without_a_pid_runs_nothing(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: pytest.fail("must not shell out without a pid"))
    single_instance.focus_running_gui(None)


def test_focus_swallows_a_failing_osascript(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("no osascript")))
    single_instance.focus_running_gui(4242)  # must not raise
