"""The build/install platform gate: 64-bit only, and macOS is Apple silicon only.

House policy: Apple no longer ships or supports Intel Macs, and no build of this
repo has ever been compiled, run, or tested on a 32-bit host. Both are HARD
failures -- never a warning, never a fallback build.

This gate was this repo's reference implementation and then lost its home.
`scripts/build_libdivoom.sh` carried it inline and this file drove it; the C
encoder chain went (`9a1cade`, 2026-09-25) and took both with it, so every
build/install entry point was back to checking `uname -s` alone and an x86_64 Mac
built and shipped a bundle nobody had run (ROADMAP P1.6).

The check lives once now, in `scripts/lib/platform_gate.sh`, and each entry point
calls it with the policy it needs:

  core  -- builds the cross-platform daemon core. Linux (x86_64/amd64,
           aarch64/arm64) is still supported -- the `rust-core` CI job's target --
           which is why the gate is per script and not global.
  macos -- produces a macOS artifact (.app, .dmg, .dylib, an installed bundle):
           Apple silicon only.

SEAM: the scripts read DIVOOM_BUILD_OS / DIVOOM_BUILD_ARCH instead of calling
`uname` themselves, so BOTH directions are testable on this one machine, and
DIVOOM_BUILD_GATE_ONLY stops the caller immediately after the gate, so the ACCEPT
direction does not have to do the slow work.

TEETH: every case here was watched red. Delete a rejection branch from
`platform_gate.sh` and its rows go red; drop the `divoom_platform_gate` call from
an entry point and that entry point's rows go red; narrow the accepted-arch list
and the accept rows go red.

HONEST SCOPE: this is about the scripts a person runs. `.github/workflows/*.yml`
names its own `runs-on` runner, and that label is its platform contract.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE = "scripts/lib/platform_gate.sh"

# (entry point, policy) -- the contract this file holds each script to. A wrong
# policy here is a red row, which is the point: "macOS-only" and "core" are
# facts about what the script produces, and they are asserted, not assumed.
ENTRY_POINTS: tuple[tuple[str, str], ...] = (
    ("build.sh", "core"),
    ("install.sh", "macos"),
    ("scripts/build_release.sh", "macos"),
    ("scripts/build_nowplaying_helper.sh", "macos"),
    ("scripts/make_app_bundle.sh", "macos"),
    ("scripts/make_dev_daemon_app.sh", "macos"),
)

# Every entry point, plus which of them may run on Linux.
ALL_SCRIPTS = [script for script, _ in ENTRY_POINTS]
CORE_SCRIPTS = [script for script, policy in ENTRY_POINTS if policy == "core"]
MACOS_SCRIPTS = [script for script, policy in ENTRY_POINTS if policy == "macos"]

# The gate must stop a script at the gate. Every gated script exits within
# milliseconds, so a case that reaches this bound did NOT stop there -- it began
# the real build, which in the pre-gate tree means `install.sh` installs and
# `build.sh` compiles. A loud failure beats a test suite that suddenly builds an
# app, and it names the cause.
GATE_DEADLINE_S = 30

INTEL_ARCHES = ["x86_64", "amd64"]
WIDE_ARCHES = ["i686", "i386", "armv7l", "armhf", "riscv64"]
UNSUPPORTED_OSES = ["FreeBSD", "OpenBSD", "SunOS", "Windows_NT"]


def _run(script: str, os_name: str, arch: str) -> subprocess.CompletedProcess[str]:
    """Drive one entry point's seam, stopping it at the gate."""
    try:
        return subprocess.run(
            ["bash", script],
            cwd=REPO,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=GATE_DEADLINE_S,
            env={
                **os.environ,
                "DIVOOM_BUILD_OS": os_name,
                "DIVOOM_BUILD_ARCH": arch,
                "DIVOOM_BUILD_GATE_ONLY": "1",
            },
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"{script} did not stop at the platform gate within "
            f"{GATE_DEADLINE_S}s ({os_name}/{arch}): it ignored "
            f"DIVOOM_BUILD_GATE_ONLY and started real work"
        )


@pytest.mark.parametrize("script", ALL_SCRIPTS)
@pytest.mark.parametrize("arch", INTEL_ARCHES)
def test_macos_intel_is_rejected(script: str, arch: str) -> None:
    """Apple dropped Intel Macs; so did we. macOS x86_64 must not build."""
    r = _run(script, "Darwin", arch)
    assert r.returncode == 1, f"{script}: macOS/{arch} should be rejected, got {r.returncode}"
    assert "Intel" in r.stderr, f"{script}: the refusal must name the Intel case"
    assert arch in r.stderr, f"{script}: the refusal must name the arch"
    # The message must not imply Linux x86_64 is gone too -- it isn't.
    assert "Linux x86_64 remains supported" in r.stderr


@pytest.mark.parametrize("script", ALL_SCRIPTS)
@pytest.mark.parametrize("arch", WIDE_ARCHES)
@pytest.mark.parametrize("os_name", ["Linux", "Darwin"])
def test_32bit_is_rejected_on_every_os(script: str, os_name: str, arch: str) -> None:
    """32-bit and exotic hosts previously fell through to a silent build."""
    r = _run(script, os_name, arch)
    assert r.returncode == 1, f"{script}: {os_name}/{arch} should be rejected, got {r.returncode}"
    assert "64-bit only" in r.stderr


@pytest.mark.parametrize("script", ALL_SCRIPTS)
@pytest.mark.parametrize("os_name", UNSUPPORTED_OSES)
def test_unsupported_os_is_rejected(script: str, os_name: str) -> None:
    """An unsupported OS must HARD-FAIL, not fall through to a generic build.

    R67: the OS branch printed "Unsupported OS: X. Building a generic .so with
    -shared." and kept going, shipping a binary for a platform nobody has
    compiled, run, or tested -- the same silent-untested-binary failure the arch
    branch was hardened against one round earlier.
    """
    r = _run(script, os_name, "x86_64")
    assert r.returncode == 1, f"{script}: {os_name} should be rejected, got {r.returncode}"
    assert "Unsupported OS" in r.stderr
    assert "generic" not in (r.stdout + r.stderr).lower(), (
        "the gate must refuse, not announce a fallback build")


@pytest.mark.parametrize("script", ALL_SCRIPTS)
def test_apple_silicon_is_accepted(script: str) -> None:
    """The gate must not over-reject: this machine builds all of these."""
    r = _run(script, "Darwin", "arm64")
    assert r.returncode == 0, f"{script}: Darwin/arm64 should pass, stderr={r.stderr}"
    assert "gate ok" in r.stdout
    assert "Darwin/arm64" in r.stdout


@pytest.mark.parametrize("script", ALL_SCRIPTS)
@pytest.mark.parametrize("arch", ["x86_64", "amd64", "aarch64"])
def test_linux_is_accepted_by_the_core_build_only(script: str, arch: str) -> None:
    """Linux x86_64/aarch64 stays supported for the daemon core, and only there.

    The daemon core is cross-platform (the `rust-core` CI job builds it on
    Ubuntu); the .app/.dmg/.dylib scripts are macOS by construction -- a TCC
    artifact, a MediaRemote private framework -- and must say so rather than
    produce something for a platform the author cannot run.
    """
    r = _run(script, "Linux", arch)
    if script in CORE_SCRIPTS:
        assert r.returncode == 0, f"{script}: Linux/{arch} should pass, stderr={r.stderr}"
        assert "gate ok" in r.stdout
    else:
        assert r.returncode == 1, f"{script}: Linux/{arch} should be refused, got {r.returncode}"
        assert "macOS-only" in r.stderr


# ── the class, not the instances ────────────────────────────────────────────
#
# The item this closes exists because the gate was deleted from ONE script at a
# time and nobody noticed for twelve days. Per-script rows do not stop that; a
# rule about every script does.

# Files that may call `uname` themselves, and why. An entry here is a claim that
# the call decides nothing; if one goes stale (the call is gone), the claim is a
# lie and the test says so.
UNAME_ALLOWED: dict[str, str] = {
    "scripts/lib/platform_gate.sh": "the gate itself -- this is where uname is read",
    "scripts/linux_remote/test_host.sh": "prints the REMOTE host's identity for the operator; decides nothing",
}

# A platform read: `uname`, with or without a flag cluster (`-s`, `-m`, and the
# combined `-srm` a report uses). Whether it feeds a decision or a print is a
# question for the allowlist below, not for the pattern.
UNAME_RE = re.compile(r"\buname\b(?:\s+-[a-zA-Z]+)?")
GATE_CALL_RE = re.compile(r"^\s*divoom_platform_gate\s+(core|macos)\b")


def _tracked_shell_scripts() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=REPO, capture_output=True, text=True, check=True,
        stdin=subprocess.DEVNULL,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def test_uname_is_read_only_through_the_gate() -> None:
    """No script may decide the platform on its own.

    A `uname -s` comparison in a new build script is exactly how this class came
    back, so the rule is mechanical: `uname` appears in the gate, and nowhere
    else except the places listed above with a reason.
    """
    offenders: list[str] = []
    for rel in _tracked_shell_scripts():
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if not UNAME_RE.search(text):
            continue
        if rel not in UNAME_ALLOWED:
            offenders.append(f"{rel}: reads `uname` outside {GATE}")
    assert not offenders, (
        "expected every platform decision to go through divoom_platform_gate:\n  "
        + "\n  ".join(offenders)
    )


def _reads_uname(rel: str) -> bool:
    """Does this file read `uname` today? A missing file reads nothing."""
    path = REPO / rel
    if not path.is_file():
        return False
    return bool(UNAME_RE.search(path.read_text(encoding="utf-8", errors="replace")))


def test_the_uname_allowlist_has_no_stale_entries() -> None:
    """An allowance nobody re-reads is how the next one gets in."""
    stale = [rel for rel in UNAME_ALLOWED if not _reads_uname(rel)]
    assert not stale, f"these no longer read `uname` -- drop them: {stale}"


@pytest.mark.parametrize("script", ALL_SCRIPTS)
def test_every_entry_point_goes_through_the_gate(script: str) -> None:
    """A gateway that one caller can skip is not a gateway."""
    text = (REPO / script).read_text(encoding="utf-8", errors="replace")
    calls = [line for line in text.splitlines()
             if GATE_CALL_RE.match(line) and not line.strip().startswith("#")]
    assert calls, f"{script} never calls divoom_platform_gate"
    assert f'scripts/lib/platform_gate.sh' in text, (
        f"{script} calls the gate without sourcing {GATE}")
