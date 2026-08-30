#!/usr/bin/env python3
"""Drive the REAL GUI against a REAL daemon, and report what a user would see.

Green tests said the app worked. Launching it took twenty minutes and found
three defects, the worst of which killed the daemon on startup (v0.28.1). This
script is that twenty minutes, made repeatable.

    scripts/gui_pov.py                     # widgets tab, screenshot + report
    scripts/gui_pov.py --widget sysmon     # select a widget first
    scripts/gui_pov.py --kill-daemon       # then kill it, to check honesty
    scripts/gui_pov.py --out /tmp/shots    # where screenshots land

WHAT IT WIRES UP (no mocks anywhere in the chain):

    divoomd (real binary, isolated temp socket)
        ^  unix socket
    tests/e2e_gui_bridge.py -- HOME redirected to a throwaway dir, instantiates
        the REAL DivoomGuiAPI, serves it over HTTP
        ^  fetch
    camoufox loading the REAL web_ui/index.html, window.pywebview.api proxied
        to that bridge

The HOME redirect is not optional: without it this reads and writes the user's
live `~/.config/divoom-control/`, which a running GUI or menubar session may be
using at the same time.

WHAT IT CHECKS, beyond "did it render":

  * the daemon is still ALIVE afterwards -- a request returning a reply does not
    mean the process survived it (that is exactly how the v0.28.1 crash hid);
  * a live value actually MOVES -- a card showing a plausible number that never
    changes is indistinguishable from a working one in a screenshot, which is
    how the frozen System Monitor hid;
  * with `--kill-daemon`, that the UI SAYS the backend is gone rather than
    leaving the last good values on screen looking current.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

INDEX_HTML = REPO / "divoom_gui" / "web_ui" / "index.html"
BRIDGE = REPO / "tests" / "e2e_gui_bridge.py"

# Same proxy the real-daemon e2e suite uses: every window.pywebview.api call
# becomes an HTTP call into the real Python GUI backend.
# Every api call is recorded with a timestamp. When the backend dies mid-run,
# "what did the UI ask for just before it went" is the whole diagnosis, and
# guessing at it from the outside costs hours.
SHIM = """
window.__api = {};
window.__calls = [];
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    window.__calls.push({t: Date.now(), m: String(name)});
    if (window.__calls.length > 400) window.__calls.shift();
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return fetch(window.__BRIDGE_URL__ + '/call', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: name, args: args}),
    }).then(r => r.json()).then(d => { if (d.error) throw new Error(d.error); return d.result; });
}})};
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _links_corebluetooth(binary: Path) -> bool:
    try:
        out = subprocess.run(["otool", "-L", str(binary)],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    return "corebluetooth" in out.lower()


def _divoomd() -> Path:
    from tests.support.daemon_binary import find_divoomd

    found = find_divoomd()
    if found is None:
        sys.exit("divoomd is not built. Run: cargo build -p divoomd --no-default-features")
    if sys.platform == "darwin" and _links_corebluetooth(found):
        print(f"WARNING: {found} links CoreBluetooth.\n"
              "  macOS Bluetooth access is granted per RESPONSIBLE PROCESS. A daemon\n"
              "  launched from a shell has no grant, so the first BLE scan the GUI\n"
              "  triggers gets the process killed with SIGABRT and NO message --\n"
              "  which reads exactly like a crash in your change and is not one.\n"
              "  (The real app is fine: the GUI launches the daemon and holds the grant.)\n"
              "  Build a BLE-free daemon for this harness:\n"
              "      cargo build -p divoomd --no-default-features\n"
              "  NOTE: `cargo test` rebuilds target/debug/divoomd WITH default features,\n"
              "  so re-run that build after any test run.\n", file=sys.stderr)
    return found


class Stack:
    """The daemon + bridge pair, torn down by PID and never by pkill."""

    def __init__(self, log_dir: Path) -> None:
        # A directory plus a name that does not exist yet. NamedTemporaryFile
        # would CREATE a regular file, and the daemon refuses to unlink one of
        # those by design.
        self.dir = tempfile.mkdtemp(prefix="divoom_pov_")
        self.socket_path = str(Path(self.dir) / "daemon.sock")
        self.home = tempfile.mkdtemp(prefix="divoom_pov_home_")
        self.port = _free_port()

        # Daemon stderr goes to a FILE, not a pipe. A pipe read after the fact
        # can lose output when the process aborts, and an unread pipe blocks the
        # writer once its buffer fills -- both of which turn "the daemon died"
        # into a mystery. The log stays on disk to be read afterwards.
        self.daemon_log = log_dir / "divoomd.stderr.log"
        self._daemon_log_fh = open(self.daemon_log, "w")
        self.daemon = subprocess.Popen(
            [str(_divoomd()), "--socket", self.socket_path],
            stdout=subprocess.DEVNULL, stderr=self._daemon_log_fh, text=True,
            # A backtrace costs nothing here and is the difference between
            # "the daemon died" and knowing which call killed it.
            env={**os.environ, "RUST_BACKTRACE": os.environ.get("RUST_BACKTRACE", "full")})
        self._await_socket()

        self.bridge = subprocess.Popen(
            [sys.executable, str(BRIDGE), "--socket-path", self.socket_path,
             "--port", str(self.port), "--fake-home", self.home],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self._await_http()

    def _await_socket(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(self.socket_path):
                return
            if self.daemon.poll() is not None:
                sys.exit(f"divoomd exited: {self._why_no_daemon()}")
            time.sleep(0.05)
        sys.exit(f"divoomd never bound {self.socket_path}: {self._why_no_daemon()}")

    def _why_no_daemon(self) -> str:
        """The daemon's own account, which it writes precisely so we can say it."""
        code = self.daemon.poll()
        prefix = f"exit code {code}; " if code is not None else ""
        report = Path(f"{self.socket_path}.failure")
        if report.exists():
            recorded = " / ".join(
                x.strip() for x in report.read_text().splitlines() if x.strip())
            return prefix + recorded
        try:
            self._daemon_log_fh.flush()
        except Exception:
            pass
        err = self.daemon_log.read_text(errors="replace") if self.daemon_log.exists() else ""
        if not err.strip():
            return prefix + "no stderr"
        # Surface the PANIC line, not the tail. Truncating a subject's error
        # output to its last N characters throws away the one line that names
        # the fault whenever a backtrace follows it.
        panic = [ln for ln in err.splitlines()
                 if "panic" in ln.lower() or "Cannot drop" in ln
                 or "abort" in ln.lower()]
        if panic:
            frames = [ln.strip() for ln in err.splitlines()
                      if "divoomd::" in ln or "nowplaying::" in ln][:4]
            return (prefix + " | ".join(x.strip() for x in panic[:3])
                    + (f"  [frames: {' <- '.join(frames)}]" if frames else "")
                    + f"  (full log: {self.daemon_log})")
        return prefix + err.strip()[-400:] + f"  (full log: {self.daemon_log})"

    def _await_http(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                # A raw TCP connect, NOT an HTTP GET: the bridge only answers
                # POST, so a GET raises and would be mistaken for "not up yet"
                # forever -- the server running perfectly the whole time.
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                if self.bridge.poll() is not None:
                    err = self.bridge.stderr.read() if self.bridge.stderr else ""
                    sys.exit(f"GUI bridge exited: {(err or '')[-800:]}")
                time.sleep(0.05)
        # Say WHY, not just "never opened". A harness that hides its subject's
        # own error message is the thing this script exists to stop doing.
        self.bridge.terminate()
        try:
            _, err = self.bridge.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.bridge.kill()
            _, err = self.bridge.communicate(timeout=3)
        sys.exit(f"GUI bridge never opened port {self.port} in {timeout}s: "
                 f"{(err or '(no stderr)').strip()[-1200:]}")

    def note_tcc_if_likely(self, called: list) -> None:
        """SIGABRT + empty stderr + a BLE call = macOS TCC, not a code defect.

        Rust panics always print. An abort with nothing on stderr, right after
        the UI asked for a scan, is the OS killing an unentitled process. Saying
        so here is the difference between a five-minute answer and an hour spent
        bisecting a daemon that was never broken.
        """
        if self.daemon.poll() != -6:
            return
        log = self.daemon_log.read_text(errors="replace") if self.daemon_log.exists() else ""
        if "panic" in log.lower():
            return  # a real panic; let the normal report speak
        if not any("scan" in c or "connect" in c for c in called[-30:]):
            return
        print("\nLIKELY CAUSE: macOS Bluetooth TCC, not a bug in the daemon.\n"
              "  SIGABRT with an empty stderr is the OS killing the process; a Rust\n"
              "  panic would have printed. The UI asked for a scan, and a\n"
              "  shell-launched daemon has no Bluetooth grant.\n"
              "  Rebuild BLE-free and re-run:\n"
              "      cargo build -p divoomd --no-default-features\n", file=sys.stderr)

    @property
    def daemon_alive(self) -> bool:
        return self.daemon.poll() is None

    def kill_daemon(self) -> None:
        self.daemon.terminate()
        try:
            self.daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.daemon.kill()

    def close(self) -> None:
        for proc in (self.bridge, self.daemon):
            if proc.poll() is None:
                proc.terminate()
        for proc in (self.bridge, self.daemon):
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


async def run(args) -> int:
    from playwright.async_api import async_playwright

    from tests.support.browser import add_init_js, eval_js, launch, wait_js

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stack = Stack(out)
    problems: list[str] = []

    try:
        async with async_playwright() as p:
            browser = await launch(p)
            page = await browser.new_page(viewport={"width": 1440, "height": 960})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            await add_init_js(page, f"window.__BRIDGE_URL__ = 'http://127.0.0.1:{stack.port}';\n" + SHIM)
            await page.goto(f"file://{INDEX_HTML}")
            await page.wait_for_load_state("domcontentloaded")
            await wait_js(page, "() => !!window.DivoomState")
            await page.click('.nav-btn[data-tab="data-sources"]')
            await page.wait_for_selector("#widget-card-sysmon")

            if args.widget:
                await eval_js(page, f"() => document.getElementById('widget-card-{args.widget}')?.click()")
                await page.wait_for_timeout(1500)
                selected = await eval_js(page, f"() => window.selectedWidgetIs?.('{args.widget}')")
                print(f"selected {args.widget}: {selected}")
                if selected is not True:
                    problems.append(f"clicking the {args.widget} card did not select it")

            # Is the live refresh actually RUNNING? A frozen card looks identical
            # to a working one in any single screenshot.
            #
            # Count the refresh CALLS, do not watch the value. A busy machine
            # can legitimately sit at 100% for ten seconds, and "the number did
            # not change" cannot tell that apart from "nothing is refreshing" --
            # measured that false positive on the first run of this check.
            before = await eval_js(page, "() => (window.__calls || []).length")
            samples = []
            for _ in range(4):
                samples.append(await eval_js(
                    page, "() => document.getElementById('sysmon-cpu')?.textContent"))
                await page.wait_for_timeout(2500)
            refreshes = await eval_js(page, f"""() => (window.__calls || [])
                .slice({before})
                .filter(c => c.m === 'get_system_stats_preview').length""")
            print(f"sysmon cpu over ~10s: {samples}  (refresh calls: {refreshes})")
            if args.widget == "sysmon" and refreshes < 2:
                problems.append(
                    f"the sysmon live refresh is not running — only {refreshes} "
                    f"get_system_stats_preview call(s) in ~10s with the widget selected")

            if args.kill_daemon:
                print("killing the daemon; the UI must SAY so, not go quiet")
                stack.kill_daemon()
                await page.wait_for_timeout(9000)
                state = await eval_js(page, """() => ({
                    note: document.getElementById('sysmon-unavailable')?.textContent || '',
                    cpu: document.getElementById('sysmon-cpu')?.textContent,
                    img: document.getElementById('sysmon-device-preview')?.style.display })""")
                print("after daemon death:", json.dumps(state))
                if not state.get("note"):
                    problems.append("daemon is gone and the System Monitor card says nothing")
                await page.screenshot(path=str(out / "gui_pov_unavailable.png"))
            else:
                await page.screenshot(path=str(out / "gui_pov.png"), full_page=True)
                # A request that returns is not proof the process survived it.
                if not stack.daemon_alive:
                    calls = await eval_js(page, "() => window.__calls || []")
                    stack.note_tcc_if_likely([c["m"] for c in calls])
                    tail = " -> ".join(c["m"] for c in calls[-25:])
                    (out / "api_calls.json").write_text(json.dumps(calls, indent=1))
                    problems.append(
                        f"the daemon DIED while the GUI was driving it: "
                        f"{stack._why_no_daemon()}\n"
                        f"    last api calls: {tail}\n"
                        f"    full call log: {out / 'api_calls.json'}")

            if errors:
                problems.append(f"{len(errors)} page/console error(s): {errors[:3]}")
            await browser.close()
    finally:
        stack.close()

    print()
    if problems:
        print("PROBLEMS:")
        for p_ in problems:
            print(f"  - {p_}")
        return 1
    print(f"OK — screenshots in {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--widget", default="sysmon",
                    help="widget card to select first (sysmon, music, stock, weather)")
    ap.add_argument("--kill-daemon", action="store_true",
                    help="kill the daemon mid-session and check the UI says so")
    ap.add_argument("--out", default="/tmp/divoom_gui_pov",
                    help="directory for screenshots")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
