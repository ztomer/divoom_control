"""Real daemon <-> real GUI e2e: connect/disconnect feedback correctness (R61 follow-up).

The existing e2e suite (test_e2e_ux_feedback.py etc.) drives the real web_ui
against a fully JS-side mock of window.pywebview.api — no daemon is ever
involved, so nothing verifies that the ACTUAL divoom_gui backend code
(ConnectionApi/ScannerMixin) round-trips through a REAL daemon and produces
correct UI feedback. This file closes that gap.

Isolation, mirroring tests/test_rust_daemon_parity.py's proven pattern (PID-
tracked subprocess, never `pkill -f` — see the R61 CHANGELOG entry for why
that pattern is unsafe):
  - A real `divoomd` binary is spawned on a unique temp socket path, PID
    tracked directly, torn down by PID (never pkill). Skips cleanly if no
    binary is built (matches test_rust_daemon_parity.py).
  - The GUI backend runs in a SEPARATE subprocess (tests/e2e_gui_bridge.py)
    with HOME redirected to a throwaway directory, so it can never read/write
    the user's real ~/.config/divoom-control/ or touch the default
    /tmp/divoom.sock a live session might be using.
  - The mock BLE/LAN transport (`connect` with `{"mock": true}`, and the new
    `mock_simulate_drop` command) means no real hardware is touched.

Uses the daemon's mock transport (not connect_single_device's own MAC/LAN
path) to ESTABLISH connection state — connect_single_device has no "mock"
knob, so exercising it fully would need real BLE/LAN hardware. What this
file verifies end-to-end for real: the GUI's honest status read-back
(get_connection_state), the polling heartbeat (refreshConnectionState), and
the live event-driven path (window.Divoom.onDaemonEvent) against the REAL
event shapes divoomd actually broadcasts — the layer that actually decides
what feedback the user sees. It also drives one real connect FAILURE
end-to-end through connect_single_device itself (an unreachable LAN IP),
which needs no mock transport.

Skipped if Playwright / a browser isn't installed, or no divoomd binary is
built (`cargo build` in divoomd/ first).
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_client.daemon_protocol import DaemonClient
from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

REPO_ROOT = Path(__file__).parent.parent
INDEX_HTML = REPO_ROOT / "divoom_gui" / "web_ui" / "index.html"
BRIDGE_SCRIPT = REPO_ROOT / "tests" / "e2e_gui_bridge.py"

# window.__api.* is left in place as an ESCAPE HATCH some tests use for
# scenarios the bridge can't reach (e.g. get_device_name — cosmetic, not
# state); everything else proxies to the real Python GUI backend over HTTP.
_REAL_BRIDGE_API = """
window.__api = {};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return fetch(window.__BRIDGE_URL__ + '/call', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: name, args: args}),
    }).then(r => r.json()).then(d => {
        if (d.error) throw new Error(d.error);
        return d.result;
    });
}})};
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_rust_binary() -> Path | None:
    for folder in ("release", "debug"):
        candidate = REPO_ROOT / "target" / folder / "divoomd"
        if candidate.exists():
            return candidate
    return None


class _IsolatedStack:
    """Owns the daemon + bridge subprocesses; kills only its own PIDs."""

    def __init__(self, bin_path: Path):
        self.socket_path = f"/tmp/divoomd_e2e_gui_{os.getpid()}.sock"
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        self.bridge_port = _free_port()
        self.fake_home = tempfile.mkdtemp(prefix="divoom_e2e_home_")
        self.bridge_url = f"http://127.0.0.1:{self.bridge_port}"

        self.daemon_proc = subprocess.Popen(
            [str(bin_path), "--socket", self.socket_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self._wait_for_socket(self.socket_path)

        self.bridge_proc = subprocess.Popen(
            [sys.executable, str(BRIDGE_SCRIPT),
             "--socket-path", self.socket_path,
             "--port", str(self.bridge_port),
             "--fake-home", self.fake_home],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self._wait_for_http(self.bridge_port)

        self.client = DaemonClient(self.socket_path)

    def _wait_for_socket(self, path: str, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(path):
                return
            if self.daemon_proc.poll() is not None:
                out, err = self.daemon_proc.communicate(timeout=1.0)
                pytest.fail(f"divoomd exited early. stdout={out} stderr={err}")
            time.sleep(0.05)
        pytest.fail(f"divoomd never bound {path}")

    # Generous: the bridge is a fresh interpreter that cold-imports the whole
    # divoom_gui stack (bleak, pyobjc, PIL, aiohttp) before it binds. That is
    # sub-second warm locally but seconds on a cold CI runner under load, so a
    # tight timeout produced spurious "never opened port" errors.
    def _wait_for_http(self, port: int, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                if self.bridge_proc.poll() is not None:
                    out, err = self.bridge_proc.communicate(timeout=1.0)
                    pytest.fail(f"e2e_gui_bridge exited early. stdout={out} stderr={err}")
                time.sleep(0.05)
        # Still alive but never bound — kill it and surface its output so a real
        # hang is diagnosable rather than an opaque timeout.
        self.bridge_proc.terminate()
        try:
            out, err = self.bridge_proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            self.bridge_proc.kill()
            out, err = self.bridge_proc.communicate(timeout=2.0)
        pytest.fail(
            f"e2e_gui_bridge never opened port {port} in {timeout}s. "
            f"stdout={out} stderr={err}")

    def close(self) -> None:
        for proc in (self.bridge_proc, self.daemon_proc):
            proc.terminate()
        for proc in (self.bridge_proc, self.daemon_proc):
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)


class _EventRelay:
    """Runs DaemonClient.subscribe() on a background thread and forwards each
    event into the real browser page via window.Divoom.onDaemonEvent — the
    same call path the production GUI's daemon subscription drives (R58)."""

    def __init__(self, client: DaemonClient, page, loop: asyncio.AbstractEventLoop):
        self._client = client
        self._page = page
        self._loop = loop
        self._stop = threading.Event()
        self.received: list[dict] = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._client.subscribe(on_event=self._on_event, should_stop=self._stop.is_set)

    def _on_event(self, ev: dict) -> None:
        self.received.append(ev)
        fut = asyncio.run_coroutine_threadsafe(
            eval_js(
                self._page,
                "(ev) => { if (window.Divoom && window.Divoom.onDaemonEvent) "
                "window.Divoom.onDaemonEvent(ev); }", ev),
            self._loop)
        try:
            fut.result(timeout=2.0)
        except Exception:
            pass  # page may be mid-navigation/closing; not a relay failure

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)


@pytest.fixture
def gui_daemon_stack():
    require_browser()
    # This suite is unique among the e2e files: it spins up the REAL
    # divoom_gui backend (DivoomGuiAPI) in the bridge subprocess. Importing it
    # pulls in pywebview (`import webview`), which initializes Cocoa and hangs
    # without a macOS Aqua/GUI session — which the headless GitHub runner does
    # not have (the bridge never binds its port; see _wait_for_http). The other
    # e2e files use a JS-side mock of pywebview.api and run fine in CI. Skip
    # here on CI and keep running locally where a session exists.
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.skip(
            "real-DivoomGuiAPI bridge needs a macOS GUI (Aqua) session; "
            "pywebview import hangs on headless CI. Runs locally.")
    bin_path = _find_rust_binary()
    if bin_path is None:
        pytest.skip("Rust divoomd binary not found. Run `cargo build` in divoomd/ first.")
    stack = _IsolatedStack(bin_path)
    try:
        yield stack
    finally:
        stack.close()


async def _open(p, stack):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, 
        f"window.__BRIDGE_URL__ = {json.dumps(stack.bridge_url)};\n" + _REAL_BRIDGE_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.refreshConnectionState")
    return browser, page


async def _dot_class(page) -> str:
    return await eval_js(page, 
        "() => document.getElementById('global-status-dot').className")


@pytest.mark.asyncio
async def test_real_connect_then_refresh_shows_active_dot(gui_daemon_stack):
    """Mock-connect on the REAL daemon; the GUI's real get_connection_state +
    refreshConnectionState must turn the dot active — no JS mock involved."""
    from playwright.async_api import async_playwright

    stack = gui_daemon_stack
    reply = stack.client.send_command("connect", {"mock": True})
    assert reply.get("success") is True, reply

    async with async_playwright() as p:
        browser, page = await _open(p, stack)
        try:
            await eval_js(page, "() => { window.DivoomState.appConnected = true; }")
            await eval_js(page, "() => window.refreshConnectionState()")
            await wait_js(page, 
                "() => document.getElementById('global-status-dot')"
                ".className === 'transport-dot active ble'", timeout=4000)
            assert (await _dot_class(page)).split() == ["transport-dot", "active", "ble"]

            state = await eval_js(page, 
                "() => window.pywebview.api.get_connection_state()"
                ".then(r => JSON.parse(r))")
            assert state == {"connected": True, "state": "connected"}
        finally:
            await browser.close()


def _simulate_drop_or_skip(stack):
    """Send mock_simulate_drop, skipping if the native daemon hasn't implemented
    it yet. It's the hardware-free drop hook these tests hang on; without it
    there is nothing to exercise, so skip (like the playwright/binary guards)
    rather than hard-fail until divoomd grows the command."""
    reply = stack.client.send_command("mock_simulate_drop", {})
    if not reply.get("success") and "not implemented" in str(reply.get("error", "")):
        pytest.skip(f"divoomd lacks mock_simulate_drop yet: {reply.get('error')}")
    assert reply.get("success") is True, reply
    return reply


@pytest.mark.asyncio
async def test_real_drop_then_refresh_shows_inactive_dot(gui_daemon_stack):
    """After mock_simulate_drop settles, device_status reports disconnected
    (the transient 'degraded' broadcast is covered by the event-relay test
    below, not by polling — degraded never lingers long enough to poll)."""
    from playwright.async_api import async_playwright

    stack = gui_daemon_stack
    assert stack.client.send_command("connect", {"mock": True}).get("success") is True
    drop_reply = _simulate_drop_or_skip(stack)
    assert drop_reply.get("connection_state") == "disconnected"

    async with async_playwright() as p:
        browser, page = await _open(p, stack)
        try:
            await eval_js(page, "() => { window.DivoomState.appConnected = true; }")
            await eval_js(page, "() => window.refreshConnectionState()")
            # Wait on the flag this test actually asserts, not on the dot.
            # The dot and appConnected are separate updates, and the dot may
            # ALREADY be inactive when we arrive — in which case waiting on it
            # returns instantly, before refreshConnectionState() has flipped the
            # flag, and the assertion below races. Same class as the
            # LAN-failure test above; it surfaced when R66 moved these suites
            # to camoufox/Firefox, where the ordering differs from Chromium.
            await wait_js(page, 
                "() => window.DivoomState.appConnected === false", timeout=4000)
            await wait_js(page, 
                "() => document.getElementById('global-status-dot')"
                ".className === 'transport-dot inactive'", timeout=4000)
            assert await eval_js(page, 
                "() => document.getElementById('global-status-dot').title") == "Disconnected"
            assert await eval_js(page, 
                "() => window.DivoomState.appConnected") is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_real_event_relay_degraded_then_disconnected(gui_daemon_stack):
    """The transient DEGRADED broadcast (only observable live, not via
    polling) reaches window.Divoom.onDaemonEvent with the REAL shape divoomd
    sends, and the dot goes amber before settling to inactive -- verifies the
    daemon's broadcast shape and the GUI's event handler actually agree."""
    from playwright.async_api import async_playwright

    stack = gui_daemon_stack
    assert stack.client.send_command("connect", {"mock": True}).get("success") is True

    async with async_playwright() as p:
        browser, page = await _open(p, stack)
        relay = None
        try:
            await eval_js(page, "() => { window.DivoomState.appConnected = true; }")
            loop = asyncio.get_running_loop()
            relay = _EventRelay(stack.client, page, loop)
            await asyncio.sleep(0.2)  # let the subscribe connection establish

            _simulate_drop_or_skip(stack)

            await wait_js(page, 
                "() => document.getElementById('global-status-dot')"
                ".className === 'transport-dot inactive'", timeout=4000)

            states = [ev.get("state") for ev in relay.received if ev.get("type") == "status"]
            assert "degraded" in states, f"never saw a live degraded broadcast: {states}"
            assert states[-1] == "disconnected", f"did not settle disconnected: {states}"
        finally:
            if relay is not None:
                relay.stop()
            await browser.close()


@pytest.mark.asyncio
async def test_real_connect_single_device_failure_unreachable_lan(gui_daemon_stack):
    """No mock transport involved: connect_single_device really asks the
    daemon to reach an unreachable LAN IP, really fails, and the honest
    daemon error really reaches the toast via get_last_connect_error."""
    from playwright.async_api import async_playwright

    stack = gui_daemon_stack

    async with async_playwright() as p:
        browser, page = await _open(p, stack)
        try:
            await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address: 'LAN:127.0.0.1', name: 'Unreachable'}];
                window.renderDeviceDots && window.renderDeviceDots();
                window.connectDevice('Unreachable', 'LAN:127.0.0.1');
            }""")
            # Wait for the CONDITION BEING ASSERTED (the error toast), not a
            # proxy for it. This used to wait on the status dot flipping to
            # inactive and then read the toast, assuming the error toast had
            # landed by then. Those are two independent DOM updates, so the
            # assumption was an engine-timing coincidence: it held on Chromium
            # and broke the moment R66 moved these suites to camoufox/Firefox,
            # where the dot settles first and the read caught the earlier
            # SUCCESS "Connecting to Unreachable..." toast.
            #
            # Waiting on the real signal does not weaken the test -- if the app
            # never raises the error toast, this times out and fails, which is
            # exactly the regression worth catching.
            await wait_js(page, 
                "() => document.getElementById('toast').className.split(' ')"
                ".includes('error')", timeout=8000)
            toast = await eval_js(page, 
                "() => ({c: document.getElementById('toast').className,"
                "        t: document.getElementById('toast').textContent})")
            assert "error" in toast["c"].split()
            assert "Unreachable" in toast["t"]
            # The dot must still settle inactive — kept as a separate assertion
            # rather than as the (mis-used) synchronisation signal.
            await wait_js(page, 
                "() => document.getElementById('global-status-dot')"
                ".className === 'transport-dot inactive'", timeout=4000)
        finally:
            await browser.close()
