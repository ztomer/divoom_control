"""R17 P5 — GUI-side daemon bridge: auto-spawn, TCC-disclaim, and the proxy
status cache — the parts that do NOT need a live daemon.

The proxy-dispatch tests (built on a real in-process DivoomDaemon over a temp
socket) depend on the archived divoom_daemon.daemon server module and moved to
archive/tests/ (removed in R66; in git history) test_daemon_bridge.py.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

# The implementation lives in divoom_daemon.daemon_client (R28); monkeypatching
# below targets that module's globals, which ensure_daemon resolves against.
# divoom_gui.daemon_bridge re-exports the same objects.
from divoom_daemon import daemon_client as daemon_bridge
from divoom_gui.daemon_bridge import daemon_alive, ensure_daemon


def test_daemon_alive_false_for_missing():
    assert daemon_alive(f"/tmp/divoom_absent_{os.getpid()}.sock") is False


def test_ensure_daemon_no_spawn_returns_none_when_absent():
    assert ensure_daemon(f"/tmp/divoom_absent2_{os.getpid()}.sock", spawn=False) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS TCC disclaim path")
def test_rust_daemon_is_tcc_disclaimed(monkeypatch, tmp_path):
    """The native divoomd MUST be spawned TCC-disclaimed so it's its OWN responsible
    process (using its embedded com.divoom.divoomd Info.plist) — not an undisclaimed
    Popen child that inherits the launcher's responsibility. When the .app is started
    under another app (e.g. Claude Desktop) with no Bluetooth usage description, an
    inherited responsibility SIGABRTs the daemon mid-scan. Regression guard for that.
    """
    rust = tmp_path / "divoomd"
    rust.write_text("")
    rust.chmod(0o755)
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust))
    # Not a py2app bundle.
    monkeypatch.setattr(daemon_bridge, "bundle_python", lambda: None)

    seen = {}

    def fake_disclaim(cmd, log_path, env=None):
        seen["cmd"] = cmd
        seen["env"] = env
        return 4242

    def boom_popen(*a, **k):  # the Rust daemon must NOT take the Popen path
        raise AssertionError("rust daemon spawned undisclaimed via Popen")

    monkeypatch.setattr(daemon_bridge, "_spawn_disclaimed_macos", fake_disclaim)
    monkeypatch.setattr(daemon_bridge.subprocess, "Popen", boom_popen)

    pid = daemon_bridge.spawn_daemon(f"/tmp/divoom_disc_{os.getpid()}.sock")
    assert pid == 4242
    assert seen["cmd"][0] == str(rust)
    # env is passed explicitly (so DIVOOMD_ENCODER_LIB propagates through posix_spawn).
    assert seen["env"] is not None


def test_bundle_python_none_from_source():
    """Release: bundle_python() is None when running from source (not a .app)."""
    assert daemon_bridge.bundle_python() is None


def test_bundle_python_resolves_in_frozen_app(monkeypatch, tmp_path):
    """In a py2app .app, bundle_python() points at the sibling `python` stub of
    the GUI executable (sys.executable is the app stub, not a python)."""
    macos = tmp_path / "Divoom.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "Divoom").write_text("")        # the GUI app stub
    py = macos / "python"
    py.write_text("")                        # the bundled interpreter
    monkeypatch.setattr(sys, "frozen", "macosx_app", raising=False)
    monkeypatch.setattr(sys, "executable", str(macos / "Divoom"))
    assert daemon_bridge.bundle_python() == str(py)


# ── R53.25: exclusive_end failure is logged, never raised, never silent ──────

def test_exclusive_end_failure_is_logged_not_raised(caplog):
    """A dropped exclusive release wedges the device ~30s (until G3 auto-release);
    __aexit__ must surface it (can't raise — would mask a body exception)."""
    import asyncio
    import logging
    from divoom_daemon.daemon_client import _ProxyExclusiveCtx

    class _Client:
        def exclusive_end(self, token):
            return {"success": False, "error": "daemon mid-restart"}

    class _Proxy:
        _client = _Client()

    ctx = _ProxyExclusiveCtx(_Proxy(), "tok-1")
    loop = asyncio.new_event_loop()
    try:
        with caplog.at_level(logging.WARNING, logger="divoom_gui"):
            loop.run_until_complete(ctx.__aexit__(None, None, None))   # must NOT raise
    finally:
        loop.close()
    assert any("did not confirm release" in r.message for r in caplog.records)


def test_exclusive_end_success_is_quiet(caplog):
    import asyncio
    import logging
    from divoom_daemon.daemon_client import _ProxyExclusiveCtx

    class _Client:
        def exclusive_end(self, token):
            return {"success": True}

    class _Proxy:
        _client = _Client()

    ctx = _ProxyExclusiveCtx(_Proxy(), "tok-2")
    loop = asyncio.new_event_loop()
    try:
        with caplog.at_level(logging.WARNING, logger="divoom_gui"):
            loop.run_until_complete(ctx.__aexit__(None, None, None))
    finally:
        loop.close()
    assert not any("tok-2" in r.message for r in caplog.records)


# ── R53.31: proxy device_status short-TTL cache ─────────────────────────────

def test_proxy_status_cache_dedupes_intra_op_reads():
    """is_connected/lan/_conn read back-to-back in one op must share ONE
    device_status() RPC, not fire three blocking round-trips."""
    from divoom_daemon.daemon_client import DaemonDeviceProxy

    calls = {"n": 0}

    class _Client:
        def device_status(self):
            calls["n"] += 1
            return {"connected": True, "lan_ip": None, "mac": "AA:BB"}

    proxy = DaemonDeviceProxy(_Client())
    _ = proxy.is_connected
    _ = proxy.lan
    _ = proxy._conn
    assert calls["n"] == 1, f"expected 1 device_status RPC, got {calls['n']}"


def test_proxy_status_cache_refetches_after_ttl():
    """Once the short TTL lapses, a fresh read refetches (no permanent staleness)."""
    from divoom_daemon.daemon_client import DaemonDeviceProxy

    calls = {"n": 0}

    class _Client:
        def device_status(self):
            calls["n"] += 1
            return {"connected": True}

    proxy = DaemonDeviceProxy(_Client())
    _ = proxy.is_connected
    # rewind the cache timestamp past the TTL (faster + deterministic vs sleeping)
    object.__setattr__(proxy, "_status_cache_ts", proxy._status_cache_ts - 1.0)
    _ = proxy.is_connected
    assert calls["n"] == 2
