"""scripts/recycled_pid_probe.py: the D.CFXSBX repro, kept as a repo tool.

The probe launches a browser at a quit app's recycled pid. The part worth a
test is the part that can be wrong without anyone noticing: the pid-advance
loop (it must stop one pid short of the target, and only when every pid
between is taken) and the verdict (a browser that exits is the failure
signature). Both run here against injected spawn/clock/lookup functions, so
no pid is consumed and no browser is started.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parent.parent / "scripts" / "recycled_pid_probe.py"


def _probe():
    spec = importlib.util.spec_from_file_location("_recycled_pid_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # loaded by path: scripts/ is not a package
    return module


class FakeKernel:
    """A pid counter: each spawn takes the next pid; `taken` pids are live."""

    def __init__(self, start: int, taken: set[int] = frozenset()):
        self.next_pid = start
        self.taken = set(taken)
        self.spawned: list[int] = []

    def spawn_and_reap(self) -> int:
        while self.next_pid in self.taken:
            self.next_pid += 1
        pid = self.next_pid
        self.next_pid += 1
        self.spawned.append(pid)
        return pid

    def is_taken(self, pid: int) -> bool:
        return pid in self.taken


def test_it_stops_one_pid_short_of_the_target():
    probe = _probe()
    kernel = FakeKernel(start=900)
    last = probe.advance_to(
        1000,
        spawn_and_reap=kernel.spawn_and_reap,
        taken=kernel.is_taken,
        clock=lambda: 0.0,
        deadline_s=60,
    )
    # Nothing between is taken, so the loop must keep going until the pid it
    # just used is the LAST free one below the target: the next spawn is 1000.
    assert last == 999
    assert kernel.next_pid == 1000


def test_it_does_not_stop_early_while_a_pid_below_the_target_is_free():
    probe = _probe()
    # 990..993 are free; the loop must not stop at 970 just because it is
    # within the 50-pid window.
    kernel = FakeKernel(start=970, taken={994, 995, 996, 997, 998, 999})
    last = probe.advance_to(
        1000,
        spawn_and_reap=kernel.spawn_and_reap,
        taken=kernel.is_taken,
        clock=lambda: 0.0,
        deadline_s=60,
    )
    # Every free pid below the stop was spent, in order, and none after it: a
    # stop condition that fires early (970 is inside the window; 971-993 are
    # free) or late ends the run elsewhere. (`994 not in spawned` could never
    # fail: the kernel never hands out a taken pid.)
    assert kernel.spawned == list(range(970, 994))
    assert last == 993


def test_it_says_when_it_overshoots_and_laps_again():
    probe = _probe()
    said: list[str] = []
    laps = iter([1000, 5, 998])

    def spawn() -> int:
        return next(laps)

    last = probe.advance_to(
        1000,
        spawn_and_reap=spawn,
        taken=lambda pid: pid in {999},
        clock=lambda: 0.0,
        deadline_s=60,
        say=said.append,
    )
    assert any("overshot" in line for line in said)
    assert last == 998


def test_it_gives_up_at_the_deadline_naming_the_last_pid():
    probe = _probe()
    now = iter(range(0, 1000, 10))
    with pytest.raises(probe.ProbeError, match="deadline.*last pid 42"):
        probe.advance_to(
            1000,
            spawn_and_reap=lambda: 42,
            taken=lambda pid: False,
            clock=lambda: next(now),
            deadline_s=30,
        )


def test_a_live_target_is_refused_before_any_pid_is_spent():
    probe = _probe()
    with pytest.raises(probe.ProbeError, match="alive"):
        probe.require_free(os.getpid(), kill=os.kill)


def test_a_dead_target_is_accepted():
    probe = _probe()

    def gone(pid, sig):
        raise ProcessLookupError

    probe.require_free(4_000_000, kill=gone)


def test_a_pid_we_may_not_signal_still_counts_as_taken():
    probe = _probe()

    def forbidden(pid, sig):
        raise PermissionError

    assert probe.pid_taken(1, kill=forbidden) is True


def test_the_newest_installed_camoufox_is_found(tmp_path):
    probe = _probe()
    for version in ("155.0.0-beta.1-aaa", "156.0.1-beta.39-9f754b10"):
        exe = tmp_path / version / "Camoufox.app" / "Contents" / "MacOS" / "camoufox"
        exe.parent.mkdir(parents=True)
        exe.write_text("#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    found = probe.find_camoufox(tmp_path)
    assert found is not None and "156.0.1" in str(found)


def test_no_camoufox_installed_is_none_not_a_crash(tmp_path):
    assert _probe().find_camoufox(tmp_path) is None


def test_the_verdict_names_the_failure_signature():
    probe = _probe()
    assert probe.verdict(None) == (0, "camoufox still running after 4 s -> launched cleanly")
    code, text = probe.verdict(1)
    assert code == 1 and "exited 1" in text and "D.CFXSBX" in text


def test_only_launched_by_ls_lines_are_reported():
    probe = _probe()
    log = "a\n2026 foo launchedByLS=0 bar\nb\nlaunchedByLS=1\n"
    assert probe.launched_by_ls_lines(log) == ["2026 foo launchedByLS=0 bar", "launchedByLS=1"]
    assert probe.launched_by_ls_lines("nothing here") == []
