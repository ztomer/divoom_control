"""R61 coverage push: divoom_client.daemon_client branches not exercised by
test_daemon_bridge.py (proxy happy paths against a real in-process daemon) or
test_daemon_client_wedge.py (client-side socket timeouts).

Gaps closed here, all against mocks — no real subprocess, socket, or daemon:
  * spawn_daemon()'s binary-resolution chain (DIVOOM_RUST_BINARY pointing at a
    missing file, the PyInstaller _MEIPASS layout, the py2app RESOURCEPATH
    layout, the no-binary-resolves RuntimeError, the disclaimed-spawn-raises ->
    Popen fallback, and the log-file-unwritable OSError guard).
  * ensure_daemon()'s remote-host (DIVOOM_DAEMON_HOST) branch, never reached
    by the local-socket tests in test_daemon_bridge.py.
  * _spawn_disclaimed_macos()'s three internal libc-failure branches, via a
    mocked ctypes.CDLL (never a real posix_spawn).
  * DaemonDeviceProxy/_ProxyExclusiveCtx edge cases: __aenter__ raising on a
    failed exclusive_start, __aexit__ swallowing an exception FROM
    exclusive_end itself (distinct from the already-tested "returned a
    failure dict" case), push_animation's OSError cleanup paths, the
    leading-underscore AttributeError guard, and the remote-client blob
    -shipping path in __call__.
"""
import ctypes
import os
import sys
from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from divoom_client import daemon_client
from divoom_client.daemon_client import (
    DaemonDeviceProxy,
    _LanView,
    _ProxyExclusiveCtx,
)
from divoom_client.daemon_protocol import ENV_HOST, DaemonClient


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


# ── _spawn_disclaimed_macos: libc failure branches (mocked CDLL) ─────────


def _fake_libc(**overrides):
    lib = MagicMock()
    lib.posix_spawnattr_init.return_value = 0
    lib.responsibility_spawnattrs_setdisclaim.return_value = 0
    lib.posix_spawn.return_value = 0
    for k, v in overrides.items():
        getattr(lib, k).return_value = v
    return lib


def test_spawn_disclaimed_macos_attr_init_failure(monkeypatch, tmp_path):
    fake_libc = _fake_libc(posix_spawnattr_init=1)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake_libc)
    with pytest.raises(OSError, match="posix_spawnattr_init failed"):
        daemon_client._spawn_disclaimed_macos(["/bin/true"], str(tmp_path / "log.txt"))


def test_spawn_disclaimed_macos_disclaim_failure(monkeypatch, tmp_path):
    fake_libc = _fake_libc(responsibility_spawnattrs_setdisclaim=1)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake_libc)
    with pytest.raises(OSError, match="responsibility_spawnattrs_setdisclaim failed"):
        daemon_client._spawn_disclaimed_macos(["/bin/true"], str(tmp_path / "log.txt"))
    # The attrs-destroy cleanup must still run despite the raise.
    fake_libc.posix_spawnattr_destroy.assert_called_once()


def test_spawn_disclaimed_macos_posix_spawn_failure(monkeypatch, tmp_path):
    fake_libc = _fake_libc(posix_spawn=7)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake_libc)
    with pytest.raises(OSError, match=r"posix_spawn failed rc=7"):
        daemon_client._spawn_disclaimed_macos(["/bin/true"], str(tmp_path / "log.txt"))
    fake_libc.posix_spawn_file_actions_destroy.assert_called_once()
    fake_libc.posix_spawnattr_destroy.assert_called_once()


def test_spawn_disclaimed_macos_success_returns_pid(monkeypatch, tmp_path):
    fake_libc = _fake_libc()

    def fake_posix_spawn(pid_ptr, path, fa, attr, argv, envp):
        pid_ptr._obj.value = 4242
        return 0

    fake_libc.posix_spawn.side_effect = fake_posix_spawn
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake_libc)
    pid = daemon_client._spawn_disclaimed_macos(
        ["/bin/true"], str(tmp_path / "log.txt"), env={"FOO": "bar"})
    assert pid == 4242


# ── spawn_daemon(): binary resolution chain ───────────────────────────────


@pytest.fixture(autouse=True)
def _clean_spawn_env(monkeypatch):
    """spawn_daemon() reads several env vars / sys attrs; keep each test's
    view of them isolated."""
    for var in ("DIVOOM_RUST_BINARY", "DIVOOM_USE_RUST_DAEMON", "RESOURCEPATH",
                "DIVOOM_DAEMON_LOG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    yield


def test_spawn_daemon_rust_binary_env_invalid_path_falls_through(monkeypatch, tmp_path):
    """DIVOOM_RUST_BINARY pointing at a nonexistent file must be discarded,
    not used, and resolution must continue to the dev build tree (not crash)."""
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(tmp_path / "nope-not-here"))
    seen = {}

    def fake_disclaim(cmd, log_path, env=None):
        seen["cmd"] = cmd
        return 999

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", fake_disclaim)
    pid = daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert pid == 999
    # Resolved via the dev build tree fallback, not the discarded env path.
    assert seen["cmd"][0].endswith("/target/release/divoomd") or \
        seen["cmd"][0].endswith("/target/debug/divoomd")


def test_spawn_daemon_raises_when_no_rust_binary_resolves(monkeypatch, tmp_path):
    """No env override, no _MEIPASS, no RESOURCEPATH, and a dev tree that
    doesn't resolve (patched away) must raise a clear RuntimeError instead of
    emitting a broken `-m divoom_lib.cli daemon` command."""
    monkeypatch.setattr(daemon_client.Path, "exists", lambda self: False)
    with pytest.raises(RuntimeError, match="divoomd .* binary not found"):
        daemon_client.spawn_daemon(str(tmp_path / "sock"))


def test_spawn_daemon_meipass_resolves_binary_and_dylib(monkeypatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "divoomd").write_text("")
    libdir = tmp_path / "divoom_lib"
    libdir.mkdir()
    (libdir / "libdivoom_compact.dylib").write_text("")

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    seen = {}

    def fake_disclaim(cmd, log_path, env=None):
        seen["cmd"] = cmd
        seen["env"] = env
        return 111

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", fake_disclaim)
    pid = daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert pid == 111
    assert seen["cmd"][0] == str(bindir / "divoomd")
    assert seen["env"]["DIVOOMD_ENCODER_LIB"] == str(libdir / "libdivoom_compact.dylib")


def test_spawn_daemon_resourcepath_resolves_binary_and_dylib(monkeypatch, tmp_path):
    (tmp_path / "divoomd").write_text("")
    (tmp_path / "libdivoom_compact.dylib").write_text("")
    monkeypatch.setenv("RESOURCEPATH", str(tmp_path))

    seen = {}

    def fake_disclaim(cmd, log_path, env=None):
        seen["cmd"] = cmd
        seen["env"] = env
        return 222

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", fake_disclaim)
    pid = daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert pid == 222
    assert seen["cmd"][0] == str(tmp_path / "divoomd")
    assert seen["env"]["DIVOOMD_ENCODER_LIB"] == str(tmp_path / "libdivoom_compact.dylib")


def test_spawn_daemon_rust_path_with_mac(monkeypatch, tmp_path):
    rust_bin = tmp_path / "divoomd"
    rust_bin.write_text("")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust_bin))
    seen = {}

    def fake_disclaim(cmd, log_path, env=None):
        seen["cmd"] = cmd
        return 444

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", fake_disclaim)
    pid = daemon_client.spawn_daemon(str(tmp_path / "sock"), mac="11:22:33")
    assert pid == 444
    assert seen["cmd"] == [str(rust_bin), "--socket", str(tmp_path / "sock"), "--mac", "11:22:33"]


def test_spawn_daemon_log_open_failure_is_swallowed(monkeypatch, tmp_path):
    """An unwritable DIVOOM_DAEMON_LOG path must not crash the spawn."""
    rust_bin = tmp_path / "divoomd"
    rust_bin.write_text("")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust_bin))
    monkeypatch.setenv("DIVOOM_DAEMON_LOG", str(tmp_path / "no" / "such" / "dir" / "log.txt"))
    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos",
                         lambda cmd, log_path, env=None: 555)
    pid = daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert pid == 555


@pytest.mark.skipif(sys.platform != "darwin", reason="disclaim-fallback path is macOS-only")
def test_spawn_daemon_disclaim_raises_falls_back_to_popen(monkeypatch, tmp_path):
    """If the disclaimed spawn itself raises, spawn_daemon must fall back to
    plain Popen rather than propagating."""
    rust_bin = tmp_path / "divoomd"
    rust_bin.write_text("")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust_bin))

    def boom(cmd, log_path, env=None):
        raise OSError("disclaim broke")

    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", boom)
    fake_popen = MagicMock(return_value="popen-handle")
    monkeypatch.setattr(daemon_client.subprocess, "Popen", fake_popen)
    result = daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert result == "popen-handle"
    fake_popen.assert_called_once()


@pytest.mark.skipif(sys.platform == "darwin", reason="non-darwin Popen-only path")
def test_spawn_daemon_non_darwin_uses_popen_directly(monkeypatch, tmp_path):
    rust_bin = tmp_path / "divoomd"
    rust_bin.write_text("")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(rust_bin))
    fake_popen = MagicMock(return_value="popen-handle")
    monkeypatch.setattr(daemon_client.subprocess, "Popen", fake_popen)
    result = daemon_client.spawn_daemon(str(tmp_path / "sock"))
    assert result == "popen-handle"


# ── ensure_daemon(): remote-host branch ────────────────────────────────────


def test_ensure_daemon_remote_host_alive_returns_client(monkeypatch):
    monkeypatch.setenv(ENV_HOST, "otherhost")
    fake_remote = MagicMock(host="otherhost", port=4321)
    monkeypatch.setattr(DaemonClient, "from_env", classmethod(lambda cls, sp: fake_remote))
    monkeypatch.setattr(daemon_client, "_client_alive", lambda client: client is fake_remote)
    result = daemon_client.ensure_daemon("/tmp/unused.sock")
    assert result is fake_remote


def test_ensure_daemon_remote_host_unreachable_returns_none(monkeypatch):
    monkeypatch.setenv(ENV_HOST, "otherhost")
    fake_remote = MagicMock(host="otherhost", port=4321)
    monkeypatch.setattr(DaemonClient, "from_env", classmethod(lambda cls, sp: fake_remote))
    monkeypatch.setattr(daemon_client, "_client_alive", lambda client: False)
    result = daemon_client.ensure_daemon("/tmp/unused.sock")
    assert result is None


# ── _LanView ───────────────────────────────────────────────────────────────


def test_lan_view_bool_reflects_device_ip():
    assert bool(_LanView(None)) is False
    assert bool(_LanView("192.168.1.5")) is True


# ── _ProxyExclusiveCtx: __aenter__ / __aexit__ edge cases ─────────────────


class _FakeClient:
    def __init__(self, start_reply=None, end_reply=None, end_raises=None):
        self._start_reply = start_reply if start_reply is not None else {"success": True}
        self._end_reply = end_reply if end_reply is not None else {"success": True}
        self._end_raises = end_raises

    def exclusive_start(self, token):
        return self._start_reply

    def exclusive_end(self, token):
        if self._end_raises is not None:
            raise self._end_raises
        return self._end_reply


class _FakeProxy:
    def __init__(self, client):
        self._client = client

    def _with_token(self, token):
        return ("tokenized-proxy", token)


def test_exclusive_ctx_aenter_raises_on_failed_start():
    client = _FakeClient(start_reply={"success": False, "error": "device busy"})
    ctx = _ProxyExclusiveCtx(_FakeProxy(client), "tok")
    with pytest.raises(daemon_client._DeviceCallError, match="device busy"):
        _run(ctx.__aenter__())


def test_exclusive_ctx_aenter_returns_tokenized_proxy_on_success():
    client = _FakeClient(start_reply={"success": True})
    proxy = _FakeProxy(client)
    ctx = _ProxyExclusiveCtx(proxy, "tok-9")
    result = _run(ctx.__aenter__())
    assert result == ("tokenized-proxy", "tok-9")


def test_exclusive_ctx_aexit_swallows_exception_from_exclusive_end(caplog):
    """exclusive_end() itself raising (not just returning a failure dict)
    must be caught and logged, never propagated — it runs during cleanup and
    must not mask whatever exception the `async with` body raised."""
    import logging
    client = _FakeClient(end_raises=RuntimeError("socket blew up"))
    ctx = _ProxyExclusiveCtx(_FakeProxy(client), "tok-err")
    with caplog.at_level(logging.WARNING, logger="divoom_gui"):
        _run(ctx.__aexit__(None, None, None))  # must not raise
    assert any("exclusive_end raised" in r.message for r in caplog.records)


# ── DaemonDeviceProxy: attribute guard + remote blob shipping ─────────────


def test_getattr_leading_underscore_raises_attribute_error():
    proxy = DaemonDeviceProxy(MagicMock())
    with pytest.raises(AttributeError):
        getattr(proxy, "_totally_private")


def test_call_ships_local_file_as_blob_for_remote_client(tmp_path):
    real_file = tmp_path / "art.gif"
    real_file.write_bytes(b"GIF89a-fake-bytes")

    fake_client = MagicMock()
    fake_client.is_remote = True
    fake_client.device_call.return_value = {"success": True, "result": True}

    proxy = DaemonDeviceProxy(fake_client, "display.show_image")
    _run(proxy(str(real_file)))

    fake_client.device_call.assert_called_once()
    _, kwargs = fake_client.device_call.call_args
    assert kwargs["blobs"] == {0: b"GIF89a-fake-bytes"}


def test_call_local_client_never_ships_blobs(tmp_path):
    real_file = tmp_path / "art.gif"
    real_file.write_bytes(b"GIF89a-fake-bytes")

    fake_client = MagicMock()
    fake_client.is_remote = False
    fake_client.device_call.return_value = {"success": True, "result": True}

    proxy = DaemonDeviceProxy(fake_client, "display.show_image")
    _run(proxy(str(real_file)))

    _, kwargs = fake_client.device_call.call_args
    assert kwargs["blobs"] is None


def test_call_remote_client_unreadable_file_is_swallowed(tmp_path):
    """A path that IS a file but can't be opened (permission denied) must not
    crash __call__ — the OSError is swallowed and the call proceeds blob-less
    for that arg."""
    real_file = tmp_path / "locked.gif"
    real_file.write_bytes(b"secret")
    os.chmod(real_file, 0o000)
    try:
        if os.access(real_file, os.R_OK):
            pytest.skip("running as a user that can read chmod-000 files (e.g. root)")

        fake_client = MagicMock()
        fake_client.is_remote = True
        fake_client.device_call.return_value = {"success": True, "result": True}

        proxy = DaemonDeviceProxy(fake_client, "display.show_image")
        _run(proxy(str(real_file)))

        _, kwargs = fake_client.device_call.call_args
        assert kwargs["blobs"] is None
    finally:
        os.chmod(real_file, 0o644)


def test_device_call_error_raised_on_failure_reply():
    fake_client = MagicMock()
    fake_client.is_remote = False
    fake_client.device_call.return_value = {"success": False, "error": "nope"}
    proxy = DaemonDeviceProxy(fake_client, "display.show_light")
    with pytest.raises(daemon_client._DeviceCallError, match="nope"):
        _run(proxy())


# ── push_animation: OSError cleanup paths ─────────────────────────────────


def test_push_animation_tempfile_write_failure_propagates(monkeypatch):
    fake_client = MagicMock()
    proxy = DaemonDeviceProxy(fake_client)

    class _BoomFile:
        name = "/tmp/whatever.gif"

        def write(self, data):
            raise OSError("disk full")

        def close(self):
            pass

    monkeypatch.setattr(
        daemon_client.tempfile if hasattr(daemon_client, "tempfile") else __import__("tempfile"),
        "NamedTemporaryFile", lambda *a, **k: _BoomFile())

    with pytest.raises(OSError, match="disk full"):
        _run(proxy.push_animation(b"GIF89a-payload"))


def test_push_animation_unlink_failure_is_swallowed(monkeypatch, tmp_path):
    """Cleanup of the temp file we created must never raise even if the file
    is already gone (e.g. removed by another process)."""
    calls = []

    class _StubExclusiveCtx:
        async def __aenter__(self_inner):
            class _P:
                class display:
                    @staticmethod
                    async def show_image(path):
                        calls.append(path)
                        return True
            return _P()

        async def __aexit__(self_inner, *exc):
            return None

    fake_client = MagicMock()
    proxy = DaemonDeviceProxy(fake_client)
    monkeypatch.setattr(proxy, "exclusive", lambda token: _StubExclusiveCtx())

    def boom_unlink(path):
        raise OSError("already gone")

    monkeypatch.setattr(daemon_client.os, "unlink", boom_unlink)

    result = _run(proxy.push_animation(b"GIF89a-payload"))
    assert result is True
    assert len(calls) == 1
