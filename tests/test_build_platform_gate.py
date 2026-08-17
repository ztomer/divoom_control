"""The native-build platform gate: 64-bit only, and macOS is Apple silicon only.

House policy (2026-08): Apple no longer ships or supports Intel Macs, and we
never compiled, ran, or tested a 32-bit build. Both are hard failures now.

Before this gate, `scripts/build_libdivoom.sh` matched arch with a `*)` fallback
that printed "Unknown arch: building with no SIMD flags" and **kept going** — so
an i686 or armv7 host silently produced an untested binary instead of stopping.

Teeth: delete the `exit 1` from either reject branch in build_libdivoom.sh and
the corresponding test here goes red.

The script reads DIVOOM_BUILD_OS/DIVOOM_BUILD_ARCH instead of calling `uname`
directly, so both directions are testable on one machine.
DIVOOM_BUILD_GATE_ONLY stops it before the (slow) compile.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_libdivoom.sh"


def _run(os_name: str, arch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "DIVOOM_BUILD_OS": os_name,
            "DIVOOM_BUILD_ARCH": arch,
            "DIVOOM_BUILD_GATE_ONLY": "1",
        },
    )


@pytest.mark.parametrize("arch", ["x86_64", "amd64"])
def test_macos_intel_is_rejected(arch: str) -> None:
    """Apple dropped Intel Macs; so did we. macOS x86_64 must not build."""
    r = _run("Darwin", arch)
    assert r.returncode == 1, f"macOS/{arch} should be rejected, got {r.returncode}"
    assert "Intel" in r.stderr
    # The message must not imply Linux x86_64 is also gone — it isn't.
    assert "Linux x86_64 remains supported" in r.stderr


@pytest.mark.parametrize("arch", ["i686", "i386", "armv7l", "armhf"])
def test_32bit_is_rejected_on_every_os(arch: str) -> None:
    """32-bit hosts previously fell through to a silent no-SIMD build."""
    for os_name in ("Linux", "Darwin"):
        r = _run(os_name, arch)
        assert r.returncode == 1, f"{os_name}/{arch} should be rejected"
        assert "64-bit only" in r.stderr or "Intel" in r.stderr


@pytest.mark.parametrize(
    "os_name,arch",
    [
        ("Darwin", "arm64"),
        ("Linux", "x86_64"),   # Linux Intel/AMD stays supported
        ("Linux", "amd64"),
        ("Linux", "aarch64"),
    ],
)
def test_supported_platforms_pass_the_gate(os_name: str, arch: str) -> None:
    """The gate must not over-reject: these four are still supported."""
    r = _run(os_name, arch)
    assert r.returncode == 0, f"{os_name}/{arch} should pass, stderr={r.stderr}"
    assert "gate ok" in r.stdout
