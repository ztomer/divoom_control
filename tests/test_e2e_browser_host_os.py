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
import time
from pathlib import Path

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
_DRAW = (
    "import json, sys; sys.path.insert(0, sys.argv[1]);"
    "from tests.support.browser_options import launch_options_for;"
    "env = launch_options_for(network=False)['env'];"
    "print(json.loads(''.join(v for k, v in sorted(env.items()) if k.startswith('CAMOU_CONFIG')))"
    "['navigator.platform'])"
)


def test_the_host_has_a_fingerprint_os() -> None:
    assert fingerprint_os() == {"Darwin": "macos", "Linux": "linux"}[platform.system()]


def test_every_process_draws_the_hosts_os() -> None:
    """Without a browser: a fresh process per draw, because the OS is drawn once per process."""
    want = PLATFORM[fingerprint_os()]
    got = [subprocess.run([sys.executable, "-c", _DRAW, str(ROOT)], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          check=True, timeout=60).stdout.strip() for _ in range(PROCESSES)]
    assert got == [want] * PROCESSES, f"fingerprint platforms {got}, host {want}"


@pytest.mark.asyncio
async def test_a_new_page_is_cheap() -> None:
    """The effect, not only the setting: a warm browser opens a page in well under a second
    (2.5-2.6 s each with a foreign-OS fingerprint, 0.12-0.16 s with the host's)."""
    async with async_playwright() as p:
        browser = await launch(p)
        try:
            context = await browser.new_context()
            await context.new_page()  # the first page also starts the content process
            costs = []
            for _ in range(3):
                start = time.monotonic()
                await context.new_page()
                costs.append(time.monotonic() - start)
        finally:
            await browser.close()
    assert sorted(costs)[1] < 1.0, f"new_page took {[round(c, 2) for c in costs]} s"
