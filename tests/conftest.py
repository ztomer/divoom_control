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

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from divoom_lib.native_lib import library_path as _native_library_path
_DYLIB = _native_library_path()  # platform-aware (.dylib/.so/.dll)
_BUILD_SCRIPT = _REPO_ROOT / "scripts" / "build_libdivoom.sh"
_C_SOURCES = [
    _REPO_ROOT / "divoom_lib" / "native_src" / "compact.c",
    _REPO_ROOT / "divoom_lib" / "native_src" / "downsample.c",
    _REPO_ROOT / "divoom_lib" / "native_src" / "downsample_kernel.c",
    _REPO_ROOT / "divoom_lib" / "native_src" / "image_encode.c",
    _REPO_ROOT / "divoom_lib" / "native_src" / "image_encode_32.c",
]


def _dylib_is_stale() -> bool:
    """True if the dylib is missing or older than any C source."""
    if not _DYLIB.exists():
        return True
    lib_mtime = _DYLIB.stat().st_mtime
    return any(src.exists() and src.stat().st_mtime > lib_mtime for src in _C_SOURCES)


def pytest_configure(config):
    """Rebuild the native dylib if it's missing or stale, so the dual-impl
    correctness suite (tests/test_encoder_both_impls.py) actually exercises the
    C encoder instead of silently skipping it. This is the anti-drift guarantee:
    a C-source change can't ship untested. No-ops cleanly if there's no compiler.
    Set DIVOOM_SKIP_NATIVE_BUILD=1 to opt out.
    """
    if os.environ.get("DIVOOM_SKIP_NATIVE_BUILD"):
        return
    if not _BUILD_SCRIPT.exists() or not _dylib_is_stale():
        return
    try:
        subprocess.run(
            ["bash", str(_BUILD_SCRIPT)],
            cwd=str(_REPO_ROOT), check=True,
            capture_output=True, text=True, timeout=120,
        )
        print(f"conftest: rebuilt {_DYLIB.name} (was missing/stale)")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        # No compiler / build failure: the native tests will skip; Python still runs.
        print(f"conftest: native dylib build skipped ({type(e).__name__})")


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
    "test_sleep_functions",
    "test_system_functions",
    "test_timeplan_functions",
    "test_tool_functions",
    "test_tool_timer_functions",
})


def pytest_addoption(parser):
    parser.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="Run integration tests that require a physically connected Divoom device.",
    )
    parser.addoption(
        "--run-cloud",
        action="store_true",
        default=False,
        help="Run integration tests that require live Divoom cloud access "
             "(network egress + guest login). Skipped in CI / offline.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-hardware"):
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
