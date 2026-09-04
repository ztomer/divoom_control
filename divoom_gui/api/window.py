"""WindowApi — window chrome (min/max/close) (REVIEW §1.2).

Thin façade over pywebview window.
"""
from __future__ import annotations

from divoom_gui.api import ApiBase


class WindowApi(ApiBase):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    def minimize_window(self) -> None:
        window = self._state_getter().get("window")
        if window:
            window.minimize()

    def maximize_window(self) -> None:
        window = self._state_getter().get("window")
        if window:
            window.toggle_fullscreen()

    def close_window(self) -> None:
        loop_thread = self._loop_thread
        if loop_thread:
            loop_thread.stop()
        window = self._state_getter().get("window")
        if window:
            def _destroy():
                import time
                time.sleep(0.1)
                window.destroy()
            import threading
            threading.Thread(target=_destroy, daemon=True).start()