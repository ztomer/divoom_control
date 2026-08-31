"""Base classes for the API collaborator pattern (REVIEW §1.2).

The old `DivoomGuiAPI` was a 891-line God Object assembled from three
fat-interface mixins. This module provides the lightweight foundation
for splitting it into independent, testable collaborators.
"""
from __future__ import annotations

import asyncio
import threading
import logging

logger = logging.getLogger("divoom_gui.api")



def _lan_error(what: str, reason: str, cause: str) -> dict:
    """One place that phrases a LAN failure (mirrors `_cloud_error`)."""
    logger.error("%s unavailable (%s): %s", what, cause, reason)
    return {"ok": False, "error": f"Could not {what}: {reason}", "cause": cause}


class AsyncLoopThread(threading.Thread):
    """Single shared asyncio loop for all device-bound coroutines.

    Kept as a shared resource so all API collaborators run on the same
    event loop (the loop is thread-local and doesn't conflict with
    pywebview's main thread).
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class ApiBase:
    """Common base for all API collaborators.

    Provides:
    - shared reference to the async loop thread
    - shared reference to the daemon client (lazy, cached)
    - shared wall/single target resolution + dispatch
    - `_run_async` / `_schedule_async` helpers
    """

    def __init__(self, loop_thread: AsyncLoopThread, daemon_client_getter, state_getter):
        self._loop_thread = loop_thread
        self._daemon_client_getter = daemon_client_getter  # callable returning DaemonClient | None
        self._state_getter = state_getter  # callable returning dict with current_divoom, wall_instance, current_target_mode, wall_slots

    @property
    def _client(self):
        return self._daemon_client_getter()

    @property
    def _current_divoom(self):
        return self._state_getter().get("current_divoom")

    @property
    def _wall_instance(self):
        return self._state_getter().get("wall_instance")

    @property
    def _wall_slots(self):
        return self._state_getter().get("wall_slots", {})

    @property
    def _current_target_mode(self):
        return self._state_getter().get("current_target_mode", "single")

    def _rebuild_wall_instance(self, cell_size: int = 16) -> bool:
        if not self._wall_slots:
            return False
        client = self._client
        if client is None:
            logger.error("Wall build failed: no daemon available")
            return False
        from divoom_gui.daemon_bridge import DaemonDeviceProxy
        reply = client.wall_configure(self._wall_slots, cell_size=cell_size)
        if not reply.get("success") or not reply.get("wall"):
            logger.error(f"Failed to build display wall: {reply.get('error', reply)}")
            self._state_getter()["wall_instance"] = None
            return False
        self._state_getter()["wall_instance"] = DaemonDeviceProxy(client, target="wall")
        return True

    def _target(self):
        if self._current_target_mode == "wall":
            if not self._rebuild_wall_instance():
                return None
            return self._wall_instance
        return self._current_divoom

    def _lan_action(self, what: str, build_coro) -> dict:
        """Run one LAN command and report WHY it failed, not just that it did.

        R71 P3.1, and the same defect R70 fixed for cloud browse. Every
        LAN-backed panel returned a bare bool, so a user on a BLE-only device
        clicking "Send Overlay" saw "Failed to send overlay" -- indistinguishable
        from a broken feature. The daemon knew the answer the whole time ("this
        device is connected over Bluetooth, which has no LAN API") and the bool
        threw it away.

        Returns the shape `web_ui/cloud_result.js` already unwraps:
        ``{ok, error, cause}``. ``cause`` is a flag and never parsed text --
        'no_lan_capability' | 'not_configured' | 'unreachable' | 'lan' -- so the
        wording can change without moving the UI.

        This is a funnel on purpose. One place produces the shape, so a second
        LAN panel cannot invent a third way of saying "no".
        """
        from divoom_client.daemon_proxy import _DeviceCallError

        target = self._target()
        if target is None:
            return _lan_error(what, "no device is connected", "unreachable")
        try:
            self._run_async(build_coro(target))
        except _DeviceCallError as exc:
            return _lan_error(what, str(exc), exc.cause or "lan")
        except Exception as exc:
            logger.exception("%s failed", what)
            return _lan_error(what, str(exc), "lan")
        return {"ok": True, "error": "", "cause": ""}

    def _dispatch(self, build_coro):
        target = self._target()
        if target is None:
            return False
        return self._run_async(build_coro(target))

    def _run_async(self, coro, *, timeout: float = 120.0):
        # A3 (completion): bound the wait. The A3 hardening added this guard to
        # GuiApi._run_async, but EVERY actual device command goes through a
        # collaborator (LightingApi/ToolsApi/WidgetsApi/ConnectionApi) which inherits
        # THIS base method — so without the bound here a wedged async chain (daemon
        # stopped answering, hung device op) froze the pywebview JS-API thread forever
        # (a dead button, no error). On expiry cancel + raise so the GUI surfaces it.
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(coro, self._loop_thread.loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error("GUI async op timed out after %.0fs", timeout)
            raise RuntimeError(f"Operation timed out after {timeout:.0f}s")

    def _schedule_async(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self._loop_thread.loop)