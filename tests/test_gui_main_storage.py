"""The app keeps its page's storage across launches (2026-11-01).

Split from `test_gui_main_main.py` (500-line cap); same harness.
"""

import pytest

from divoom_gui import gui_main
from tests.test_gui_main_main import _patch_main_common


def test_main_keeps_the_pages_storage_across_launches(monkeypatch, tmp_path):
    """pywebview's default `private_mode=True` wipes WKWebView's website data
    at every launch, so every preference the page keeps (theme, favourites,
    the bench's collapse) was forgotten on each restart (2026-11-01)."""
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    with pytest.raises(SystemExit):
        gui_main.main()

    assert ctx.start_calls[0].get("private_mode") is False, ctx.start_calls[0]
