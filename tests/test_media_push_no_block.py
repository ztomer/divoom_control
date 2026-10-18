"""R53.30: _push_frame must NOT read dev.is_connected / dev.lan — each is a
BLOCKING daemon device_status() RPC, and is_connected was read INSIDE the loop
coroutine, stalling the whole asyncio loop. The daemon's device_call already
ensures the device is connected + routes the transport, so the GUI pushes directly.
"""
import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_gui.media_sync import MediaSyncMixin


def test_push_frame_does_not_read_blocking_attrs():
    o = MediaSyncMixin.__new__(MediaSyncMixin)
    o.wall_slots = {}
    pushed = {}

    class _Display:
        async def show_image(self, path):
            pushed["path"] = path
            return True

    class _Dev:
        display = _Display()

        @property
        def is_connected(self):
            raise AssertionError("is_connected read = blocking RPC that stalls the loop")

        @property
        def lan(self):
            raise AssertionError("lan read = blocking RPC")

    dev = _Dev()

    class _Lighting:   # the ONE resolution of a named display (P5.7)
        @staticmethod
        def _display(mac, **_kw):
            return dev if mac == "AA:00:00:00:00:01" else None

    o.lighting = _Lighting()
    o._run_async = lambda coro: asyncio.new_event_loop().run_until_complete(coro)

    assert o._push_frame("AA:00:00:00:00:01", "/tmp/frame.png") == {"success": True}
    assert pushed["path"] == "/tmp/frame.png"


def test_push_frame_returns_false_when_the_named_panel_resolves_to_nothing():
    o = MediaSyncMixin.__new__(MediaSyncMixin)
    o.wall_slots = {}

    class _Lighting:
        @staticmethod
        def _display(mac, **_kw):
            return None

    o.lighting = _Lighting()
    assert o._push_frame("", "/tmp/frame.png")["success"] is False
