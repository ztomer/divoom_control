"""Shared scaffolding for the split gallery_sync test modules."""
import sys
import threading
import types
from pathlib import Path

# Stub the C dylib the same way test_gallery_cache_rebuild.py does, so the
# top-level `from divoom_lib import media_decoder` import in gallery_sync.py
# is safe even in environments where the native lib isn't built.
if "divoom_lib.media_decoder" not in sys.modules:
    import divoom_lib
    _shim = types.ModuleType("divoom_lib.media_decoder")
    _shim.extract_image_from_magic_43 = lambda b: None
    _shim.extract_gif_from_magic_43 = lambda b: None
    _shim.decode_and_save_preview = lambda *a, **k: None
    sys.modules["divoom_lib.media_decoder"] = _shim
    divoom_lib.media_decoder = _shim

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from divoom_gui.gallery_sync import GallerySyncMixin  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from divoom_gui.gallery_sync import GallerySyncMixin


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
