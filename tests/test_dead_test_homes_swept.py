"""A SIGKILLed run's fake HOME is removed by the next session start.

Queue D.KBNA: ``tests/conftest.py`` makes a ``divoom-test-home-*`` directory per
session and only an ``atexit`` rmtree removed it, so a run that was SIGKILLed
(a deadline killing the tree, an OOM) left its home in TMPDIR for good -- ten of
them on 2026-11-02. The session now claims its home (an owner file: pid + start
time) and ``browser_reaper.sweep_dead_homes`` removes the homes whose owner is
dead and which no live process holds.

Teeth: make ``owner_alive`` return True always, or drop the
``sweep_dead_homes()`` call from ``pytest_sessionstart``, and the cases below go
red (the dead home stays); make it ignore ``held_by_process`` and
``test_a_home_a_live_process_holds_is_kept`` goes red.
"""

from __future__ import annotations

import os
import subprocess
import time

from tests.support import browser_reaper as R


def _home(tmp_path, name="divoom-test-home-x1"):
    home = tmp_path / name
    home.mkdir()
    (home / "marker").write_text("x")
    return home


def _dead_pid():
    proc = subprocess.Popen(["/usr/bin/true"], stdin=subprocess.DEVNULL)
    proc.wait()
    return proc.pid


def test_the_session_claims_its_home():
    home = R.active_home()
    assert home, "run inside the isolated test session"
    assert R.owner_alive(home) is True


def test_a_home_whose_owner_is_dead_is_removed(tmp_path):
    home = _home(tmp_path)
    sleeper = subprocess.Popen(["/bin/sleep", "60"], stdin=subprocess.DEVNULL)
    try:
        R.claim_home(str(home), sleeper.pid)
        assert R.owner_alive(str(home)) is True
        assert R.sweep_dead_homes(str(tmp_path)) == 0, "a live owner's home must stay"
        assert home.exists()
    finally:
        sleeper.kill()
        sleeper.wait()
    assert R.owner_alive(str(home)) is False
    assert R.sweep_dead_homes(str(tmp_path)) == 1
    assert not home.exists()


def test_a_recycled_pid_does_not_keep_a_dead_home(tmp_path):
    """The owner's pid is alive but started at another moment: not the owner."""
    home = _home(tmp_path)
    R.claim_home(str(home), os.getpid())
    (home / R.OWNER_FILE).write_text(f"{os.getpid()}\nMon Jan  1 00:00:00 1990\n")
    assert R.owner_alive(str(home)) is False
    assert R.sweep_dead_homes(str(tmp_path)) == 1
    assert not home.exists()


def test_a_home_a_live_process_holds_is_kept(tmp_path):
    home = _home(tmp_path)
    R.claim_home(str(home), _dead_pid())
    holder = subprocess.Popen(["/bin/sleep", "60"], cwd=home, stdin=subprocess.DEVNULL)
    try:
        time.sleep(0.2)
        assert R.sweep_dead_homes(str(tmp_path)) == 0
        assert home.exists(), "a process with its cwd in the home holds it"
    finally:
        holder.kill()
        holder.wait()
    assert R.sweep_dead_homes(str(tmp_path)) == 1


def test_a_home_with_no_owner_waits_out_the_legacy_age(tmp_path):
    home = _home(tmp_path)
    assert R.owner_alive(str(home)) is None
    assert R.sweep_dead_homes(str(tmp_path)) == 0, "a fresh unowned home may be mid-creation"
    assert home.exists()
    old = time.time() + R.LEGACY_HOME_AGE_S + 60
    assert R.dead_homes(str(tmp_path), now=old) == [str(home)]


def test_only_test_homes_are_candidates(tmp_path):
    other = tmp_path / "somebody-elses-dir"
    other.mkdir()
    link_target = _home(tmp_path, "keep-me")
    link = tmp_path / "divoom-test-home-link"
    link.symlink_to(link_target)
    R.claim_home(str(other), _dead_pid())
    assert R.sweep_dead_homes(str(tmp_path)) == 0
    assert other.exists() and link.is_symlink() and link_target.exists()


def test_the_symlinks_inside_a_home_are_not_followed(tmp_path):
    """The real home's caches are linked into every fake one: removing the fake
    home must remove the link, never the cache."""
    cache = tmp_path / "real-cache"
    cache.mkdir()
    (cache / "precious").write_text("x")
    home = _home(tmp_path)
    (home / "cache").symlink_to(cache)
    R.claim_home(str(home), _dead_pid())
    assert R.sweep_dead_homes(str(tmp_path)) == 1
    assert (cache / "precious").read_text() == "x"


def test_the_session_start_sweeps_dead_homes(tmp_path, monkeypatch):
    """The wiring: the hook the next session runs at its start does it."""
    import types

    dead = _home(tmp_path, "divoom-test-home-dead")
    R.claim_home(str(dead), _dead_pid())
    live = _home(tmp_path, "divoom-test-home-live")
    R.claim_home(str(live))
    monkeypatch.setattr(R.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(R, "sweep_orphans", lambda: 0)  # not the real process table's
    controller = types.SimpleNamespace(config=types.SimpleNamespace())
    R.ReaperPlugin().pytest_sessionstart(controller)
    assert not dead.exists()
    assert live.exists()
    worker = types.SimpleNamespace(config=types.SimpleNamespace(workerinput={}))
    again = _home(tmp_path, "divoom-test-home-dead2")
    R.claim_home(str(again), _dead_pid())
    R.ReaperPlugin().pytest_sessionstart(worker)
    assert again.exists(), "an xdist worker must not sweep: the controller does"
