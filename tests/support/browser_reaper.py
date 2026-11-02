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

The fake HOME itself has the same owner problem: only an ``atexit`` rmtree
removes it, and a SIGKILLed run never reaches ``atexit`` (ten of them sat in
TMPDIR on 2026-11-02). So the session CLAIMS its home -- an owner file naming
its pid and start time -- and the next session start removes every home whose
owner is dead and which no live process holds (:func:`sweep_dead_homes`).

``tests/test_e2e_browser_reaped.py`` holds all three.
"""

from __future__ import annotations

import contextlib
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
#: The fake HOME a session creates, and the file in it naming the session.
HOME_PREFIX = "divoom-test-home-"
OWNER_FILE = ".divoom-owner"
#: A home with no readable owner file (made before the claim existed) is
#: removed only once it is older than any session can run: the gate's own
#: deadline is 40 minutes.
LEGACY_HOME_AGE_S = 6 * 3600
#: How long `lsof` may take to say who holds a home; no answer counts as held.
LSOF_WAIT_S = 20.0
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


# ── Ownership: who removes a fake HOME ───────────────────────────────────────

def process_started(pid: int) -> str | None:
    """The process's start time as the OS reports it, or None if it is gone.
    A pid alone is not an identity (the OS reuses them); pid + start time is."""
    done = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart="], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False, env={**os.environ, "LC_ALL": "C"})
    started = done.stdout.strip()
    return started if done.returncode == 0 and started else None


def claim_home(home: str, pid: int | None = None) -> None:
    """Name the session that owns ``home``: its pid and start time."""
    pid = os.getpid() if pid is None else pid
    with open(os.path.join(home, OWNER_FILE), "w") as f:
        f.write(f"{pid}\n{process_started(pid) or ''}\n")


def owner_alive(home: str) -> bool | None:
    """True when the session that claimed ``home`` is still running, False when
    it is gone (or its pid now belongs to another process), None when the home
    names no owner."""
    try:
        with open(os.path.join(home, OWNER_FILE)) as f:
            pid_text, _, started = f.read().partition("\n")
        pid = int(pid_text)
    except (OSError, ValueError):
        return None
    live = process_started(pid)
    return live is not None and live == started.strip()


def held_by_process(home: str, procs: list[Proc]) -> bool:
    """Does a live process hold ``home``: it is named in a command line, or a
    process has a file open under it (`lsof`; no answer counts as held)."""
    real = os.path.realpath(home)
    if any(home in p.command or real in p.command for p in procs):
        return True
    try:
        done = subprocess.run(
            ["lsof", "-t", "+D", real], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=LSOF_WAIT_S, check=False)
    except FileNotFoundError:
        return False  # no lsof here: the command-line check above is all there is
    except subprocess.TimeoutExpired:
        return True
    return bool(done.stdout.strip())


def dead_homes(tmpdir: str | None = None, *, now: float | None = None) -> list[str]:
    """The ``divoom-test-home-*`` directories nobody owns any more: the
    claiming session is dead and no live process holds the directory. A home
    with no owner file qualifies once it is older than LEGACY_HOME_AGE_S."""
    base = tmpdir or tempfile.gettempdir()
    now = time.time() if now is None else now
    procs = table()
    mine = active_home()
    dead = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    for name in names:
        path = os.path.join(base, name)
        if not name.startswith(HOME_PREFIX) or os.path.islink(path) or not os.path.isdir(path):
            continue
        if os.stat(path).st_uid != os.getuid() or path == mine:
            continue
        alive = owner_alive(path)
        if alive:
            continue
        if alive is None:
            born = getattr(os.stat(path), "st_birthtime", os.stat(path).st_ctime)
            if now - born < LEGACY_HOME_AGE_S:
                continue
        if not held_by_process(path, procs):
            dead.append(path)
    return dead


def sweep_dead_homes(tmpdir: str | None = None) -> int:
    """Remove every fake HOME whose session is dead (the SIGKILLed run's
    ``atexit`` never ran). Returns how many were removed."""
    removed = 0
    for path in dead_homes(tmpdir):
        shutil.rmtree(path, ignore_errors=True)  # symlinks inside are unlinked, not followed
        removed += 1
    return removed


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


@contextlib.contextmanager
def session_owned():
    """Launches inside the block belong to the SESSION (its end reaps them),
    not to the fixture or test that happens to be running. For a browser many
    tests share (``tests/support/browser_shared.py``)."""
    _frames.append(_frames[0])
    try:
        yield
    finally:
        _frames.pop()


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
            # After the browsers: a browser still running under a home holds it.
            sweep_dead_homes()

    @_pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        reap_frame(_frames[0])
        if not hasattr(session.config, "workerinput"):
            reap_home(active_home())
            sweep_orphans()
