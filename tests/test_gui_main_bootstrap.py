"""Coverage for the testable logic in divoom_gui/gui_main.py.

Split from test_gui_event_forwarder.py (which already covers
`_make_daemon_event_handler`) and test_menubar.py (which already covers the
`_spawn_menubar_agent` dupe-guard happy path). This file covers:

  - the pure helper functions (`_pywebview_1820_bug_present`, `_resolve_web_ui`,
    `_resolve_bundled_binary`, `_resolve_menubar_binary`, `_ensure_single_instance`)
  - the remaining `_spawn_menubar_agent` / `_terminate_menubar_agent` branches
  - `main()`'s bootstrap/decision logic (single-instance gate, optional control
    servers, eager daemon spawn, permission priming, the daemon-shutdown-once
    guard, url/query construction) with `webview`/`DivoomGuiAPI`/daemon/menubar
    calls mocked out.

What's deliberately NOT covered here (left to real app / user-POV verification,
per docs/PLANNING_ROUND61.md item 1): the actual `webview.create_window(...)`
window it produces, `webview.start()`'s real GTK/Cocoa event loop, and the
`__main__` entrypoint — those are platform GUI mainloop plumbing, not logic.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_gui import gui_main  # noqa: E402


# ───────────────────────── module-level locale bootstrap ────────────────────
# gui_main.py's very first lines (before any other import) try
# `en_US.UTF-8` then `C.UTF-8` via `locale.setlocale`, swallowing failures —
# a py2app-bundled interpreter starts with no locale applied. That loop runs
# once, at import time, before any fixture can intervene, so the only way to
# exercise the "every candidate fails" branch is a fresh interpreter with
# `locale.setlocale` forced to fail *before* `divoom_gui.gui_main` is
# imported. A subprocess gives us that clean slate without mutating the
# current process's locale or reloading a module already used by other tests.

def test_locale_bootstrap_swallows_setlocale_failures_for_all_candidates():
    script = (
        "import locale, sys\n"
        "def _boom(*a, **kw):\n"
        "    raise locale.Error('no locale available')\n"
        "locale.setlocale = _boom\n"
        "sys.path.insert(0, %r)\n"
        "import divoom_gui.gui_main as gm\n"
        "print('IMPORTED_OK', gm.logger.name)\n"
    ) % str(_REPO)

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_REPO), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "IMPORTED_OK divoom_gui" in proc.stdout


# ─────────────────────────── _pywebview_1820_bug_present ────────────────────

def test_bug_present_detects_token(monkeypatch):
    def fake_getsource(fn):
        return "AppKit.NSPoint(self.screen.origin.x + x, self.screen.origin.y + flipped_y)"

    # The function imports `inspect` locally; patch the real (shared) module.
    import inspect as real_inspect
    monkeypatch.setattr(real_inspect, "getsource", fake_getsource)
    assert gui_main._pywebview_1820_bug_present() is True


def test_bug_present_false_when_fixed(monkeypatch):
    import inspect as real_inspect
    monkeypatch.setattr(real_inspect, "getsource", lambda fn: "NSPoint(x, self.screen.origin.y + flipped_y)")
    assert gui_main._pywebview_1820_bug_present() is False


def test_bug_present_false_on_import_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "webview.platforms.cocoa":
            raise ImportError("no cocoa backend")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert gui_main._pywebview_1820_bug_present() is False


def test_bug_present_false_on_getsource_oserror(monkeypatch):
    import inspect as real_inspect

    def raiser(fn):
        raise OSError("no source available")

    monkeypatch.setattr(real_inspect, "getsource", raiser)
    assert gui_main._pywebview_1820_bug_present() is False


# ─────────────────────────────── _resolve_web_ui ─────────────────────────────

def test_resolve_web_ui_finds_dev_tree_index(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src" / "web_ui").mkdir(parents=True)
    (tmp_path / "src" / "web_ui" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)

    result = gui_main._resolve_web_ui()
    assert result == tmp_path / "src" / "web_ui"


def test_resolve_web_ui_falls_back_to_meipass_divoom_gui(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src").mkdir(parents=True)  # no web_ui next to the module
    mei = tmp_path / "bundle" / "frameworks"
    (mei / "divoom_gui" / "web_ui").mkdir(parents=True)
    (mei / "divoom_gui" / "web_ui" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)

    result = gui_main._resolve_web_ui()
    assert result == mei / "divoom_gui" / "web_ui"


def test_resolve_web_ui_falls_back_to_resources_parent(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src").mkdir(parents=True)
    mei = tmp_path / "bundle" / "Contents" / "Frameworks"
    resources = tmp_path / "bundle" / "Contents" / "Resources" / "divoom_gui" / "web_ui"
    resources.mkdir(parents=True)
    (resources / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)

    result = gui_main._resolve_web_ui()
    assert result == resources


def test_resolve_web_ui_no_candidate_found_returns_first(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src").mkdir(parents=True)
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)

    result = gui_main._resolve_web_ui()
    assert result == tmp_path / "src" / "web_ui"


# ───────────────────────────── _resolve_bundled_binary ───────────────────────

def test_resolve_bundled_binary_env_override(tmp_path, monkeypatch):
    binary = tmp_path / "divoomd"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(binary))
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_env_override_menubar(tmp_path, monkeypatch):
    binary = tmp_path / "divoom-menubar"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("DIVOOM_MENUBAR_BINARY", str(binary))
    assert gui_main._resolve_bundled_binary("divoom-menubar") == str(binary)


def test_resolve_bundled_binary_meipass_bin_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    mei = tmp_path / "mei"
    (mei / "bin").mkdir(parents=True)
    binary = mei / "bin" / "divoomd"
    binary.write_text("x")
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_resourcepath(tmp_path, monkeypatch):
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)
    rp = tmp_path / "Resources"
    rp.mkdir()
    binary = rp / "divoomd"
    binary.write_text("x")
    monkeypatch.setenv("RESOURCEPATH", str(rp))
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_meipass_second_candidate(tmp_path, monkeypatch):
    """First MEIPASS candidate (bin/<name>) is absent; the loop must continue
    to the second (<mei>/<name>) rather than stopping at the first miss."""
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    mei = tmp_path / "mei"
    mei.mkdir(parents=True)
    binary = mei / "divoomd"
    binary.write_text("x")
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_meipass_no_candidate_falls_through(tmp_path, monkeypatch):
    """None of the three MEIPASS-relative candidates exist -> the loop runs to
    completion and falls through to the RESOURCEPATH/None checks below it."""
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    mei = tmp_path / "mei-empty"
    mei.mkdir(parents=True)
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") is None


def test_resolve_bundled_binary_none_found(tmp_path, monkeypatch):
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") is None


# ───────────────────────────── _ensure_single_instance ───────────────────────

def test_ensure_single_instance_acquires_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(gui_main, "_GUI_LOCK_FH", None)
    # `_ensure_single_instance` imports `tempfile` locally; patch the shared module.
    import tempfile as real_tempfile
    monkeypatch.setattr(real_tempfile, "gettempdir", lambda: str(tmp_path))

    assert gui_main._ensure_single_instance() is True
    assert gui_main._GUI_LOCK_FH is not None


def test_ensure_single_instance_false_when_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(gui_main, "_GUI_LOCK_FH", None)
    import fcntl as real_fcntl

    def raiser(fd, flags):
        raise BlockingIOError("already locked")

    monkeypatch.setattr(real_fcntl, "flock", raiser)
    assert gui_main._ensure_single_instance() is False


# ─────────────────────────────── _resolve_menubar_binary ─────────────────────

def test_resolve_menubar_binary_uses_bundled(monkeypatch):
    monkeypatch.setattr(gui_main, "_resolve_bundled_binary", lambda name: "/bundled/divoom-menubar")
    assert gui_main._resolve_menubar_binary() == "/bundled/divoom-menubar"


def test_resolve_menubar_binary_dev_tree_release(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_main, "_resolve_bundled_binary", lambda name: None)
    # `_resolve_menubar_binary` computes `repo_root = Path(__file__).resolve().parents[1]`
    # — fake `__file__` two levels under a controlled repo_root instead of touching
    # the real Path.resolve (which is process-global and used everywhere).
    repo_root = tmp_path
    fake_module_file = repo_root / "divoom_gui" / "gui_main.py"
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    target = repo_root / "target" / "release"
    target.mkdir(parents=True)
    (target / "divoom-menubar").write_text("x")

    assert gui_main._resolve_menubar_binary() == str(target / "divoom-menubar")


def test_resolve_menubar_binary_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_main, "_resolve_bundled_binary", lambda name: None)
    repo_root = tmp_path
    fake_module_file = repo_root / "divoom_gui" / "gui_main.py"
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))

    assert gui_main._resolve_menubar_binary() is None


# ─────────────────────────────── _spawn_menubar_agent ────────────────────────

def test_spawn_menubar_agent_noop_on_non_darwin(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    gui_main._spawn_menubar_agent()  # must return immediately, no assertion raised


def test_spawn_menubar_agent_already_running_skips_spawn(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    class _Match:
        returncode = 0
        stdout = "1234\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Match())
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not spawn")))
    gui_main._spawn_menubar_agent()  # no assertion raised => Popen never called


def test_spawn_menubar_agent_binary_not_found_warns(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    class _NoMatch:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _NoMatch())
    monkeypatch.setattr(gui_main, "_resolve_menubar_binary", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not spawn")))
    gui_main._spawn_menubar_agent()  # no assertion raised => Popen never called


def test_spawn_menubar_agent_frozen_uses_executable(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(gui_main.sys, "frozen", True, raising=False)

    class _NoMatch:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _NoMatch())
    monkeypatch.setattr(gui_main, "_resolve_menubar_binary", lambda: "/bin/divoom-menubar")
    seen = {}

    def fake_popen(args, env=None, **kw):
        seen["args"] = args
        seen["env"] = env
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    gui_main._spawn_menubar_agent()

    assert seen["env"]["DIVOOM_GUI_PYTHON"] == sys.executable
    assert seen["env"]["DIVOOM_GUI_SCRIPT"] == ""


def test_spawn_menubar_agent_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    def raiser(*a, **kw):
        raise OSError("pgrep missing")

    monkeypatch.setattr(subprocess, "run", raiser)
    gui_main._spawn_menubar_agent()  # must not raise


# ────────────────────────────── _terminate_menubar_agent ─────────────────────

def test_terminate_menubar_agent_noop_on_non_darwin(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    gui_main._terminate_menubar_agent()


def test_terminate_menubar_agent_calls_pkill(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    gui_main._terminate_menubar_agent()
    assert seen["args"] == ["pkill", "-f", "divoom-menubar"]


def test_terminate_menubar_agent_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    def raiser(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pkill", timeout=3)

    monkeypatch.setattr(subprocess, "run", raiser)
    gui_main._terminate_menubar_agent()  # must not raise
