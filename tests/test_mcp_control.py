"""
Tests for divoom_gui.mcp_control — the GUI's MCP server subprocess controller.

Coverage target: lifecycle (start/stop/is_running), the already-running guard,
spawn-failure envelopes (FileNotFoundError / OSError), SIGTERM->SIGKILL
escalation in stop(), log-tail reading in status() (including its OSError
envelope and the stale-log gate), and the process-level singleton.

All ``subprocess.Popen`` calls are mocked — this file must never spawn a real
subprocess. The MCP server is a long-lived stdio process (see
tests/test_mcp_server.py for the no-pipe-stdio guard it needs); accidentally
spawning a real one here would hang the test suite.
"""
from __future__ import annotations

import signal
import subprocess
import sys
from unittest.mock import MagicMock, patch

from divoom_gui.mcp_control import MCPController


def _fake_popen(pid: int = 4242, poll_return=None) -> MagicMock:
    """Build a MagicMock standing in for a subprocess.Popen instance."""
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid
    proc.poll.return_value = poll_return
    proc.wait.return_value = 0
    return proc


# ── is_running() ──────────────────────────────────────────────────────


def test_is_running_false_when_never_started(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    assert ctl.is_running() is False


def test_is_running_true_while_process_alive(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    ctl._proc = _fake_popen(poll_return=None)
    assert ctl.is_running() is True


def test_is_running_false_and_clears_state_after_exit(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    ctl._proc = _fake_popen(poll_return=1)  # exited with code 1
    ctl._started_at = 123.0
    ctl._mac = "AA:BB:CC:DD:EE:FF"
    assert ctl.is_running() is False
    assert ctl._proc is None
    assert ctl._started_at is None
    assert ctl._mac is None


# ── start() ────────────────────────────────────────────────────────────


def test_start_already_running_is_noop(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    ctl._proc = _fake_popen(poll_return=None)
    with patch("divoom_gui.mcp_control.subprocess.Popen") as popen:
        status = ctl.start(mac="11:22:33:44:55:66")
    popen.assert_not_called()
    assert status.running is True


def test_start_spawns_divoomd_mcp_and_tracks_state(tmp_path) -> None:
    """R70 P4.2: the MCP server is `divoomd mcp`, not a Python module.

    This test used to assert
    `["/usr/bin/python3", "-m", "divoom_lib.cli", "mcp-server", "--mac", ...]`
    — the defect AS the specification, and it passed in a dev tree forever
    because `sys.executable` is a real Python there. Inside the packaged app it
    is the GUI binary, and P4.1 watched that spawn a second Divoom window
    instead of a server. House rule #8: a test pinning a wrong behaviour is
    part of the defect.
    """
    log_path = tmp_path / "sub" / "mcp-server.log"
    ctl = MCPController(log_path=log_path)
    fake_proc = _fake_popen(pid=999)
    with patch("divoom_gui.mcp_control.subprocess.Popen", return_value=fake_proc) as popen:
        status = ctl.start(mac="11:22:33:44:55:66", python="/opt/divoom/divoomd")

    assert status.running is True
    assert status.pid == 999
    assert status.mac == "11:22:33:44:55:66"
    assert ctl._started_this_session is True

    args, kwargs = popen.call_args
    assert args[0] == ["/opt/divoom/divoomd", "mcp"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
    # stdout and stderr point at the same log file handle.
    assert kwargs["stdout"] is kwargs["stderr"]
    assert log_path.parent.is_dir()


def test_start_passes_no_mac_flag_to_the_daemon(tmp_path) -> None:
    """`divoomd mcp` takes no arguments — it connects to the running daemon,
    which already owns the device (R28). The mac is still recorded for the
    status card, but sending it would be inventing a flag."""
    ctl = MCPController(log_path=tmp_path / "x.log")
    with patch("divoom_gui.mcp_control.subprocess.Popen", return_value=_fake_popen()) as popen, \
         patch("divoom_client.binary_resolver.resolve", return_value="/opt/divoomd"):
        status = ctl.start(mac="11:22:33:44:55:66")
    assert popen.call_args[0][0] == ["/opt/divoomd", "mcp"]
    assert status.mac == "11:22:33:44:55:66"


def test_start_resolves_the_daemon_BY_VERSION_not_by_walking_paths(tmp_path) -> None:
    """P4.3, and the R69 class: there must be exactly one resolver.

    `binary_resolver.resolve` is what applies the bundle-vs-dev rules (a bundle
    answers from the bundle; a dev tree requires a version match). A second
    path-walk here is how "pick the first binary that exists" came back last
    time.
    """
    ctl = MCPController(log_path=tmp_path / "x.log")
    with patch("divoom_gui.mcp_control.subprocess.Popen", return_value=_fake_popen()) as popen, \
         patch("divoom_client.binary_resolver.resolve",
               return_value="/resolved/by/version/divoomd") as resolve:
        ctl.start()
    resolve.assert_called_once_with("divoomd")
    assert popen.call_args[0][0][0] == "/resolved/by/version/divoomd"


def test_start_reports_an_honest_error_when_no_daemon_resolves(tmp_path) -> None:
    """Never "running" when nothing was started.

    P4.1's reproduction had `is_running()` reporting success while the spawned
    process was a GUI window. A controller that cannot find its binary must say
    so, not report a healthy server.
    """
    ctl = MCPController(log_path=tmp_path / "x.log")
    with patch("divoom_client.binary_resolver.resolve", return_value=None), \
         patch("divoom_gui.mcp_control.subprocess.Popen") as popen:
        status = ctl.start()
    assert status.running is False
    assert "divoomd" in (status.error or "")
    popen.assert_not_called()
    assert ctl.is_running() is False


def test_start_never_spawns_the_gui_binary(tmp_path) -> None:
    """The structural guard for P4.1's actual failure.

    Whatever the resolver returns, the command must be a daemon invocation —
    never `sys.executable` with a `-m` module, which inside the app is the GUI.
    """
    ctl = MCPController(log_path=tmp_path / "x.log")
    with patch("divoom_gui.mcp_control.subprocess.Popen", return_value=_fake_popen()) as popen, \
         patch("divoom_client.binary_resolver.resolve", return_value="/opt/divoomd"):
        ctl.start()
    cmd = popen.call_args[0][0]
    assert "-m" not in cmd, "spawning a Python module is what launched a second GUI"
    assert cmd[0] != sys.executable
    assert cmd[-1] == "mcp"


def test_start_truncates_existing_log(tmp_path) -> None:
    """Each start() gets a self-contained log — old content must not survive,
    or the GUI card would mix a fresh run with a stale crash trace."""
    log_path = tmp_path / "mcp-server.log"
    log_path.write_text("stale crash from a previous session\n")
    ctl = MCPController(log_path=log_path)
    fake_proc = _fake_popen()
    with patch("divoom_gui.mcp_control.subprocess.Popen", return_value=fake_proc), \
         patch("divoom_client.binary_resolver.resolve", return_value="/opt/divoomd"):
        ctl.start()
    assert log_path.read_bytes() == b""


def test_start_file_not_found_returns_error_status(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    with patch("divoom_gui.mcp_control.subprocess.Popen",
               side_effect=FileNotFoundError("nope")), \
         patch("divoom_client.binary_resolver.resolve", return_value="/opt/divoomd"):
        status = ctl.start()
    assert status.running is False
    assert status.error is not None
    assert "divoomd not found" in status.error
    assert ctl._proc is None


def test_start_oserror_returns_error_status(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    with patch("divoom_gui.mcp_control.subprocess.Popen", side_effect=OSError("boom")), \
         patch("divoom_client.binary_resolver.resolve", return_value="/opt/divoomd"):
        status = ctl.start()
    assert status.running is False
    assert status.error is not None
    assert "failed to spawn MCP server" in status.error


# ── stop() ─────────────────────────────────────────────────────────────


def test_stop_when_not_running_is_noop(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    status = ctl.stop()
    assert status.running is False


def test_stop_sends_sigterm_and_clears_state(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    fake_proc = _fake_popen(pid=555, poll_return=None)
    ctl._proc = fake_proc
    ctl._started_at = 1.0
    ctl._mac = "AA"
    ctl._started_this_session = True
    with patch("divoom_gui.mcp_control.os.killpg") as killpg, \
         patch("divoom_gui.mcp_control.os.getpgid", return_value=555):
        status = ctl.stop()
    killpg.assert_called_once_with(555, signal.SIGTERM)
    fake_proc.wait.assert_called_once()
    assert ctl._proc is None
    assert ctl._started_at is None
    assert ctl._mac is None
    assert ctl._started_this_session is False
    assert status.running is False


def test_stop_escalates_to_sigkill_on_timeout(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "x.log")
    fake_proc = _fake_popen(pid=777, poll_return=None)
    fake_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=3.0), None]
    ctl._proc = fake_proc
    with patch("divoom_gui.mcp_control.os.killpg") as killpg, \
         patch("divoom_gui.mcp_control.os.getpgid", return_value=777):
        ctl.stop()
    assert killpg.call_count == 2
    killpg.assert_any_call(777, signal.SIGTERM)
    killpg.assert_any_call(777, signal.SIGKILL)


def test_stop_second_wait_also_times_out_is_swallowed(tmp_path) -> None:
    """Even if the process refuses to die after SIGKILL, stop() must not raise."""
    ctl = MCPController(log_path=tmp_path / "x.log")
    fake_proc = _fake_popen(pid=778, poll_return=None)
    fake_proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="x", timeout=3.0),
        subprocess.TimeoutExpired(cmd="x", timeout=1.0),
    ]
    ctl._proc = fake_proc
    with patch("divoom_gui.mcp_control.os.killpg"), \
         patch("divoom_gui.mcp_control.os.getpgid", return_value=778):
        status = ctl.stop()
    assert status.running is False


def test_stop_process_already_gone_swallows_lookup_error(tmp_path) -> None:
    """getpgid()/killpg() raising ProcessLookupError (process already reaped
    by the OS) must be swallowed, not propagated."""
    ctl = MCPController(log_path=tmp_path / "x.log")
    fake_proc = _fake_popen(pid=888, poll_return=None)
    ctl._proc = fake_proc
    with patch("divoom_gui.mcp_control.os.getpgid", side_effect=ProcessLookupError()):
        status = ctl.stop()
    assert status.running is False


# ── status() log tail ───────────────────────────────────────────────────


def test_status_hides_log_when_not_started_this_session(tmp_path) -> None:
    log_path = tmp_path / "mcp-server.log"
    log_path.write_text("line1\nline2\n")
    ctl = MCPController(log_path=log_path)
    status = ctl.status()
    assert status.last_log_lines == []


def test_status_tails_log_when_started_this_session(tmp_path) -> None:
    log_path = tmp_path / "mcp-server.log"
    lines = [f"line {i}" for i in range(30)]
    log_path.write_text("\n".join(lines) + "\n")
    ctl = MCPController(log_path=log_path)
    ctl._started_this_session = True
    status = ctl.status()
    assert status.last_log_lines == lines[-MCPController.LOG_TAIL_LINES:]


def test_status_missing_log_file_returns_empty_lines(tmp_path) -> None:
    ctl = MCPController(log_path=tmp_path / "does-not-exist.log")
    ctl._started_this_session = True
    status = ctl.status()
    assert status.last_log_lines == []


def test_status_oserror_reading_log_returns_error_status(tmp_path) -> None:
    log_path = tmp_path / "mcp-server.log"
    log_path.write_text("hello\n")
    ctl = MCPController(log_path=log_path)
    ctl._started_this_session = True
    ctl._proc = _fake_popen(pid=42, poll_return=None)
    ctl._started_at = 5.0
    ctl._mac = "AA"
    with patch("builtins.open", side_effect=OSError("disk gone")):
        status = ctl.status()
    assert status.error is not None
    assert "failed to read log" in status.error
    assert status.pid == 42
    assert status.mac == "AA"
    assert status.log_path == str(log_path)


# ── singleton ────────────────────────────────────────────────────────────


def test_instance_returns_singleton() -> None:
    MCPController._instance = None
    try:
        a = MCPController.instance()
        b = MCPController.instance()
        assert a is b
        assert isinstance(a, MCPController)
    finally:
        MCPController._instance = None


# ── R70 P4.2: it actually serves MCP ─────────────────────────────────────────

def test_the_spawned_process_really_answers_json_rpc(tmp_path) -> None:
    """The end-to-end proof, and the one P4.1 showed was missing.

    Every assertion above checks what the controller ASKS for. This checks that
    what it asks for is an MCP server: spawn the resolved binary the same way
    `start()` does and complete a real `initialize` + `tools/list` handshake.

    The old command passed every argv assertion in this file and served nothing.
    """
    import json
    import subprocess as sp

    from tests.support.daemon_binary import require_divoomd

    exe = require_divoomd()
    proc = sp.Popen([str(exe), "mcp"], stdin=sp.PIPE, stdout=sp.PIPE,
                    stderr=sp.DEVNULL, text=True)
    try:
        requests = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
        )
        out, _ = proc.communicate(requests, timeout=30)
    except sp.TimeoutExpired:
        proc.kill()
        raise
    finally:
        if proc.poll() is None:
            proc.kill()

    replies = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(replies) >= 2, f"expected two JSON-RPC replies, got: {out!r}"

    init = replies[0]["result"]
    assert init["serverInfo"]["name"] == "divoom-control"
    assert "protocolVersion" in init

    tools = replies[1]["result"]["tools"]
    assert len(tools) >= 13, f"only {len(tools)} tools"
    names = {t["name"] for t in tools}
    assert {"set_brightness", "set_volume"} <= names, names
