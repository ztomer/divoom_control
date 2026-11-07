"""The menu-bar agent's lifecycle: find it, launch it, stop it.

Split out of `divoom_gui/gui_main.py` at the house 500-line cap, at the seam
that names itself: everything here is about the native Rust status item
(`divoom-menubar`) and nothing else in the app is.

In a built app the agent is a helper APP (`Contents/Helpers/Divoom
Menubar.app`, `divoom_client/helper_app.py`) opened through LaunchServices: it
does not die with the app, and it does not keep the app's LaunchServices
record alive either (P1.18). It is also not an
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
    launch command via env (DIVOOM_GUI_PYTHON/SCRIPT). Opened as a helper app
    of its own; never blocks or fails the GUI if it can't start. macOS only.

    `resolve_bundled` is this app's binary resolver (it knows the packaging
    layouts); it is passed in so this module does not have to know how the app
    is packaged. The file that relaunches the GUI is this package's own
    `gui_main.py`, so it is found here.
    """
    if sys.platform != "darwin":
        return
    try:
        # No "is one already running" check, and never a process NAME: the
        # old guard was `pgrep -x divoom-menubar`, and pgrep EXCLUDES ITS OWN
        # ANCESTORS -- from the GUI the tray's "Launch Dashboard" opened, it
        # could not see that very tray, so a second one was spawned (two
        # status items, pids 42068 and 30142, 2026-11-02). The agent keeps
        # the rule itself: it holds a single-instance lock and the newest one
        # replaces any other (`divoom-menubar/src/single_instance.rs`), so
        # starting one is always safe and a relaunch after a reinstall runs
        # the binary now on disk.
        binary = _resolve_menubar_binary(resolve_bundled)
        if not binary:
            logger.warning(
                "Native menu-bar binary (divoom-menubar) not found; build it with ./build.sh. No menu-bar this session."
            )
            return
        # Tell the agent how to relaunch this GUI from "Launch Dashboard".
        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            # PyInstaller .app: sys.executable IS the GUI launcher -- the agent
            # opens its bundle through LaunchServices (launch.rs).
            env["DIVOOM_GUI_PYTHON"] = sys.executable
            env["DIVOOM_GUI_SCRIPT"] = ""
        else:
            from divoom_client.daemon_client import bundle_python

            env["DIVOOM_GUI_PYTHON"] = bundle_python() or sys.executable
            env["DIVOOM_GUI_SCRIPT"] = str(Path(__file__).resolve().parent / "gui_main.py")
        from divoom_client import helper_app

        bundle = helper_app.helper_bundle(binary)
        if bundle is not None:
            # An app of its own, NOT this app's child: a helper this app
            # starts keeps this app's LaunchServices record alive by pid after
            # it quits (P1.18, D.CFXSBX); one opened through LaunchServices
            # does not.
            helper_app.open_helper(bundle, [], env)
            logger.info("Opened the menu-bar agent (%s).", bundle.name)
            return
        # A dev tree's binary has no helper app to open: fork it.
        agent = subprocess.Popen(
            [binary],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        _record_menubar_identity(agent.pid, binary)
        logger.info("Launched native Rust menu-bar agent (divoom-menubar).")
    except Exception as e:
        logger.warning(f"Could not launch menu-bar agent: {e}")


def _ask_agent_to_step_down(timeout: float = 2.0) -> bool:
    """Ask the running agent to exit, over the socket it listens on while it
    holds the single-instance lock (`divoom-menubar/src/single_instance.rs`).

    That socket is what the agent OWNS, so this reaches the running agent
    however it was started -- an opened helper app has no identity file.
    """
    import socket
    from divoom_client import helper_identity

    path = helper_identity.run_dir() / "divoom-menubar.sock"
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(b"replace\n")
            return s.recv(16).strip() == b"ok"
    except OSError:
        return False


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

        stopped = _ask_agent_to_step_down() or helper_identity.stop(helper_identity.MENUBAR)
        logger.info("Terminated menu-bar agent (shared-lifecycle quit): %s", "stopped" if stopped else "not running")
    except Exception as e:
        logger.debug(f"menu-bar terminate skipped: {e}")
