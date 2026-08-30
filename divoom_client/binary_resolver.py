"""Which built `divoomd` is the one this tree means? Answered by VERSION.

**The rule (2026-08-30): the daemon and menubar binaries always carry the app
version. Anything else is stale, and stale means rebuild — never "cope with".**

Three places used to answer this question three different ways, and all three
were wrong in the same direction — they picked a binary by its LOCATION or its
MTIME and then hoped it was current:

* `spawn_daemon` walked ``["release", "debug"]`` and took the first that
  existed, so `target/release/divoomd` won unconditionally. Nothing in this repo
  rebuilds `release` — only `scripts/build_release.sh` does — so it sits at
  whatever version was last shipped. On this machine that was 0.27.0 while the
  tree was 0.28.2.
* `tests/support/daemon_binary.py` had already been bitten by that and switched
  to newest-by-mtime. Better, but recency is still a proxy: the newest binary is
  stale too if nobody rebuilt it after a version bump.
* the version guard in `ensure_daemon` checked the RUNNING daemon and, on a
  mismatch, shut it down and spawned a replacement — from the same stale path.
  Stop, respawn stale, mismatch again: an infinite restart loop, and the user
  sees a daemon that will not stay up.

The proxy is the bug. The binary's own version is the thing being asked about,
so ask the binary: `divoomd --version` prints and exits without touching a
socket (`divoomd/src/cli_args.rs` — it used to start a daemon instead, which is
why nobody could ask cheaply).

`expected_daemon_version()` returning None means the expectation is unknowable
(a bundle with no metadata). An unknown expectation must never justify refusing
to start something that might be perfectly current, so the fallback there is
newest-by-mtime — the old behaviour, kept deliberately for exactly that case.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("divoom_client.binary_resolver")

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The binaries that must carry the app version. `nowplaying` is a standalone
#: library crate and versions independently — same exclusion as
#: `tools/check_version_consistency.py`.
PRODUCT_BINARIES = ("divoomd", "divoom-menubar")

#: `<name> <version>` — what `--version` prints.
_VERSION_LINE = re.compile(r"^\S+\s+(\d+\.\d+\.\d+)\s*$")

#: A `--version` probe is a print and an exit. Anything slower is a binary too
#: old to have the flag, which would fall through its parser and START. Killing
#: at the deadline is the point, not a safety net.
PROBE_TIMEOUT = 5.0


def binary_version(path: Path, timeout: float = PROBE_TIMEOUT) -> str | None:
    """The version `path` reports, or None if it will not say.

    None covers every "cannot trust this" case together, because they all lead
    to the same action (rebuild): the binary predates `--version` and hung until
    the deadline, it exited non-zero, or it printed something unparseable.

    A binary old enough to lack `--version` ignores the flag and starts serving,
    so the timeout **must** kill it — otherwise this function leaks a daemon per
    call. `stdin` is closed and the output captured so it can never inherit this
    process's terminal.

    `--socket` is passed to a throwaway path for that same case, and it is not
    decoration. A hard kill skips `HeldSocket::drop`, so the socket file it bound
    is left behind; without this the probe would litter `/tmp/divoomd.sock` — the
    DEFAULT path — with a stale socket, i.e. a version check whose side effect is
    the exact failure the daemon has code to recover from. A current binary never
    reaches the flag: `--version` short-circuits the parser before it.
    """
    with tempfile.TemporaryDirectory(prefix="divoomd_version_probe_") as tmp:
        try:
            proc = subprocess.run(
                [str(path), "--version", "--socket", str(Path(tmp) / "probe.sock")],
                capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            # subprocess.run kills the child on timeout, but a daemon spawned
            # with setsid would survive; divoomd does not do that to itself, so
            # the kill is sufficient here.
            logger.warning(
                "%s did not answer --version within %.1fs — too old to have the "
                "flag, so it is stale by definition", path, timeout)
            return None
        except OSError as e:
            logger.warning("cannot execute %s: %s", path, e)
            return None
    if proc.returncode != 0:
        logger.warning("%s --version exited %s", path, proc.returncode)
        return None
    m = _VERSION_LINE.match((proc.stdout or "").strip())
    return m.group(1) if m else None


def _expected_version() -> str | None:
    """The version every product binary must carry, or None if unknowable."""
    try:
        from divoom_client.daemon_version import expected_daemon_version

        return expected_daemon_version()
    except Exception:
        return None


def built_candidates(name: str = "divoomd") -> list[Path]:
    """Every built copy of `name` in the dev tree, newest first."""
    found = [REPO_ROOT / "target" / flavour / name for flavour in ("release", "debug")]
    found = [p for p in found if p.exists()]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def bundled_candidates(name: str = "divoomd") -> list[Path]:
    """Copies of `name` shipped inside a packaged app, if we are running in one.

    PyInstaller collects the binary under ``<_MEIPASS>/bin``; py2app puts it in
    ``Resources`` and exports ``RESOURCEPATH``. Both layouts are checked because
    both have shipped.
    """
    out: list[Path] = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        out += [Path(mei) / "bin" / name,
                Path(mei).parent / "Resources" / "bin" / name]
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        out += [Path(rp) / name, Path(rp) / "bin" / name]
    return [p for p in out if p.exists()]


def resolve(name: str = "divoomd", *, override: str | None = None) -> Path | None:
    """The binary to run for `name`, chosen by version, or None if none is current.

    Order: an explicit override (the caller has said which one, so it is not
    ours to second-guess), then the bundle, then the dev tree.
    """
    if override:
        p = Path(override)
        return p if p.exists() else None

    candidates = bundled_candidates(name) + built_candidates(name)
    if not candidates:
        return None

    expected = _expected_version()
    if not expected:
        # Unknowable expectation: fall back to recency rather than refusing to
        # run anything at all.
        return candidates[0]

    for path in candidates:
        if binary_version(path) == expected:
            return path
    return None


def stale_report(name: str = "divoomd") -> list[tuple[Path, str | None]]:
    """Built copies of `name` whose version is not the app's, newest first.

    The gate (`tools/check_built_binaries.py`) uses this; so does the failure
    message when `resolve` comes back empty, so a user is told which binaries
    are wrong and what they say rather than just "not found".
    """
    expected = _expected_version()
    if not expected:
        return []
    out = []
    for path in built_candidates(name):
        got = binary_version(path)
        if got != expected:
            out.append((path, got))
    return out


def rebuild_hint(name: str = "divoomd") -> str:
    """The exact command that makes `name` current."""
    if name == "divoomd":
        return "cargo build -p divoomd    (add --release to refresh target/release)"
    return f"cargo build -p {name}    (add --release to refresh target/release)"
