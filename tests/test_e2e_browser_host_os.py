"""The test browser's fingerprint claims the host's OS, so a new page costs ~0.1 s, not ~2.6 s.

camoufox draws the fingerprint's OS at random, weighted toward Windows, ONCE
per Python process (every launch in one process draws the same OS). A Windows
fingerprint on a Mac lists fonts the host does not have (Calibri, Cambria
Math, Consolas, ...), and every ``new_page`` then took 2.5-2.6 s instead of
0.12-0.16 s (measured 2026-11-02, 22 launches over 9 processes: 16 Windows
draws, all slow; 6 macOS draws, all fast). scripts/browser_e2e.sh runs the
suites in one process, so a whole CI run drew once: the browser step took
58-91 min on a Windows draw and 13-23 min on a macOS one, the same 278 tests.

The fix is at the one launch seam (``tests/support/browser_options.py``):
the fingerprint's OS is the host's. Imports playwright, so
scripts/browser_e2e.sh collects it with the other browser suites.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

import psutil
import pytest

from tests.support.browser import launch
from tests.support.browser_options import fingerprint_os

pytest.importorskip("playwright.async_api")
pytest.importorskip("camoufox")
from playwright.async_api import async_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
#: navigator.platform for each fingerprint OS camoufox draws.
PLATFORM = {"macos": "MacIntel", "linux": "Linux x86_64", "windows": "Win32"}
#: One process draws one OS, so the check needs several processes. The host's
#: OS comes up about 1 draw in 4 unpinned, so 8 all-host draws by chance is
#: about 1 in 65,000.
PROCESSES = 8
#: Each draw READS the options (``launching=False``): camoufox's GPU probe would
#: otherwise launch a browser per draw, 6-10 s each (2026-11-07). The OS is drawn
#: before that probe and does not depend on it.
_DRAW = (
    "import json, sys; sys.path.insert(0, sys.argv[1]);"
    "from tests.support.browser_options import launch_options_for;"
    "env = launch_options_for(network=False, launching=False)['env'];"
    "print(json.loads(''.join(v for k, v in sorted(env.items()) if k.startswith('CAMOU_CONFIG')))"
    "['navigator.platform'])"
)


def test_the_host_has_a_fingerprint_os() -> None:
    assert fingerprint_os() == {"Darwin": "macos", "Linux": "linux"}[platform.system()]


@pytest.mark.parametrize(("host", "want"), [("Darwin", "macos"), ("Linux", "linux")])
def test_each_supported_host_names_its_os(monkeypatch: pytest.MonkeyPatch, host: str, want: str) -> None:
    monkeypatch.setattr(platform, "system", lambda: host)
    assert fingerprint_os() == want


@pytest.mark.parametrize("host", ["Windows", "FreeBSD", ""])
def test_an_unsupported_host_is_refused_not_guessed(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    """Any other host must stop the launch: a guessed OS is the slow foreign-font fingerprint."""
    monkeypatch.setattr(platform, "system", lambda: host)
    with pytest.raises(RuntimeError, match="macOS and Linux"):
        fingerprint_os()


@pytest.mark.parametrize("gpu", [("Apple", "Apple Paravirtual device"), ("Apple", "Apple M1"), None])
def test_the_canvas_is_never_covered_whatever_gpu_the_host_reports(monkeypatch: pytest.MonkeyPatch, gpu) -> None:
    """The suites read canvas pixels. camoufox covers the canvas when the host GPU
    is one fpgen does not record (CI's macOS VM), so seven pixel tests read
    noise there and passed here (run 42406876821)."""
    import camoufox.host_rendering as hr

    from tests.support.browser_options import launch_options_for

    monkeypatch.setattr(hr, "_host_gpu", lambda *a: gpu)
    assert not hr.has_canvas_placeholder(launch_options_for(network=False, launching=True)["firefox_user_prefs"])


def test_every_process_draws_the_hosts_os() -> None:
    """Without a browser: a fresh process per draw, because the OS is drawn once per process."""
    want = PLATFORM[fingerprint_os()]
    got = [
        subprocess.run(
            [sys.executable, "-c", _DRAW, str(ROOT)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=True,
            timeout=60,
        ).stdout.strip()
        for _ in range(PROCESSES)
    ]
    assert got == [want] * PROCESSES, f"fingerprint platforms {got}, host {want}"


def _tree_cpu() -> float:
    """CPU seconds (user + system) spent so far by this process and every descendant,
    which includes the browser playwright launched. Descendants that exit mid-read are
    skipped: a page open does not end a content process."""
    me = psutil.Process()
    total = 0.0
    for proc in [me, *me.children(recursive=True)]:
        try:
            t = proc.cpu_times()
        except psutil.Error:
            continue
        total += t.user + t.system
    return total


#: CPU seconds a warm ``new_page`` may spend across the process tree. Measured
#: 2026-11-07 on this Mac: host fingerprint 0.32-0.68 s, Windows fingerprint
#: 3.5-5.0 s. CPU time, not wall time, because wall time is a function of machine
#: load: the old 1.0 s wall budget read 1.2 s at load average 56 on a healthy
#: browser and refused a push, while CPU time is what the page open itself costs.
CPU_BUDGET_S = 1.5


@pytest.mark.asyncio
async def test_a_new_page_is_cheap() -> None:
    """The effect, not only the setting: a warm browser opens a page cheaply
    (3.5-5.0 CPU-s each with a foreign-OS fingerprint, 0.3-0.7 with the host's)."""
    async with async_playwright() as p:
        browser = await launch(p)
        try:
            context = await browser.new_context()
            await context.new_page()  # the first page also starts the content process
            costs = []
            for _ in range(3):
                start = _tree_cpu()
                await context.new_page()
                costs.append(_tree_cpu() - start)
        finally:
            await browser.close()
    assert sorted(costs)[1] < CPU_BUDGET_S, f"new_page cost {[round(c, 2) for c in costs]} CPU-s"
