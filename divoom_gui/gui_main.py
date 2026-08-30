#!/usr/bin/env python3
"""
gui_main.py — Divoom Desktop GUI launcher.
Launches the custom frameless PyWebView window.
"""

# The py2app-bundled interpreter starts with NO locale applied and ignores
# PYTHONUTF8, so locale.getpreferredencoding() is US-ASCII. That breaks any text
# I/O that relies on it (e.g. the daemon spawn's env handling) with
# UnicodeDecodeError on the non-ASCII Kare glyphs. Apply a UTF-8 locale FIRST,
# before any other import does locale-sensitive I/O. (No-op when already UTF-8.)
import locale as _locale
for _loc in ("en_US.UTF-8", "C.UTF-8"):
    try:
        _locale.setlocale(_locale.LC_ALL, _loc)
        break
    except Exception:  # pragma: no cover - runs at import, before any fixture;
        pass            # exercised by a subprocess in test_gui_main_bootstrap.py
                         # (coverage can't attribute a child process's lines here)

import os
import sys
import threading
import logging
import webview
from pathlib import Path

# Add divoom-control paths
sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

from divoom_gui.gui_api import DivoomGuiAPI
from divoom_lib.divoom import Divoom
from divoom_lib.wall import DivoomWall
from bleak import BleakScanner
from divoom_lib import divoom_auth

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("divoom_gui")


def _pywebview_1820_bug_present() -> bool:
    """Detect whether pywebview's cocoa `BrowserView.move` still has
    the multi-monitor drag bug from upstream issue #1820.

    The bug (May 2026, present in 6.2.1): the cocoa backend's
    `BrowserView.move` does
        AppKit.NSPoint(self.screen.origin.x + x, self.screen.origin.y + flipped_y)
    but the JS in `webview/js/customize.js:44-48` sends absolute
    screen coordinates (`x = ev.screenX - initialX`), so the X is
    double-counted on multi-monitor setups and the window jumps
    off-screen mid-drag.

    The fix (upstream-recommended): drop the `self.screen.origin.x`
    term, or replace with the primary screen's origin. Any fix
    necessarily changes the literal token `self.screen.origin.x + x`
    inside the NSPoint call, so we can use that token's presence
    as a robust detection signal.

    Returns:
        True if the installed pywebview's `BrowserView.move` still
        contains the bug token and the downstream monkey-patch
        should be applied. False if the bug is not detectable
        (non-cocoa backend, source not introspectable) or if the
        upstream fix has shipped.

    The detection is intentionally narrow: matching on the exact
    bug token (`self.screen.origin.x + x`) means any plausible
    upstream fix (drop the term, replace with primary screen
    reference, rewrite the call) will not match, and the
    monkey-patch will be skipped cleanly. See
    `docs/DRAG_FIX_HISTORY.md` for the full journey.
    """
    try:
        import inspect
        from webview.platforms.cocoa import BrowserView
        src = inspect.getsource(BrowserView.move)
    except (ImportError, OSError, TypeError):
        return False

    return "self.screen.origin.x + x" in src


def _resolve_web_ui() -> Path:
    """Locate the web_ui directory. Source: next to this file. PyInstaller: data is
    collected under divoom_gui/web_ui, which for a .app lives in Contents/Resources
    while sys._MEIPASS is Contents/Frameworks — so search the likely roots and pick
    the one that actually has index.html."""
    here = Path(__file__).resolve().parent
    cands = [here / "web_ui"]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        m = Path(mei)
        cands += [m / "divoom_gui" / "web_ui", m / "web_ui",
                  m.parent / "Resources" / "divoom_gui" / "web_ui"]
    for c in cands:
        if (c / "index.html").exists():
            return c
    return cands[0]


def _resolve_bundled_binary(name: str) -> "str | None":
    """Find a bundled Rust binary (divoomd / divoom-menubar) across packagings:
    PyInstaller (sys._MEIPASS/bin), py2app (RESOURCEPATH), and the dev tree."""
    override = os.environ.get("DIVOOM_RUST_BINARY" if name == "divoomd" else "DIVOOM_MENUBAR_BINARY")
    if override and Path(override).exists():
        return override
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        for c in (Path(mei) / "bin" / name, Path(mei) / name,
                  Path(mei).parent / "Resources" / "bin" / name):
            if c.exists():
                return str(c)
    rp = os.environ.get("RESOURCEPATH")
    if rp and (Path(rp) / name).exists():
        return str(Path(rp) / name)
    return None


_GUI_LOCK_FH = None  # kept open for the process lifetime to hold the lock


def _ensure_single_instance() -> bool:
    """True if we got the single-instance lock; False if a Control Center is
    already running (R24 #1 — prevents the menubar 'Launch Dashboard' →
    dashboard → menubar runaway)."""
    global _GUI_LOCK_FH
    try:
        import fcntl
        import tempfile
        fh = open(os.path.join(tempfile.gettempdir(), "divoom_gui.lock"), "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        _GUI_LOCK_FH = fh
        return True
    except (OSError, BlockingIOError):
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Divoom Control Center")
    # R15 §6: the menubar "Open Notifications..." item launches with these so the
    # GUI opens straight to a given tab/card.
    parser.add_argument("--tab", default=None, help="nav tab to pre-select (e.g. data-sources)")
    parser.add_argument("--card", default=None, help="card to focus within the tab (e.g. notifications)")
    cli_args, _ = parser.parse_known_args()

    if sys.platform == "darwin" and not _ensure_single_instance():
        logger.info("A Divoom Control Center is already running; focusing it and exiting.")
        try:
            import subprocess
            subprocess.run(["osascript", "-e", 'tell application "Python" to activate'],
                           check=False, capture_output=True)
        except Exception:
            pass
        return

    api = DivoomGuiAPI()
    web_ui_dir = _resolve_web_ui()
    index_html = web_ui_dir / "index.html"

    # Optional headless control server surface (E2E testing)
    if os.environ.get("DIVOOM_CONTROL_SERVER") in ("1", "true", "yes"):
        try:
            from control_server import serve_in_background
            port = int(os.environ.get("DIVOOM_CONTROL_PORT", "8787"))
            serve_in_background(api, port=port)
            logger.info(f"Control server enabled on http://127.0.0.1:{port}")
        except Exception as e:
            logger.warning(f"Failed to start control server: {e}")

    # Optional Unix-domain-socket control surface
    sock_path = os.environ.get("DIVOOM_CONTROL_SOCKET")
    if sock_path:
        try:
            from control_server import serve_unix_in_background
            serve_unix_in_background(api, sock_path)
            logger.info(f"Control server enabled on unix:{sock_path}")
        except Exception as e:
            logger.warning(f"Failed to start unix control server: {e}")

    logger.info("Starting Divoom Desktop GUI window in frameless mode...")

    # Workaround for pywebview upstream issue #1820
    # (https://github.com/r0x0r/pywebview/issues/1820, May 2026):
    # BrowserView.move in the cocoa backend double-counts the window's
    # screen origin on multi-monitor setups, causing the window to
    # jump off the visible workspace mid-drag. The recommended
    # downstream patch drops the `self.screen.origin.x` term from the
    # NSPoint calculation. This is a no-op on single-monitor setups
    # (where screen.origin = (0, 0)) and matches the JS-side contract
    # that drag deltas are applied relative to the live window
    # position tracked by the host.
    #
    # The detection is source-based: if the literal token
    # `self.screen.origin.x + x` is no longer in BrowserView.move's
    # source, the upstream fix has shipped and the patch is skipped
    # (idempotent). See docs/DRAG_FIX_HISTORY.md for the journey.
    if sys.platform == "darwin":
        try:
            from webview.platforms.cocoa import BrowserView
            import AppKit

            if _pywebview_1820_bug_present():
                def _patched_move(self, x, y):
                    flipped_y = self.screen.size.height - y
                    self.window.setFrameTopLeftPoint_(
                        AppKit.NSPoint(x, self.screen.origin.y + flipped_y)
                    )

                BrowserView.move = _patched_move
                logger.info("Applied pywebview #1820 multi-monitor drag patch")
            else:
                logger.info("pywebview #1820 already fixed upstream; skipping patch")
        except ImportError:
            logger.warning("Could not check pywebview #1820 patch (AppKit not available)")

    import time
    from urllib.parse import urlencode
    query = {"t": int(time.time())}
    if cli_args.tab:
        query["tab"] = cli_args.tab
    if cli_args.card:
        query["card"] = cli_args.card
    url_str = f"{index_html.as_uri()}?{urlencode(query)}"
    window = webview.create_window(
        title="Divoom Control Center",
        url=url_str,
        js_api=api,
        width=1080,   # R24 #8: fits 3 columns in Monthly Best
        height=768,
        resizable=True,
        frameless=True,  # Integrated custom Appbar
        easy_drag=False,
        background_color="#0a0b10",
        min_size=(1050, 400),
    )
    api.window = window
    # R24: spawn the daemon EAGERLY, BEFORE webview.start(), so it's ready when
    # the GUI first asks. The daemon's Bluetooth grant no longer depends on WHO
    # spawns it: `spawn_daemon` uses macOS TCC responsibility-disclaim so the
    # daemon is always its own responsible process — the native divoomd via its
    # own embedded Info.plist (com.divoom.divoomd), the Python daemon via the
    # granted `python3.14` binary — not pywebview's ungranted `Python.app` host or
    # whatever app launched the bundle (see daemon_bridge for the why).
    if sys.platform == "darwin":
        try:
            from divoom_gui.daemon_bridge import ensure_daemon
            # R53: assign the client. Previously the return value was discarded,
            # so api._daemon_client stayed None until the first user action
            # lazily re-ran ensure_daemon — and a failed/slow spawn surfaced
            # nothing. Handing the live client over means the GUI is ready
            # immediately; if it's None (spawn failed/timed out), the frontend's
            # daemon-health heartbeat auto-reconnects and, failing that, shows a
            # Reconnect banner instead of leaving the app silently unusable.
            api._daemon_client = ensure_daemon(detach=True)
            if api._daemon_client is not None:
                logger.info("Eagerly spawned daemon (TCC-disclaimed) before GUI host.")
            else:
                logger.warning("Eager daemon spawn did not become ready; "
                               "UI will auto-reconnect / offer a Reconnect banner.")
        except Exception as e:
            logger.warning(f"eager daemon spawn failed: {e}")
    _spawn_menubar_agent()
    # Prime TCC prompts up front from the foreground app — esp. Automation
    # (AppleScript control of Music/Spotify) for the cover-art widget, whose
    # prompt was otherwise raised invisibly by the headless daemon.
    try:
        from divoom_gui.permissions import prime_permissions
        prime_permissions()
    except Exception as e:
        logger.debug(f"permission priming skipped: {e}")
    # R40 §9: follow the daemon down if it shuts down while we're open AND the
    # lifecycles are shared (keep-alive off) — e.g. the menu bar's 'Quit Divoom'.
    _start_shutdown_follower(window)

    # R52: stop the daemon EXACTLY ONCE. Both the `closing` event and the
    # post-start block (and, indirectly, the shutdown follower) used to each send
    # a shutdown, so one quit produced a "shut down → close → shut down" cascade
    # in the logs and re-triggered the follower. The guard collapses it to one.
    _shutdown_sent = threading.Event()

    def _stop_daemon_once(reason: str) -> None:
        if _shutdown_sent.is_set():
            return
        _shutdown_sent.set()
        try:
            from divoom_lib.lifecycle_config import (
                get_keep_daemon_alive, get_quit_menubar_on_exit,
                should_stop_daemon_on_dashboard_quit, should_quit_menubar_on_exit)
            keep_alive = get_keep_daemon_alive()
            if should_stop_daemon_on_dashboard_quit(keep_alive):
                from divoom_client.daemon_protocol import DaemonClient, DEFAULT_SOCKET_PATH
                logger.info(f"{reason}; stopping daemon (shared lifecycle).")
                DaemonClient(DEFAULT_SOCKET_PATH, timeout=1.0).shutdown()
            # The native menu bar doesn't follow the daemon's shutdown broadcast,
            # so terminate it explicitly (unless the user opted to keep the tray).
            if should_quit_menubar_on_exit(keep_alive, get_quit_menubar_on_exit()):
                _terminate_menubar_agent()
        except Exception as e:
            logger.debug(f"daemon shutdown skipped: {e}")

    window.events.closing += lambda: _stop_daemon_once("Dashboard closing")
    # DIVOOM_GUI_DEBUG=1 → enable the WebKit inspector (right-click → Inspect
    # Element) so a blank/broken page can be diagnosed from the JS console.
    _debug = os.environ.get("DIVOOM_GUI_DEBUG") in ("1", "true", "yes")
    webview.start(debug=_debug)

    # webview.start() blocks until the window closes. On close, when lifecycles
    # are shared, stop the daemon too (which broadcasts → the menu bar follows).
    _stop_daemon_once("Dashboard closed")

    # R52: the GUI is a thin client — the daemon (a separate process) owns the
    # BLE connection and has already been told to stop. pywebview/WebKit can leave
    # the host process alive after the window is destroyed (an in-flight js_api
    # call, a lingering Cocoa run loop), so force a clean exit rather than hang.
    logger.info("Dashboard exited; terminating GUI host.")
    os._exit(0)


def _make_daemon_event_handler(window):
    """Build the daemon-subscription callback.

    Forwards connection ``status`` events to the web UI so the dashboard updates
    LIVE (event-driven) instead of only on its polling heartbeat — the
    R58/UI-reliability fix. The daemon now broadcasts honest status events
    (``connected`` + ``mac``/``lan_ip``) on connect/disconnect and as the
    subscribe snapshot, so a freshly opened GUI no longer shows a stale
    "disconnected" until the next poll. A shutting-down daemon still closes the
    window when shared lifecycle is on.
    """
    import json as _json
    from divoom_client.daemon_protocol import EVENT_SHUTDOWN

    def on_event(ev: dict) -> None:
        if not isinstance(ev, dict):
            return
        etype = ev.get("type")
        if etype == EVENT_SHUTDOWN:
            try:
                from divoom_lib.lifecycle_config import (
                    get_keep_daemon_alive, should_follow_daemon_shutdown)
            except Exception:
                return
            if should_follow_daemon_shutdown(get_keep_daemon_alive()):
                logger.info("Daemon shut down; closing dashboard (shared lifecycle).")
                try:
                    window.destroy()
                except Exception:
                    pass
            return
        # status + notification + owned_devices + notif_status + hot_progress →
        # web UI, for immediate honest rendering (R59/event-driven; replaces the
        # 4s polling heartbeats). Each maps to window.Divoom.on<Event>.
        if etype in ("status", "notification", "owned_devices",
                     "notif_status", "hot_progress"):
            handler = {
                "status": "onDaemonEvent",
                "notification": "onDaemonEvent",
                "owned_devices": "onOwnedDevices",
                "notif_status": "onNotifStatus",
                "hot_progress": "onHotProgress",
            }.get(etype)
            try:
                payload = _json.dumps(ev, separators=(",", ":"))
                window.evaluate_js(
                    f"if(window.Divoom&&window.Divoom.{handler}){{"
                    f"window.Divoom.{handler}({payload});}}")
            except Exception:
                pass
    return on_event


def _start_shutdown_follower(window) -> None:
    """Subscribe to the daemon's event stream on a daemon thread and forward
    connection status + shutdown to the web UI. Event-driven — no polling. When
    the subscription ends (socket closed / daemon gone) we tell the UI the
    daemon is down — that replaces the old 4s daemon-health poll (R59) — then
    retry so events resume the moment the daemon comes back."""
    import time as _time

    def _run():
        from divoom_client.daemon_protocol import DaemonClient, DEFAULT_SOCKET_PATH
        while True:
            try:
                DaemonClient(DEFAULT_SOCKET_PATH, timeout=2.0).subscribe(
                    _make_daemon_event_handler(window))
            except Exception as e:
                logger.debug(f"daemon event follower stopped: {e}")
            finally:
                # subscribe returned → daemon is down (socket closed). Tell the UI.
                try:
                    window.evaluate_js(
                        "if(window.Divoom&&window.Divoom.onDaemonDown){"
                        "window.Divoom.onDaemonDown();}")
                except Exception:
                    pass
            # back off, then resubscribe (self-heal on daemon restart)
            _time.sleep(2.0)

    threading.Thread(target=_run, daemon=True, name="daemon-event-follower").start()


def _resolve_menubar_binary() -> "str | None":
    """Locate the native Rust menubar binary (divoom-menubar).

    Bundle and env override first (`_resolve_bundled_binary` knows this app's
    packaging layouts and the `DIVOOM_MENUBAR_BINARY` name); the dev tree is
    resolved BY VERSION through the shared resolver.

    That last part is not cosmetic. This function used to walk
    `("release", "debug")` and take the first that existed — the same
    stale-`target/release` trap fixed for `divoomd` in v0.28.3, still live here
    because that fix was applied per-instance instead of swept for siblings.
    Nothing in this repo rebuilds `target/release`, so a developer running the
    GUI from source got whatever menubar was last shipped, indefinitely.
    """
    bundled = _resolve_bundled_binary("divoom-menubar")
    if bundled:
        return bundled
    from divoom_client import binary_resolver

    found = binary_resolver.resolve("divoom-menubar")
    return str(found) if found else None


def _spawn_menubar_agent() -> None:
    """Best-effort: launch the native Rust menu-bar agent (divoom-menubar)
    alongside the GUI so its status item appears on launch. The agent talks to the
    daemon over the socket and relaunches THIS GUI on demand, so we hand it our
    launch command via env (DIVOOM_GUI_PYTHON/SCRIPT). Detached + dupe-guarded;
    never blocks or fails the GUI if it can't start. macOS only."""
    if sys.platform != "darwin":
        return
    try:
        import subprocess
        # Don't spawn a second status item if one is already running. Match the
        # EXACT process name (-x), not a loose command-line substring (-f): under
        # LaunchServices (`open` / Finder / Dock) some coalition process
        # transiently carries "divoom-menubar" in its args, so `-f` false-matched
        # and the agent never launched (no tray icon on a normal launch). `-x`
        # matches only a real `divoom-menubar` process, path-independent.
        existing = subprocess.run(
            ["pgrep", "-x", "divoom-menubar"],
            capture_output=True, text=True,
        )
        if existing.returncode == 0 and existing.stdout.strip():
            logger.info("Menu-bar agent already running; not spawning another.")
            return
        binary = _resolve_menubar_binary()
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
            env["DIVOOM_GUI_SCRIPT"] = str(Path(__file__).resolve())
        subprocess.Popen(
            [binary],
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Launched native Rust menu-bar agent (divoom-menubar).")
    except Exception as e:
        logger.warning(f"Could not launch menu-bar agent: {e}")


def _terminate_menubar_agent() -> None:
    """Terminate the native menu-bar agent (divoom-menubar) on a shared-lifecycle
    quit. It's spawned detached and does NOT self-terminate on the daemon's
    shutdown broadcast, so without this it orphans to launchd — a stale tray icon
    that also survives a `brew upgrade`. Best-effort; macOS only; never raises.
    Gated by :func:`lifecycle_config.should_quit_menubar_on_exit`."""
    if sys.platform != "darwin":
        return
    try:
        import subprocess
        subprocess.run(["pkill", "-f", "divoom-menubar"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False, timeout=3)
        logger.info("Terminated menu-bar agent (shared-lifecycle quit).")
    except Exception as e:
        logger.debug(f"menu-bar terminate skipped: {e}")


if __name__ == "__main__":
    main()
