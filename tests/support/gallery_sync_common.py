"""Shared scaffolding for the split gallery_sync test modules.

R70 P2.2: the `divoom_lib.media_decoder` shim that used to sit here is gone
along with the decoder itself. `gallery_sync.py` no longer imports it — the
daemon downloads and decodes, and this process only caches the answers — so the
native dylib is no longer a precondition for importing the GUI module at all.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from divoom_gui.gallery_sync import GallerySyncMixin  # noqa: E402


class FakeDaemonClient:
    """A daemon stand-in for the gallery seam.

    `fetch_gallery` and `get_animated_preview` are the only two calls the
    gallery makes now, which is the point of the migration: two named commands
    instead of a hand-rolled POST, a credential cache and a decoder.
    """

    def __init__(self, file_list=None, previews=None, fetch_error=None,
                 preview_errors=None):
        self.file_list = file_list if file_list is not None else []
        self.previews = previews or {}
        self.fetch_error = fetch_error
        self.preview_errors = preview_errors or {}
        self.fetch_calls = []
        self.preview_calls = []

    def fetch_gallery(self, classify, limit=30, file_sort=1, file_size=127):
        self.fetch_calls.append(
            {"classify": classify, "limit": limit,
             "file_sort": file_sort, "file_size": file_size})
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.file_list

    def get_animated_preview(self, file_id):
        self.preview_calls.append(file_id)
        if file_id in self.preview_errors:
            raise self.preview_errors[file_id]
        return self.previews.get(file_id, "")


class _Host(GallerySyncMixin):
    """Minimal host exposing the attributes gallery_sync.py methods expect,
    without pulling in the full DivoomGuiAPI (webview/daemon bootstrap)."""

    def __init__(self):
        self.window = None
        self.cached_creds = None
        self.device_id = 123
        self.device_pw = 0
        self.current_target_mode = "single"
        self.current_divoom = None
        self.wall_slots = {}
        self._daemon_client = None

    def _client(self):
        return self._daemon_client


def _wait_for_fetch_thread():
    for t in threading.enumerate():
        if t.name == "DivoomGalleryFetch":
            t.join(timeout=5.0)
