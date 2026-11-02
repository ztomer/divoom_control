"""The browser a test launches is reaped by its owner, pass or fail.

On 2026-11-01 eighteen camoufox processes were found orphaned on the dev
machine, each started by this suite. Playwright starts the browser DETACHED --
its own process group, under the driver (``node ... run-driver``) -- so killing
the run's process group does not reach it, and when the driver dies without
closing it (the run SIGKILLed, an xdist worker killed mid-test, a deadline
killing the tree) the browser and its content processes are re-parented to
launchd and keep running. The suites' ``finally: browser.close()`` cannot help:
the failure path that leaks is exactly the one where no Python ``finally`` runs,
or runs against a driver that is already gone.

So ownership is structural, three layers, all keyed on the TEST'S OWN PATH --
never a process name (goh ``kill-by-name``): the whole browser tree runs its
executable through the session's fake HOME (``tests/conftest.py`` links
``Library/Caches/camoufox`` into ``divoom-test-home-*``), so argv[0] of every
browser process names the session that started it. Measured 2026-11-02: the
leader and all four ``plugin-container`` children carry it, and share the
leader's process group.

1. **The owner.** Every ``BrowserType.launch`` (patched here, the one seam every
   suite reaches) registers the new browser's process group with whatever is
   running: the fixture being set up, or the test body. When that fixture is
   torn down, or the test body returns or raises, the group is killed -- a no-op
   after a clean ``close()``, the whole tree after anything else.
2. **The session end** (the controller, after every worker is done) kills every
   browser under its own home, and every orphan.
3. **The next session start** kills orphans a SIGKILLed run left behind: a
   browser under any ``divoom-test-home-*`` whose driver is gone. A browser
   whose driver is alive belongs to a live session and is left alone.

``tests/test_e2e_browser_reaped.py`` holds all three.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass

#: argv[0] of a browser this suite started: the camoufox cache, reached
#: through a session's fake HOME (macOS cache dir, or the XDG one on Linux).
TEST_BROWSER = re.compile(
    r"^(?P<home>/\S*?/divoom-test-home-[^/\s]+)/(?:Library/Caches|\.cache)/camoufox/")
#: The process Playwright starts a browser under. A browser whose parent is
#: not this has lost its driver, and nothing will ever close it.
DRIVER_MARK = "run-driver"
#: How long a SIGKILLed tree may take to disappear from the process table.
REAP_WAIT_S = 10.0


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    uid: int
    command: str

    @property
    def session_home(self) -> str | None:
        m = TEST_BROWSER.match(self.command)
        return m.group("home") if m else None


def parse_table(text: str) -> list[Proc]:
    """Rows of ``ps -o pid=,ppid=,pgid=,uid=,command=``."""
    procs = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5 or not all(p.isdigit() for p in parts[:4]):
            continue
        procs.append(Proc(*(int(p) for p in parts[:4]), parts[4]))
    return procs


def table() -> list[Proc]:
    out = subprocess.run(
        ["ps", "-axww", "-o", "pid=,ppid=,pgid=,uid=,command="],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True).stdout
    return parse_table(out)


def active_home() -> str | None:
    """This session's fake HOME, or None outside an isolated test session --
    where the camoufox cache is the USER's, and nothing here may touch it."""
    home = os.environ.get("DIVOOM_TEST_HOME")
    return home if home and home == os.environ.get("HOME") else None


def under_home(home: str, procs: list[Proc]) -> list[Proc]:
    real = os.path.realpath(home)
    return [p for p in procs
            if p.session_home and os.path.realpath(p.session_home) in (home, real)]


def orphans(procs: list[Proc]) -> list[Proc]:
    """Test browsers whose driver is gone: a group leader whose parent is not a
    Playwright driver, and every process of that group (or of a group whose
    leader has already died)."""
    by_pid = {p.pid: p for p in procs}
    mine = [p for p in procs if p.session_home and p.uid == os.getuid()]
    lost = set()
    for p in mine:
        leader = by_pid.get(p.pgid)
        if leader is None or not leader.session_home:
            lost.add(p.pgid)  # the leader died; its children never will
            continue
        parent = by_pid.get(leader.ppid)
        if leader.ppid <= 1 or parent is None or DRIVER_MARK not in parent.command:
            lost.add(p.pgid)
    return [p for p in mine if p.pgid in lost]


def descends_from(pid: int, ancestor: int, by_pid: dict[int, Proc]) -> bool:
    seen = set()
    while pid > 1 and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        parent = by_pid.get(pid)
        if parent is None:
            return False
        pid = parent.ppid
    return False


def _profile_dir(command: str) -> str | None:
    """The throwaway profile Playwright made for this browser, if it is one --
    a SIGKILLed browser's driver never got to delete it."""
    m = re.search(r" -profile (\S+)", command)
    if not m:
        return None
    path = m.group(1)
    if (os.path.basename(path).startswith("playwright_firefoxdev_profile-")
            and os.path.dirname(os.path.realpath(path)) == os.path.realpath(tempfile.gettempdir())):
        return path
    return None


def kill(victims: list[Proc]) -> int:
    """SIGKILL each named test-browser process and wait for it to go. Only a
    process still carrying the same test-browser argv is signalled, so a pid
    reused in between is never hit. Returns how many were killed."""
    victims = [v for v in victims if v.session_home]
    if not victims:
        return 0
    for v in victims:
        try:
            os.kill(v.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    wanted = {(v.pid, v.command) for v in victims}
    deadline = time.monotonic() + REAP_WAIT_S
    while time.monotonic() < deadline:
        if not wanted & {(p.pid, p.command) for p in table()}:
            break
        time.sleep(0.05)
    for v in victims:
        profile = _profile_dir(v.command)
        if profile:
            shutil.rmtree(profile, ignore_errors=True)
    return len(victims)


def reap_groups(pgids) -> int:
    """Kill every test-browser process in these process groups."""
    pgids = set(pgids)
    if not pgids:
        return 0
    return kill([p for p in table() if p.pgid in pgids])


def reap_home(home: str | None) -> int:
    """Kill every browser running under ``home``."""
    if not home:
        return 0
    return kill(under_home(home, table()))


def sweep_orphans() -> int:
    """Kill every test browser, from ANY session, whose driver is gone."""
    return kill(orphans(table()))


# ── Ownership: who reaps a browser ───────────────────────────────────────────

#: The owners currently running, innermost last. The bottom frame is the
#: session's: a launch outside any fixture or test body is reaped at the end.
_frames: list[list[int]] = [[]]
_known: set[int] = set()


class UnreapableBrowser(RuntimeError):
    """A browser was launched whose processes the reaper cannot name."""


def register_launched() -> list[int]:
    """Give the browser just launched to the current owner.

    Called right after ``BrowserType.launch`` returns. The new browser is the
    group leader under this session's home that descends from this process and
    is not registered yet; under xdist each worker therefore sees only its own.
    Raises :class:`UnreapableBrowser` when no such leader exists -- a browser
    whose executable is not under the test home would leak without a word.
    """
    home = active_home()
    if home is None:
        return []
    procs = table()
    by_pid = {p.pid: p for p in procs}
    fresh = [p.pgid for p in under_home(home, procs)
             if p.pid == p.pgid and p.pgid not in _known
             and descends_from(p.ppid, os.getpid(), by_pid)]
    if not fresh:
        raise UnreapableBrowser(
            f"launched a browser with no process under the test home {home}: "
            "its executable must run through $HOME/Library/Caches/camoufox, "
            "or nothing can reap it (tests/support/browser_reaper.py)")
    _known.update(fresh)
    _frames[-1].extend(fresh)
    return fresh


def reap_frame(frame: list[int]) -> int:
    killed = reap_groups(frame)
    _known.difference_update(frame)
    frame.clear()
    return killed


def _wrap(original):
    import inspect

    if inspect.iscoroutinefunction(original):
        async def launch(self, *args, **kwargs):
            browser = await original(self, *args, **kwargs)
            register_launched()
            return browser
    else:
        def launch(self, *args, **kwargs):
            browser = original(self, *args, **kwargs)
            register_launched()
            return browser
    launch.__divoom_reaped__ = True
    return launch


def patch_launch() -> None:
    """Make every ``BrowserType.launch`` register what it started."""
    import importlib

    for module_name in ("playwright.async_api", "playwright.sync_api"):
        try:
            cls = importlib.import_module(module_name).BrowserType
        except Exception:  # pragma: no cover - playwright not installed
            continue
        if not getattr(cls.launch, "__divoom_reaped__", False):
            cls.launch = _wrap(cls.launch)


class ReaperPlugin:
    """The pytest half: frames for fixtures and test bodies, and the session
    sweeps. Registered by ``tests/conftest.py``."""

    import pytest as _pytest

    @_pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        frame: list[int] = []
        # Added BEFORE the fixture runs, so it is torn down AFTER the
        # fixture's own teardown (finalizers run last-in, first-out): its
        # graceful close comes first, this only catches what that left.
        fixturedef.addfinalizer(lambda: reap_frame(frame))
        _frames.append(frame)
        try:
            return (yield)
        finally:
            _frames.pop()

    @_pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        frame: list[int] = []
        _frames.append(frame)
        try:
            return (yield)
        finally:
            _frames.pop()
            reap_frame(frame)

    def pytest_sessionstart(self, session):
        if not hasattr(session.config, "workerinput"):
            sweep_orphans()

    @_pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        reap_frame(_frames[0])
        if not hasattr(session.config, "workerinput"):
            reap_home(active_home())
            sweep_orphans()
