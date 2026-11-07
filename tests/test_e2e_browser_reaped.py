"""No camoufox process outlives the test session that started it.

Queue D.CFXORPH: on 2026-11-01 eighteen camoufox processes this suite started
were found orphaned. Playwright starts the browser in its own process group,
so when its driver dies without closing it -- a run SIGKILLed, an xdist worker
killed mid-test -- nothing the test wrote can reach it.
``tests/support/browser_reaper.py`` makes the owner reap it; this holds it.

The browser cases run a REAL inner pytest session (with this repo's conftest
as its plugin, in a fresh fake HOME of its own) and look at the process table
after it, because "after the session" is the claim.

What the inner tests do to their browser is the leak path, and it is a
MODEL: the 2026-11-01 cause was not reproduced. Probed 2026-11-02, a healthy
camoufox exits within a second when its driver is SIGKILLed (its pipe
closes), and so do its content processes when the leader is -- Playwright
cleans a plain failure itself. What it cannot clean is a browser that cannot
see its pipe close: one wedged (here, SIGSTOPped -- under load-average-150
runs a browser can stop answering for minutes) when its driver dies. That
browser is re-parented to launchd and stays, which is the shape found.

Teeth: make ``register_launched`` register nothing and drop the session-end
sweep, and ``test_a_failing_test_leaves_no_browser`` goes red with the
browser still running; make ``pytest_sessionstart`` sweep nothing and
``test_a_killed_run_is_cleaned_at_the_next_session_start`` goes red.
"""

from __future__ import annotations

import os
import pwd
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.support import browser as B
from tests.support import browser_reaper as R

REPO = Path(__file__).resolve().parents[1]
HOME_A = "/var/folders/x/T/divoom-test-home-aaaa"
CAMOUFOX = "/Library/Caches/camoufox/browsers/official/1/Camoufox.app/Contents/MacOS/camoufox"
CHILD = "/Library/Caches/camoufox/browsers/official/1/Camoufox.app/Contents/MacOS/plugin-container"
UID = os.getuid()


def _row(pid, ppid, pgid, command, uid=UID):
    return R.Proc(pid, ppid, pgid, uid, command)


def _table(*rows):
    return list(rows)


# ── Which processes are a test's: pure, no browser ───────────────────────────


def test_a_browser_is_named_by_its_test_home_never_by_its_name():
    # The USER'S camoufox (the gemini-camoufox transport) runs from the real
    # cache. Same name, same binary: not ours, so never a candidate.
    users = _row(10, 1, 10, f"/Users/me{CAMOUFOX} -headless")
    ours = _row(11, 1, 11, f"{HOME_A}{CAMOUFOX} -headless")
    linux = _row(12, 1, 12, "/tmp/divoom-test-home-bbbb/.cache/camoufox/camoufox -headless")
    assert users.session_home is None
    assert ours.session_home == HOME_A
    assert linux.session_home == "/tmp/divoom-test-home-bbbb"
    assert R.orphans(_table(users, ours)) == [ours]


def test_a_browser_whose_driver_is_alive_belongs_to_a_live_session():
    driver = _row(20, 5, 5, "/x/node /x/cli.js run-driver")
    leader = _row(21, 20, 21, f"{HOME_A}{CAMOUFOX} -no-remote")
    child = _row(22, 21, 21, f"{HOME_A}{CHILD} -isForBrowser")
    assert R.orphans(_table(driver, leader, child)) == []


def test_a_browser_whose_driver_died_is_an_orphan_with_its_whole_group():
    leader = _row(31, 1, 31, f"{HOME_A}{CAMOUFOX} -no-remote")
    child = _row(32, 31, 31, f"{HOME_A}{CHILD} -isForBrowser")
    # A content process whose leader is already gone is lost too.
    stray = _row(33, 1, 40, f"{HOME_A}{CHILD} -isForBrowser")
    # A parent that is not a driver (pid reused by something else).
    leader2 = _row(41, 50, 41, f"{HOME_A}{CAMOUFOX}")
    other = _row(50, 1, 50, "/usr/bin/some-daemon")
    assert set(R.orphans(_table(leader, child, stray, leader2, other))) == {leader, child, stray, leader2}


def test_another_users_browser_is_never_a_candidate():
    theirs = _row(60, 1, 60, f"{HOME_A}{CAMOUFOX}", uid=UID + 1)
    assert R.orphans(_table(theirs)) == []


def test_only_the_browser_launched_under_this_process_is_registered(monkeypatch):
    me = os.getpid()
    home = "/var/folders/x/T/divoom-test-home-mine"
    rows = [
        _row(me, 1, me, "python -m pytest"),
        _row(70, me, me, "/x/node /x/cli.js run-driver"),
        _row(71, 70, 71, f"{home}{CAMOUFOX}"),
        _row(72, 71, 71, f"{home}{CHILD}"),
        _row(80, 99, 99, "/x/node /x/cli.js run-driver"),  # a sibling worker's
        _row(81, 80, 81, f"{home}{CAMOUFOX}"),
    ]
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("DIVOOM_TEST_HOME", home)
    monkeypatch.setattr(R, "table", lambda: rows)
    monkeypatch.setattr(R, "_known", set())
    frame: list[int] = []
    monkeypatch.setattr(R, "_frames", [frame])
    assert R.register_launched() == [71]
    assert frame == [71]
    # The same browser is not registered twice, and a launch that produced
    # nothing the reaper can name is refused rather than left to leak.
    with pytest.raises(R.UnreapableBrowser):
        R.register_launched()


def test_outside_a_test_session_nothing_is_registered(monkeypatch):
    monkeypatch.delenv("DIVOOM_TEST_HOME", raising=False)
    monkeypatch.setattr(R, "table", lambda: pytest.fail("must not look"))
    assert R.register_launched() == []


# ── The real thing: inner sessions with a real browser ───────────────────────

INNER_TEST = """
import os, signal, time
from playwright.sync_api import sync_playwright
from tests.support import browser as B
from tests.support import browser_reaper as R

def _launch_and_lose_the_driver():
    with open(os.environ["REAP_PROBE_OUT"], "w") as f:
        f.write(os.environ["HOME"])
    p = sync_playwright().start()
    B.launch_sync(p)
    home = R.active_home()
    leaders = [x for x in R.under_home(home, R.table()) if x.pid == x.pgid]
    assert leaders, "no browser under the test home"
    for leader in leaders:
        os.killpg(leader.pgid, signal.SIGSTOP)  # wedged: it can no longer see its pipe close
        os.kill(leader.ppid, signal.SIGKILL)    # the driver, as a killed run loses it
    time.sleep(0.5)

def test_fails():
    _launch_and_lose_the_driver()
    assert False, "this test fails with its browser up"

def test_killed():
    _launch_and_lose_the_driver()
    os.kill(os.getpid(), signal.SIGKILL)

def test_sees_no_orphan_of_the_killed_run():
    dead = os.environ["REAP_DEAD_HOME"]
    assert R.under_home(dead, R.table()) == []
"""


def _real_home() -> str:
    return pwd.getpwuid(os.getuid()).pw_dir


def _inner_session(tmp_path, select, *extra, env_extra=None, timeout=240):
    """Run one test of :data:`INNER_TEST` in a fresh pytest session of its own
    (its own fake HOME); return (exit code, the inner HOME). The inner process
    group is this test's, so it is killed here whatever happened."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_inner.py").write_text(textwrap.dedent(INNER_TEST))
    probe = tmp_path / f"home-{select}.txt"
    env = {k: v for k, v in os.environ.items() if k != "DIVOOM_TEST_HOME"}
    env.update(HOME=_real_home(), PYTHONPATH=str(REPO), REAP_PROBE_OUT=str(probe))
    env.update(env_extra or {})
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "tests.conftest",
        "--run-browser",
        "-c",
        str(tmp_path / "pytest.ini"),
        "--rootdir",
        str(tmp_path),
        *extra,
        f"{tmp_path / 'test_inner.py'}::{select}",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError, PermissionError:
            pass
        proc.wait()
    home = probe.read_text() if probe.exists() else ""
    return proc.returncode, home, out.decode(errors="replace") if out else ""


@pytest.fixture
def inner_homes():
    """Every inner HOME a test made; whatever runs under one when the test
    ends is reaped here, so a red run of this file leaks nothing either."""
    homes: list[str] = []
    yield homes
    for home in homes:
        R.reap_home(home)


def test_a_failing_test_leaves_no_browser(tmp_path, inner_homes):
    B.require_browser()
    code, home, out = _inner_session(tmp_path, "test_fails")
    inner_homes.append(home)
    assert home, out
    assert code == 1, out  # it failed, as written
    left = R.under_home(home, R.table())
    assert left == [], f"{len(left)} camoufox process(es) outlived the session:\n{out}"


def test_a_killed_run_is_cleaned_at_the_next_session_start(tmp_path, inner_homes):
    B.require_browser()
    code, dead, out = _inner_session(tmp_path, "test_killed")
    inner_homes.append(dead)
    assert dead, out
    assert code == -signal.SIGKILL, out
    # The instrument can see the leak: the killed run's browser IS still up.
    assert R.under_home(dead, R.table()), "the killed run left no browser to clean"
    code, _, out = _inner_session(tmp_path, "test_sees_no_orphan_of_the_killed_run", env_extra={"REAP_DEAD_HOME": dead})
    assert code == 0, out


def test_a_killed_xdist_worker_is_cleaned_when_its_session_ends(tmp_path, inner_homes):
    B.require_browser()
    code, home, out = _inner_session(tmp_path, "test_killed", "-n", "1")
    inner_homes.append(home)
    assert home, out
    assert code != 0, out
    left = R.under_home(home, R.table())
    assert left == [], f"{len(left)} camoufox process(es) outlived the session:\n{out}"
