"""Start a long-lived helper as an app of its own, through LaunchServices.

D.HELPER (ROADMAP P1.18, 2026-11-02). The app's helpers (`divoomd`,
`divoom-menubar`) are meant to outlive it (the tray, `keep_daemon_alive`).
While a helper the app started is alive, launchservicesd keeps the QUIT app's
record, keyed by its pid (`lsappinfo list`: ``(exited-with-subordinates)``),
and the next AppKit process to draw that pid is bound to the dead record and
exits 1 (the D.CFXSBX camoufox failure, `tests/support/browser_launch.py`).

Measured 2026-11-02 with a throwaway applet that starts a helper and quits:

* a forked child (any detach: `setsid`, a disclaimed `posix_spawn`) stays in
  the applet's coalition -> record kept;
* a `launchctl bootstrap`ped job leaves the coalition, but the record lists
  it under ``loadedJobs`` -> record kept (also through a trampoline job, and
  with the environment cleared);
* an app bundle opened with ``open -g -n -a`` -> the applet's record is gone
  the moment it quits, and the helper runs on as its own app.

So a helper the app starts to OUTLIVE it is the main executable of a helper
app (`scripts/make_helper_apps.sh`: ``Contents/Helpers/<Name>.app``, with
``Contents/Frameworks/bin/<name>`` a symlink into it), opened here. A binary
that is not inside a helper app (a dev tree's ``target/``) has no bundle to
open, and the caller forks it as before.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: Environment a helper is handed. `open` starts the app from LaunchServices'
#: environment, not the opener's, so the variables the helpers read are
#: passed by name: the app's own (`DIVOOM_*`) and Rust's logging switches.
_PASSED_PREFIXES = ("DIVOOM_",)
_PASSED_NAMES = ("RUST_LOG", "RUST_BACKTRACE")


def helper_bundle(binary: str | os.PathLike) -> Path | None:
    """The helper app whose main executable ``binary`` is, or None.

    ``binary`` may be the ``Frameworks/bin`` symlink: it is resolved first.
    """
    try:
        exe = Path(binary).resolve(strict=True)
    except OSError:
        return None
    macos = exe.parent
    contents = macos.parent
    app = contents.parent
    if macos.name == "MacOS" and contents.name == "Contents" and app.suffix == ".app":
        return app
    return None


def passed_env(env: dict[str, str]) -> dict[str, str]:
    """The part of ``env`` a helper reads."""
    return {k: v for k, v in env.items() if k.startswith(_PASSED_PREFIXES) or k in _PASSED_NAMES}


def open_command(bundle: Path, args: list[str], env: dict[str, str], log_path: str | None) -> list[str]:
    """The ``open`` invocation that starts ``bundle`` as a new instance.

    ``-n``: always a NEW instance, so a relaunch or a reinstall starts the
    binary now on disk; the helper's own single-instance rule decides what
    happens to an older one (the menubar's newest wins, the daemon's socket
    lock refuses a second). ``-g``: never take focus.
    """
    cmd = ["/usr/bin/open", "-n", "-g", "-a", str(bundle)]
    for k, v in sorted(passed_env(env).items()):
        cmd += ["--env", f"{k}={v}"]
    if log_path:
        cmd += ["--stdout", log_path, "--stderr", log_path]
    if args:
        cmd += ["--args", *args]
    return cmd


def open_helper(bundle: Path, args: list[str], env: dict[str, str], log_path: str | None = None, run=None) -> None:
    """Open ``bundle`` through LaunchServices. Raises OSError if `open` fails."""
    run = run or subprocess.run
    done = run(
        open_command(bundle, args, env, log_path),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
        timeout=15,
    )
    if done.returncode != 0:
        raise OSError(f"open {bundle.name} failed ({done.returncode}): {(done.stderr or '').strip()}")
