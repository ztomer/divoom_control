"""HTTP bridge for real-daemon GUI e2e tests (R61 follow-up).

The existing Playwright e2e suite (test_e2e_ux_feedback.py etc.) drives the
real ``web_ui/index.html`` against a fully JS-side mock of
``window.pywebview.api`` — no daemon, no Python GUI backend is ever touched.
That leaves a real gap: nothing verifies the ACTUAL ``divoom_gui`` backend
code (``ConnectionApi`` / ``ScannerMixin``) round-trips correctly through a
REAL daemon and produces the UI feedback the frontend expects.

This module runs as a SEPARATE PROCESS (spawned by the test, not imported
in-process) that:
  1. Isolates ``HOME`` to a throwaway directory FIRST (before any divoom_gui
     import), so nothing here ever reads/writes the user's real
     ``~/.config/divoom-control/`` — that directory is shared with a possibly
     live GUI/menubar session and must not be touched by a test.
  2. Monkeypatches ``divoom_gui.daemon_bridge.ensure_daemon``/``daemon_alive``
     (the exact names looked up via the local ``from ... import`` at each
     call site in ConnectionApi/ScannerMixin — patching the daemon_client
     module instead would miss those rebound names) so the GUI backend talks
     ONLY to the isolated daemon socket the test spawned, never the default
     ``/tmp/divoom.sock`` a live session might be using.
  3. Instantiates the real ``DivoomGuiAPI`` and serves it over a tiny local
     HTTP bridge: ``POST /call/<method>`` with a JSON array body invokes
     ``getattr(api, method)(*args)`` and returns ``{"result": ...}``.
     ``POST /daemon_send_command`` with ``{"command": ..., "args": {...}}``
     goes straight to the same isolated ``DaemonClient`` for setup/assertion
     calls that aren't part of the GUI's own JS-facing API (e.g. the mock
     transport's connect/mock_simulate_drop commands).

A Playwright test then replaces the JS-side canned-response mock with a real
``fetch()`` proxy to this bridge, so ``window.pywebview.api.connect_single_
device(...)`` etc. really executes the production GUI code path against a
real (but fully isolated) daemon.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _make_handler(api, isolated_socket_path: str):
    from divoom_gui.daemon_bridge import DaemonClient

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
            pass  # keep test output quiet; failures surface via HTTP status

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # The test page loads via file:// (origin "null"); a plain
            # cross-origin fetch() from there is blocked without this, and a
            # JSON POST triggers a CORS preflight (OPTIONS) that must also
            # succeed — see do_OPTIONS below. Without both, every fetch()
            # silently fails and the page's own .catch(() => {}) swallows it,
            # so the test looks like it ran but never actually reached here.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            return json.loads(raw) if raw else None

        def do_OPTIONS(self):  # noqa: N802 - stdlib method name
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):  # noqa: N802 - stdlib method name
            try:
                if self.path == "/call":
                    body = self._read_json() or {}
                    method_name, args = body["method"], body.get("args", [])
                    method = getattr(api, method_name)
                    self._send_json(200, {"result": method(*args)})
                elif self.path == "/daemon_send_command":
                    body = self._read_json() or {}
                    client = DaemonClient(isolated_socket_path)
                    reply = client.send_command(body["command"], body.get("args"))
                    self._send_json(200, {"result": reply})
                else:
                    self._send_json(404, {"error": f"no such endpoint: {self.path}"})
            except Exception as e:  # surfaced to the test, not swallowed
                self._send_json(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket-path", required=True,
                         help="Isolated daemon Unix socket path this bridge must exclusively use.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--fake-home", required=True,
                         help="Throwaway HOME so ~/.config/divoom-control is never touched.")
    args = parser.parse_args()

    # Must happen before ANY divoom_gui/divoom_lib import — Path.home() is
    # read at call time by those modules, but setting this first is the only
    # way to be certain nothing sneaks in an early home-relative path.
    os.environ["HOME"] = args.fake_home
    Path(args.fake_home).mkdir(parents=True, exist_ok=True)

    from divoom_gui import daemon_bridge

    real_ensure_daemon = daemon_bridge.ensure_daemon
    real_daemon_alive = daemon_bridge.daemon_alive

    def _isolated_ensure_daemon(*_a, **_kw):
        return real_ensure_daemon(args.socket_path, spawn=False)

    def _isolated_daemon_alive(*_a, **_kw):
        return real_daemon_alive(args.socket_path)

    # Patches the module attribute that ConnectionApi/ScannerMixin resolve via
    # their own local `from divoom_gui.daemon_bridge import ensure_daemon` at
    # call time — must target this exact module, not daemon_client.py (a
    # patch there wouldn't reach this already-rebound name).
    with mock.patch.object(daemon_bridge, "ensure_daemon", _isolated_ensure_daemon), \
         mock.patch.object(daemon_bridge, "daemon_alive", _isolated_daemon_alive):
        from divoom_gui.gui_api import DivoomGuiAPI
        api = DivoomGuiAPI()

        handler_cls = _make_handler(api, args.socket_path)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_cls)
        print(f"e2e_gui_bridge: serving on 127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
