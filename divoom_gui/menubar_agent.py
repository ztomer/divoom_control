"""The menu-bar agent's lifecycle: find it, launch it, stop it.

Split out of `divoom_gui/gui_main.py` at the house 500-line cap, at the seam
that names itself: everything here is about the native Rust status item
(`divoom-menubar`) and nothing else in the app is.

The agent is a bare binary in its OWN session: it does not die with the app,
and it is reparented to launchd when the app exits. It is also not an
NSApplication, so `quit:` cannot reach it. The only way to stop it used to be
a NAME PATTERN (`pkill -f divoom-menubar`), which reaches every process whose
command line looks like the agent's — including ones this app does not own.

So it has an IDENTITY: the app records the pid it spawned and the moment that
process started, and the quit path stops THAT process. A pid alone is not an
identity (the OS reuses pids), so the start time is what makes a stale
identity name nothing instead of naming an innocent process.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("divoom_gui")


def _resolve_menubar_binary(resolve_bundled) -> "str | None":
    """Locate the native Rust menubar binary (divoom-menubar).

    Bundle and env override first (`resolve_bundled` knows this app's packaging
    layouts and the `DIVOOM_MENUBAR_BINARY` name); the dev tree is resolved BY
    VERSION through the shared resolver.

    That last part is not cosmetic. This function used to walk
    `("release", "debug")` and take the first that existed — the same
    stale-`target/release` trap fixed for `divoomd` in v0.28.3, still live here
    because that fix was applied per-instance instead of swept for siblings.
    Nothing in this repo rebuilds `target/release`, so a developer running the
    GUI from source got whatever menubar was last shipped, indefinitely.
    """
    bundled = resolve_bundled("divoom-menubar")
    if bundled:
        return bundled
    from divoom_client import binary_resolver

    found = binary_resolver.resolve("divoom-menubar")
    return str(found) if found else None


def _spawn_menubar_agent(resolve_bundled) -> None:
    """Best-effort: launch the native Rust menu-bar agent (divoom-menubar)
    alongside the GUI so its status item appears on launch. The agent talks to the
    daemon over the socket and relaunches THIS GUI on demand, so we hand it our
    launch command via env (DIVOOM_GUI_PYTHON/SCRIPT). Detached + dupe-guarded;
    never blocks or fails the GUI if it can't start. macOS only.

    `resolve_bundled` is this app's binary resolver (it knows the packaging
    layouts); it is passed in so this module does not have to know how the app
    is packaged. The file that relaunches the GUI is this package's own
    `gui_main.py`, so it is found here.
    """
    if sys.platform != "darwin":
        return
    try:
        # Don't spawn a second status item if one is already running. Match the
        # EXACT process name (-x), not a loose command-line substring (-f): under
        # LaunchServices (`open` / Finder / Dock) some coalition process
        # transiently carries "divoom-menubar" in its args, so `-f` false-matched
        # and the agent never launched (no tray icon on a normal launch). `-x`
        # matches only a real `divoom-menubar` process, path-independent.
        #
        # This is a "is one already running" check, NOT a way to find the agent
        # to stop it: stopping it goes through its identity (below). The check
        # stays a name match because it also catches an agent left behind by an
        # OLDER version of the app, which wrote no identity.
        existing = subprocess.run(
            ["pgrep", "-x", "divoom-menubar"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        if existing.returncode == 0 and existing.stdout.strip():
            logger.info("Menu-bar agent already running; not spawning another.")
            return
        binary = _resolve_menubar_binary(resolve_bundled)
        if not binary:
            logger.warning("Native menu-bar binary (divoom-menubar) not found; "
                           "build it with ./build.sh. No menu-bar this session.")
            return
        # Tell the agent how to relaunch this GUI from "Launch Dashboard".
        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            # PyInstaller .app: sys.executable IS the GUI launcher — run it alone
            # (no script; the agent runs DIVOOM_GUI_PYTHON with no args).
            env["DIVOOM_GUI_PYTHON"] = sys.executable
            env["DIVOOM_GUI_SCRIPT"] = ""
        else:
            from divoom_client.daemon_client import bundle_python
            env["DIVOOM_GUI_PYTHON"] = bundle_python() or sys.executable
            env["DIVOOM_GUI_SCRIPT"] = str(Path(__file__).resolve().parent / "gui_main.py")
        agent = subprocess.Popen(
            [binary],
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        # The agent's identity, so it can be addressed by it and not by a name
        # pattern: it is a bare binary in its own session, and a `pkill -f
        # divoom-menubar` reaches every process whose COMMAND LINE looks like
        # it -- including ones this app does not own.
        _record_menubar_identity(agent.pid, binary)
        logger.info("Launched native Rust menu-bar agent (divoom-menubar).")
    except Exception as e:
        logger.warning(f"Could not launch menu-bar agent: {e}")


def _record_menubar_identity(pid: int, command: str) -> None:
    """Write the menu-bar agent's identity (pid + start time).

    The identity is what the quit path and an uninstall act on; the name is
    never used to find the process.
    """
    try:
        from divoom_client import helper_identity
        helper_identity.write(helper_identity.MENUBAR, pid, command)
    except Exception as e:
        logger.debug(f"menu-bar identity not recorded: {e}")


def _terminate_menubar_agent() -> None:
    """Terminate the native menu-bar agent (divoom-menubar) on a shared-lifecycle
    quit. It's spawned detached and does NOT self-terminate on the daemon's
    shutdown broadcast, so without this it orphans to launchd — a stale tray icon
    that also survives a `brew upgrade`. Best-effort; macOS only; never raises.
    Gated by :func:`lifecycle_config.should_quit_menubar_on_exit`.

    It is stopped BY ITS IDENTITY — the pid the app recorded when it spawned
    it, checked against the process's start time — and not by a name pattern:
    a pattern reaches every process whose command line looks like the agent's,
    including ones this app does not own.
    """
    if sys.platform != "darwin":
        return
    try:
        from divoom_client import helper_identity
        stopped = helper_identity.stop(helper_identity.MENUBAR)
        logger.info("Terminated menu-bar agent (shared-lifecycle quit): %s",
                    "stopped" if stopped else "not running")
    except Exception as e:
        logger.debug(f"menu-bar terminate skipped: {e}")
