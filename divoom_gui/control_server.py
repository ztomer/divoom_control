"""Local REST control interface for the Divoom GUI bridge.

Wraps a ``DivoomGuiAPI`` instance and exposes every public bridge method over a
localhost HTTP API. This makes the whole app **driveable headlessly** — for
automated end-to-end tests, scripting, the "run headless" hot-channel daemon
(item 4.d), and instrumented verification of features that otherwise need the
PyWebView window.

Design:
- Reflection-based dispatch: any public (non-underscore) callable on the wrapped
  API object is invokable as ``POST /api/<method>``; no per-method boilerplate,
  so new bridge methods are exposed automatically.
- Bound to 127.0.0.1 by default (local instrumentation only). An optional bearer
  token (``DIVOOM_CONTROL_TOKEN``) can gate access.

Endpoints:
- ``GET  /health``        → ``{"ok": true}``
- ``GET  /api``           → list of callable methods + signatures
- ``POST /api/<method>``  → body is a JSON object (kwargs) or array (positional);
                            returns ``{"ok": true, "result": ...}``

Run standalone:  ``python gui/control_server.py --port 8787``
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("divoom.control_server")

# Methods that require the live PyWebView window or would block — not useful (or
# safe) to drive over the headless control API.
_DENYLIST = {"run", "stop", "minimize_window", "maximize_window", "close_window"}


def list_methods(api) -> list[dict]:
    """Return metadata for every invokable public method on ``api``."""
    out = []
    for name in dir(api):
        if name.startswith("_") or name in _DENYLIST:
            continue
        attr = getattr(api, name, None)
        if not callable(attr):
            continue
        try:
            sig = str(inspect.signature(attr))
        except (TypeError, ValueError):
            sig = "(...)"
        out.append({"name": name, "signature": sig})
    return out


def _maybe_json(value):
    """Many bridge methods return a JSON *string*; decode it for convenience."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value.decode() if isinstance(value, bytes) else value
    return value


def make_handler(api, token: str | None):
    methods = {m["name"] for m in list_methods(api)}

    class Handler(BaseHTTPRequestHandler):
        server_version = "DivoomControl/1.0"

        # A client that announces a Content-Length and then stalls must not pin a
        # handler thread forever -- _drain_body() below reads on behalf of callers
        # that have NOT authenticated yet, so the read has to be bounded in time as
        # well as in size. Generous for a loopback/AF_UNIX API.
        timeout = 10

        # Ceiling on how much unread body an error path will swallow before
        # answering. Past this the reply may still race the client's write (see
        # _drain_body), but the server never reads unbounded bytes for an
        # unauthenticated peer.
        _MAX_DRAIN = 1 << 20  # 1 MiB

        # Class-level default so it is well-defined even if a request aborts
        # before handle_one_request() runs; the per-request reset lives there.
        _body_read = False

        def log_message(self, fmt, *args):  # quieter logging
            logger.debug("%s - %s", self.address_string(), fmt % args)

        def handle_one_request(self):
            # Handler instances are reused across keep-alive requests on one
            # connection, so the "did we consume this body" flag is per REQUEST.
            self._body_read = False
            return super().handle_one_request()

        def _read_body(self) -> bytes:
            """Consume the request body exactly once."""
            self._body_read = True
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def _drain_body(self) -> None:
            """Swallow an unread request body before answering.

            An error path that replies and closes while the client is still
            writing its body leaves unread bytes in the receive buffer; closing
            then sends an RST, so the client's next write fails with EPIPE and it
            never gets to READ the status code we correctly sent. The reply is
            right and unreadable -- which is how a clean 401 surfaced as
            ``BrokenPipeError`` (CI run 32655925962).

            Called from _send() rather than from each error branch on purpose: the
            three pre-body returns in do_POST were all one class, and a rule you
            have to remember at every new early return is not a rule.
            """
            if self._body_read:
                return
            self._body_read = True
            headers = getattr(self, "headers", None)
            if headers is None:
                return
            remaining = min(int(headers.get("Content-Length") or 0), self._MAX_DRAIN)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _send(self, code: int, payload: dict):
            self._drain_body()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not token:
                return True
            return self.headers.get("Authorization") == f"Bearer {token}"

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self.path == "/api":
                if not self._authorized():
                    return self._send(401, {"ok": False, "error": "unauthorized"})
                return self._send(200, {"ok": True, "methods": list_methods(api)})
            return self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return self._send(401, {"ok": False, "error": "unauthorized"})
            if not self.path.startswith("/api/"):
                return self._send(404, {"ok": False, "error": "not found"})
            method = self.path[len("/api/"):].strip("/")
            if method not in methods:
                return self._send(404, {"ok": False, "error": f"unknown method {method!r}"})

            raw = self._read_body()
            args, kwargs = [], {}
            if raw:
                try:
                    parsed = json.loads(raw)
                except ValueError as e:
                    return self._send(400, {"ok": False, "error": f"bad JSON: {e}"})
                if isinstance(parsed, dict):
                    kwargs = parsed
                elif isinstance(parsed, list):
                    args = parsed
                else:
                    args = [parsed]

            try:
                result = getattr(api, method)(*args, **kwargs)
                return self._send(200, {"ok": True, "result": _maybe_json(result)})
            except TypeError as e:
                return self._send(400, {"ok": False, "error": str(e)})
            except Exception as e:  # bridge methods already log; surface the message
                logger.exception("control API method %s failed", method)
                return self._send(500, {"ok": False, "error": str(e)})

    return Handler


def serve(api, host: str = "127.0.0.1", port: int = 8787, token: str | None = None):
    """Start a blocking control server. Returns the server (call in a thread)."""
    if token is None:
        token = os.environ.get("DIVOOM_CONTROL_TOKEN") or None
    httpd = ThreadingHTTPServer((host, port), make_handler(api, token))
    logger.info("Divoom control server listening on http://%s:%d", host, port)
    return httpd


def serve_in_background(api, host: str = "127.0.0.1", port: int = 8787, token: str | None = None):
    """Start the control server on a daemon thread; returns (httpd, thread)."""
    httpd = serve(api, host, port, token)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="divoom-control")
    thread.start()
    return httpd, thread


class _UnixHTTPServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        # BaseHTTPRequestHandler expects a (host, port)-style client address.
        request, _ = super().get_request()
        return request, ("unix", 0)


def serve_unix(api, socket_path: str, token: str | None = None):
    """Serve the same control API over a Unix domain socket. Returns the server."""
    if token is None:
        token = os.environ.get("DIVOOM_CONTROL_TOKEN") or None
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    httpd = _UnixHTTPServer(socket_path, make_handler(api, token))
    logger.info("Divoom control server listening on unix:%s", socket_path)
    return httpd


def serve_unix_in_background(api, socket_path: str, token: str | None = None):
    httpd = serve_unix(api, socket_path, token)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="divoom-control-unix")
    thread.start()
    return httpd, thread


class _UnixHTTPConnection:
    """Minimal HTTP-over-unix-socket client (no external deps)."""

    def __init__(self, path):
        import http.client

        class _Conn(http.client.HTTPConnection):
            def connect(_self):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(path)
                _self.sock = s

        self._conn = _Conn("localhost")

    def request(self, method, url, body=None, headers=None):
        return self._conn.request(method, url, body, headers or {})

    def getresponse(self):
        return self._conn.getresponse()


def call(method: str, *args, base_url: str | None = None, socket_path: str | None = None,
         token: str | None = None, timeout: float = 30.0, **kwargs):
    """Invoke a control-server method over TCP (base_url) or a unix socket.

    Pass either positional ``*args`` (sent as a JSON array) or ``**kwargs`` (sent
    as a JSON object). Returns the decoded ``result`` (raising on error)."""
    import http.client

    payload = json.dumps(kwargs if kwargs else list(args)).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    path = f"/api/{method}"

    if socket_path:
        conn = _UnixHTTPConnection(socket_path)
        conn.request("POST", path, payload, headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
    else:
        url = (base_url or "http://127.0.0.1:8787").rstrip("/")
        host = url.split("://", 1)[1]
        conn = http.client.HTTPConnection(host, timeout=timeout)
        conn.request("POST", path, payload, headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())

    if not data.get("ok"):
        raise RuntimeError(data.get("error", "control call failed"))
    return data.get("result")


def _build_api():
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from gui_main import DivoomGuiAPI
    return DivoomGuiAPI()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Divoom GUI control REST server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", default=None, help="optional bearer token")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    api = _build_api()
    httpd = serve(api, args.host, args.port, args.token)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
