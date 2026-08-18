"""R53.29: GUI/IPC findings from the convergence adversarial pass.

- ApiBase._run_async (used by EVERY device command via the collaborator API
  classes) had no timeout — the A3 guard was only on GuiApi._run_async, which the
  commands don't use. A wedged op froze the pywebview JS thread forever.
- DaemonDeviceProxy.push_animation(bytes) leaked a /tmp/*.gif on every call.
"""
import asyncio
import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))


class _LoopThread:
    def __init__(self, loop):
        self.loop = loop


def _bg_loop():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def test_apibase_run_async_is_bounded():
    """A hung coroutine must raise (not block forever) — the A3 guard now reaches
    the base method the collaborator API classes actually inherit."""
    from divoom_gui.api import ApiBase

    loop = _bg_loop()
    api = ApiBase(_LoopThread(loop), lambda: None, lambda: {})

    async def _hang():
        await asyncio.sleep(30)

    try:
        with pytest.raises(RuntimeError, match="timed out"):
            api._run_async(_hang(), timeout=0.1)
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_apibase_run_async_returns_value_on_success():
    from divoom_gui.api import ApiBase

    loop = _bg_loop()
    api = ApiBase(_LoopThread(loop), lambda: None, lambda: {})

    async def _ok():
        return 42

    try:
        assert api._run_async(_ok()) == 42
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_push_animation_deletes_its_temp_file(tmp_path):
    """A bytes payload writes a temp .gif; it must be unlinked after the push
    (success AND error), not leaked for the process lifetime."""
    from divoom_client.daemon_client import DaemonDeviceProxy

    seen = {}

    class _PushProxy:
        class display:
            @staticmethod
            async def show_image(path):
                seen["path"] = path
                seen["existed_during"] = os.path.exists(path)
                return True

    class _Ctx:
        async def __aenter__(self):
            return _PushProxy()
        async def __aexit__(self, *a):
            return False

    proxy = DaemonDeviceProxy.__new__(DaemonDeviceProxy)
    proxy.exclusive = lambda token: _Ctx()

    ok = asyncio.new_event_loop().run_until_complete(proxy.push_animation(b"GIF89a-data"))
    assert ok is True
    assert seen["existed_during"] is True          # present while streaming
    assert not os.path.exists(seen["path"])         # cleaned up after


def test_push_animation_deletes_temp_file_on_error():
    from divoom_client.daemon_client import DaemonDeviceProxy

    seen = {}

    class _BoomProxy:
        class display:
            @staticmethod
            async def show_image(path):
                seen["path"] = path
                raise RuntimeError("push failed")

    class _Ctx:
        async def __aenter__(self):
            return _BoomProxy()
        async def __aexit__(self, *a):
            return False

    proxy = DaemonDeviceProxy.__new__(DaemonDeviceProxy)
    proxy.exclusive = lambda token: _Ctx()

    with pytest.raises(RuntimeError):
        asyncio.new_event_loop().run_until_complete(proxy.push_animation(b"data"))
    assert not os.path.exists(seen["path"])         # temp removed even on failure
