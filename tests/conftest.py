"""Shared pytest configuration.

Several ``test_*_functions.py`` modules are *hardware integration* tests: their
``asyncSetUp`` calls ``discover_device()`` which spins up a real ``BleakScanner``
/ CoreBluetooth central manager. On a machine without granted Bluetooth
permission (e.g. CI, or a sandboxed shell) that triggers a macOS TCC privacy
violation which **aborts the whole interpreter**, taking the rest of the suite
down with it.

To keep the unit-test suite runnable and give a real pass/fail baseline, these
hardware tests are skipped by default. Run them against a real device with::

    pytest --run-hardware
"""

import inspect
import os
import sys
import threading
import pathlib
from pathlib import Path

import pytest
import pytest_asyncio

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The suite never sees the user's home (2026-11-01). Test daemons were started
# with the developer's HOME, so each one read and REWROTE the owner's
# `~/.config/divoom-control` -- one pytest run at 02:04 rewrote the owner's
# `links.json` to `links: [], wall: null`, and every daemon a test spawned
# logged into `/tmp/divoom_client.log`, the installed app's daemon log. A
# per-file override (`DIVOOM_LINKS_PATH`, `DIVOOM_TOPOLOGY_PATH`, ...) is a
# rule every new test and every new state file has to remember, so the ONE
# root they all derive from is replaced instead, here, before any test module
# imports a module-level `Path.home()`. Toolchains the suite needs (cargo,
# rustup, git's identity, the e2e browser, the user site-packages) are named
# by their own variables or linked in read-only-by-intent; nothing under
# `.config/divoom-control` is. `tests/test_suite_leaves_the_owner_alone.py`
# holds this.
def _isolate_home() -> None:
    import atexit
    import pwd
    import shutil
    import site
    import tempfile

    real = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if os.environ.get("DIVOOM_TEST_HOME") == os.environ.get("HOME"):
        return  # a child of an isolated run: already isolated
    os.environ.setdefault("CARGO_HOME", str(real / ".cargo"))
    os.environ.setdefault("RUSTUP_HOME", str(real / ".rustup"))
    os.environ.setdefault("GOH_DIR", str(real / "Projects" / "gates_of_heck"))
    os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())
    from tests.support import browser_reaper

    fake = Path(tempfile.mkdtemp(prefix=browser_reaper.HOME_PREFIX))
    # Name the owner: a SIGKILLed run never reaches the atexit rmtree below, so
    # the next session start removes this home once this process is gone.
    browser_reaper.claim_home(str(fake))
    for rel in (".gitconfig", ".config/git", ".cache", "Library/Caches/camoufox",
                "Library/Caches/ms-playwright", "Library/Caches/Mozilla.sccache"):
        src = real / rel
        if src.exists():
            (fake / rel).parent.mkdir(parents=True, exist_ok=True)
            (fake / rel).symlink_to(src)
    os.environ["HOME"] = str(fake)
    os.environ["DIVOOM_TEST_HOME"] = str(fake)
    # Every daemon a test spawns logs here, never into the app's own log.
    os.environ["DIVOOM_DAEMON_LOG"] = str(fake / "divoomd.log")
    atexit.register(shutil.rmtree, fake, True)
    # Registered after the rmtree, so it runs FIRST (atexit is last-in,
    # first-out): no browser of this session outlives the home it runs from.
    atexit.register(browser_reaper.reap_home, str(fake))


_isolate_home()
# The native dylib this conftest used to rebuild on every run is GONE, with
# the C sources and the build script (phase L4, 2026-09-25). The dual-impl
# anti-drift guarantee it provided is now structural instead: the daemon's
# `divoomd::framing` is asserted byte-for-byte against 550 vectors captured from
# that library (divoomd/tests/framing_vectors.json), and
# tests/test_no_native_encoder_chain.py fails the build if the library, its
# sources or a `native_lib` import come back. Nothing needs rebuilding, so
# nothing runs here.


# Modules whose tests require a physically present Divoom device (they call
# divoom_lib.utils.discovery.discover_device() in setUp and connect over BLE).
HARDWARE_TEST_MODULES = frozenset({
    "test_alarm_functions",
    "test_brightness",
    "test_channel_rotation",
    "test_channel_switching",
    "test_display_functions",
    "test_e2e_live_hardware_connect_disconnect",
    "test_game_functions",
    "test_light_functions",
    "test_music_functions",
    "test_push_protocol_diagnostic",
    "test_show_image_hw",
    "test_sleep_functions",
    "test_smoke_display_aliases_hw",
    "test_system_functions",
    "test_timeplan_functions",
    "test_tool_functions",
    "test_tool_timer_functions",
    "test_watchface_roundtrip",
})


def _add_option_once(parser, *args, **kwargs):
    """Register an opt-in flag unless a sibling conftest already did.

    `examples/tests/conftest.py` imports this module with a star import so the
    legacy suite shares these flags and fixtures. Pytest calls `pytest_addoption`
    once per loaded conftest, so `pytest tests examples/tests` calls it twice and
    the second `addoption` for the same name aborts the whole run before a single
    test collects:

        ValueError: option names {'--run-hardware'} already added

    The flags are process-wide, so the first registration wins and the duplicate
    is a no-op. Only that one ValueError is swallowed -- a bad option name must
    still raise.
    """
    try:
        parser.addoption(*args, **kwargs)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise


def pytest_addoption(parser):
    _add_option_once(
        parser,
        "--run-hardware",
        action="store_true",
        default=False,
        help="Run integration tests that require a physically connected Divoom device.",
    )
    _add_option_once(
        parser,
        "--run-browser",
        action="store_true",
        default=False,
        help="Run tests that launch a real browser (Playwright/camoufox). "
             "Excluded by default: they need the camoufox binary present and "
             "are process-contention sensitive -- one of them fails under the "
             "full suite and passes alone (TargetClosedError, kill EPERM).",
    )
    _add_option_once(
        parser,
        "--run-cloud",
        action="store_true",
        default=False,
        help="Run integration tests that require live Divoom cloud access "
             "(network egress + guest login). Skipped in CI / offline.",
    )


def pytest_configure(config):
    # The browser opt-in is enforced at the ONE seam every launch goes through
    # (`tests.support.browser.require_browser`), not by skipping whole modules
    # whose text mentions playwright -- that hid every non-browser test that
    # happened to share a file with a browser one.
    from tests.support import browser as browser_support

    browser_support.RUN_BROWSER = bool(config.getoption("--run-browser"))

    # Every page and context the suites open gets the house's navigation
    # budget (60s, like every other wait) instead of Playwright's own 30s,
    # which a loaded machine crosses: at load 90+ two pre-push runs of this
    # repo were refused by `Page.goto: Timeout 30000ms exceeded` on unrelated
    # suites. The patch lives in its own module because the harness file is
    # already at the 500-line cap.
    from tests.support import navigation_budget  # noqa: F401  (the import IS the patch)

    # A browser a test launches is reaped by its owner, pass or fail, and the
    # session sweeps what a killed run left (tests/support/browser_reaper.py).
    from tests.support import browser_reaper

    browser_reaper.patch_launch()
    if not config.pluginmanager.has_plugin("divoom-browser-reaper"):
        config.pluginmanager.register(browser_reaper.ReaperPlugin(), "divoom-browser-reaper")


def pytest_collection_modifyitems(config, items):
    # The browser suites share ONE browser per session, which belongs to one
    # event loop, so their async tests run on the session loop
    # (tests/support/browser_shared.py). `append=False`: ahead of the plain
    # `asyncio` marker auto mode adds, which would otherwise win.
    from tests.support import browser_shared

    for item in items:
        if (inspect.iscoroutinefunction(getattr(item, "obj", None))
                and browser_shared.runs_on_session_loop(item.module)):
            item.add_marker(pytest.mark.asyncio(loop_scope="session"), append=False)

    run_hw = config.getoption("--run-hardware")
    if run_hw:
        return
    skip_hw = pytest.mark.skip(
        reason="requires a physical Divoom device; run with --run-hardware"
    )
    for item in items:
        if item.module.__name__.split(".")[-1] in HARDWARE_TEST_MODULES:
            item.add_marker(skip_hw)


# R61: harness gate for a suspected cross-test hazard (a reproducible-only-under
# -full-suite flake in test_owner_art_coverage.py, where a mock.patch()'d module
# attribute was occasionally seen unmocked). Leading hypothesis: some
# owner_with_device-style fixture's DeviceOwner.stop() returns before its
# "device-loop" background thread (divoom_client/owner_loop.py) has actually
# exited, letting it survive into a later, unrelated test. DeviceOwner.stop()
# now joins that thread (and bounds its executor shutdown) to close the gap —
# this fixture is the trip-wire: if a thread named "device-loop" is EVER still
# alive after a test, fail LOUDLY and name the offending test, instead of
# leaving it to surface as an unrelated mock/decode failure hundreds of tests
# later. Scoped to this one thread name (unique to OwnerLoopMixin) so it can't
# false-positive on unrelated threads (notification monitor, socket server...).
@pytest.fixture(autouse=True)
def _identities_stay_out_of_the_users_home(tmp_path_factory):
    """The helpers' identity files go to a directory of this session's own.

    The app records an identity for every helper it spawns, so a test that
    spawns a daemon would otherwise write into the USER's
    `~/.config/divoom-control/run/` -- and a test that kills it would leave a
    stale identity there, pointing at a pid the OS may reuse. The identity
    directory is overridable (DIVOOM_IDENTITY_DIR) for exactly this.
    """
    run_dir = tmp_path_factory.mktemp("helper-identities")
    previous = os.environ.get("DIVOOM_IDENTITY_DIR")
    os.environ["DIVOOM_IDENTITY_DIR"] = str(run_dir)
    yield run_dir
    if previous is None:
        os.environ.pop("DIVOOM_IDENTITY_DIR", None)
    else:
        os.environ["DIVOOM_IDENTITY_DIR"] = previous


@pytest.fixture(autouse=True)
def _no_leaked_device_loop_threads():
    yield
    leaked = [t for t in threading.enumerate() if t.name == "device-loop" and t.is_alive()]
    if leaked:
        for t in leaked:
            t.join(timeout=2.0)  # brief grace window for its own teardown
        leaked = [t for t in leaked if t.is_alive()]
    assert not leaked, (
        f"{len(leaked)} 'device-loop' thread(s) survived past test teardown. "
        "A DeviceOwner was created (directly or via an owner_with_device-style "
        "fixture) without owner.stop() running on a guaranteed teardown path, "
        "or stop() returned before its loop thread fully exited."
    )


# The shared browser's end of life (tests/support/browser_shared.py): closed on
# the loop that started it, once, at session end.
@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _shared_browser_async():
    yield
    from tests.support import browser_shared

    await browser_shared.shutdown_async()

