"""L5: `divoom-control mcp-server` really serves MCP, by handing off to Rust.

Every other test in this area checks what something ASKS for — the argv, the
env, the resolved path. This module runs the thing an MCP client actually runs,
`python3 -m divoom_lib.cli mcp-server`, against a real daemon over a real
socket, and reads a real JSON-RPC exchange off its stdout.

The reason it exists in this shape: the delegation it proves replaced an
implementation that also worked. A green "we exec the binary" test would have
been satisfied by the old Python server too, since both answer `tools/list`.
What distinguishes them is the CATALOG — 14 native tools against the Python
13 — so the assertions here are on the catalog, and this test was calibrated
red against the Python implementation before the switch.

The daemon is a real `divoomd` process using its built-in `mock` transport (no
radio, no device), spawned on a temporary socket. A fake would do for the
protocol but not for `ensure_daemon`'s version handshake, which is the step that
actually breaks when it drifts.
"""
from __future__ import annotations

import json
import os
import subprocess as sp
import sys
from pathlib import Path

import pytest

from tests.support.daemon_binary import require_divoomd

REPO_ROOT = Path(__file__).resolve().parent.parent

# The 14 tools the native server ships, which is the 13 the Python catalog
# shipped plus `list_screens`. Written out in full rather than counted, because
# "14" alone would still pass if one tool were swapped for another; the
# superset assertion in divoomd/src/mcp_tools.rs checks the same thing from the
# other side.
NATIVE_TOOLS = {
    "set_volume",
    "set_brightness",
    "set_light_mode",
    "set_weather",
    "set_alarm",
    "set_radio",
    "set_low_power",
    "set_screen_orientation",
    "show_image",
    "push_animation",
    "play_sound",
    "get_capabilities",
    "get_device_state",
    "list_screens",
}

HANDSHAKE = (
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
)


def _entry_point() -> list[str]:
    """The command an MCP client's config names — the real one, not a wrapper."""
    return [sys.executable, "-m", "divoom_lib.cli", "mcp-server"]


def _serve(entry: list[str], socket_path: str, stdout=None) -> sp.CompletedProcess:
    """Run the entry point to completion with `HANDSHAKE` on stdin, then EOF.

    `stdout` defaults to a pipe we capture; pass a file object to model the
    failure mode where the client is NOT an MCP client (the GUI points stdout at
    a log file). `subprocess` forbids `capture_output` alongside an explicit
    stdout, so the two cases are spelled out rather than merged.
    """
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    # A stale token/host in the caller's environment would send the handoff to
    # a remote daemon instead of the fixture, so the test says which one.
    for var in ("DIVOOM_DAEMON_HOST", "DIVOOM_DAEMON_PORT", "DIVOOM_DAEMON_TOKEN"):
        env.pop(var, None)
    return sp.run(
        [*entry, "--socket", socket_path],
        input=HANDSHAKE,
        stdout=stdout if stdout is not None else sp.PIPE,
        stderr=sp.PIPE,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=env,
    )


@pytest.fixture
def live_daemon(tmp_path):
    """A real divoomd on a temp socket, with no radio and no device.

    Waited for in two stages, as `test_daemon_connect_edge_e2e.py` does: the
    socket appearing and the daemon answering `get_status` are separate events,
    and `daemon_alive` deliberately does not retry (`connect_retries=0`, so a
    device op holding the mutex cannot make a live daemon look dead). Asking it
    once and concluding "never bound" is how this fixture first failed.
    """
    import tempfile
    import time

    from divoom_client.daemon_client import DaemonClient, daemon_alive, spawn_daemon

    require_divoomd()  # skip early rather than fail later with a socket error
    # NOT tmp_path: pytest's base is already ~120 characters and a Unix socket
    # path is capped at 104 bytes (sun_path), so the daemon fails to bind and
    # the fixture reports "never bound" — which is what the first draft did.
    # The whole path has to stay short, so the directory is in /tmp too.
    sock_dir = tempfile.mkdtemp(prefix="divoom-mcp-")
    socket_path = os.path.join(sock_dir, "d.sock")
    assert len(socket_path) < 104, f"socket path too long to bind: {socket_path}"
    handle = spawn_daemon(socket_path)
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not daemon_alive(socket_path):
            time.sleep(0.1)
        if not daemon_alive(socket_path):
            pytest.fail(f"the daemon never bound {socket_path}")
        client = DaemonClient(socket_path)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if client.send_command("get_status").get("success"):
                break
            time.sleep(0.1)
        else:
            pytest.fail("the daemon never answered get_status")
        yield socket_path
    finally:
        # Only ever stop the daemon THIS fixture spawned.
        if isinstance(handle, sp.Popen):
            handle.terminate()
            try:
                handle.wait(timeout=10)
            except sp.TimeoutExpired:
                handle.kill()
        elif isinstance(handle, int):
            try:
                os.kill(handle, 15)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(handle, 0)
            except ChildProcessError:
                pass


def test_the_entry_point_serves_the_native_catalog(live_daemon) -> None:
    """The proof the whole phase rests on.

    Run the documented entry point, against a real daemon, and require the
    NATIVE catalog back. This fails against the Python implementation (13
    tools, no `list_screens`) — which is how it was calibrated — and passes only
    when the handoff to `divoomd mcp` is real.
    """
    proc = _serve(_entry_point(), live_daemon)

    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert len(replies) >= 2, f"expected a handshake, got: {proc.stdout!r}"

    init = replies[0]["result"]
    assert init["serverInfo"]["name"] == "divoom-control"
    assert init["protocolVersion"], "the client needs a negotiated version"
    assert init["capabilities"]["tools"] is not None

    tools = replies[1]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == NATIVE_TOOLS, (
        f"the entry point served a different catalog than the native server: "
        f"missing={NATIVE_TOOLS - names} unexpected={names - NATIVE_TOOLS}"
    )
    for t in tools:
        assert t["description"], f"{t['name']} has no description"
        assert t["inputSchema"]["type"] == "object", t["name"]


def test_the_handoff_is_visible_in_the_log(live_daemon) -> None:
    """A tool call that crosses a process boundary has to be diagnosable.

    The old implementation logged "MCP server starting: daemon=…, tools=N".
    The handoff logs which binary took over and which daemon it was pointed at;
    without that line, "the server is broken" and "the server never started"
    look the same in a log file.
    """
    proc = _serve(_entry_point(), live_daemon)
    assert "handing off to" in proc.stderr, proc.stderr
    assert "divoomd" in proc.stderr, proc.stderr
    assert live_daemon in proc.stderr, (
        f"the log must name the daemon it connected to: {proc.stderr}"
    )


def test_a_redirected_stdout_gets_a_diagnosis_not_a_traceback(live_daemon, tmp_path) -> None:
    """The stdio guard, proven on the real binary and in the real failure mode.

    A unit test of the fd-classification helper cannot see whether `run()` calls
    it, so this is the test that decides: run the entry point with stdout
    pointed at a file — what the GUI does, and what a user does with
    `> out.txt` — and require one clean sentence instead of the asyncio
    "Pipe transport is only for pipes, sockets and character devices" traceback
    the Python server used to die with.
    """
    out = tmp_path / "captured.txt"
    with out.open("w") as handle:
        proc = _serve(_entry_point(), live_daemon, stdout=handle)

    stderr = proc.stderr
    assert "not connected to an MCP client" in stderr, (
        f"expected the stdio diagnosis, got: {stderr}"
    )
    assert "MCP client" in stderr, "the message must say what to do instead"
    assert "Traceback" not in stderr, f"a traceback is the failure this replaces:\n{stderr}"
    # Nothing was written to the redirected stdout: the server refused rather
    # than serving into a file nobody is reading.
    assert out.read_text() == ""


def test_a_missing_daemon_binary_says_so_instead_of_silently_serving(
    monkeypatch, capsys
) -> None:
    """The failure path must name what is missing, and must be loud.

    In-process, deliberately. The first version of this test ran the entry point
    as a subprocess with `resolve` monkeypatched, and it PASSED for the wrong
    reason: the patch is in the parent, the resolution happens in the child, the
    child found the binary and served — so the test asserted a return code that
    had nothing to do with the branch it was written for. A test that cannot
    reach the code it names is worse than no test, because it looks green.

    So the branch is reached directly here, and the subprocess path stays covered
    by the three tests above.
    """
    from divoom_client import binary_resolver
    from divoom_lib.cli_commands import _native_mcp_binary

    monkeypatch.setattr(binary_resolver, "resolve", lambda *a, **k: None)
    monkeypatch.setattr(binary_resolver, "stale_report", lambda *a, **k: [])

    with pytest.raises(SystemExit) as exit_info:
        _native_mcp_binary()
    assert exit_info.value.code != 0, "a missing binary is a failure, not a no-op"
    err = capsys.readouterr().err
    assert "divoomd" in err, err
    assert "Traceback" not in err, err
    # It has to say what to do, or a user without a toolchain is stuck.
    assert binary_resolver.rebuild_hint("divoomd") in err, err


def test_a_stale_binary_is_named_rather_than_reported_as_missing(monkeypatch, capsys) -> None:
    """"No binary" and "a binary that is the wrong version" are different bugs.

    The second is the one that bit this repo: a `target/release/divoomd` left
    over from the last release satisfies a location-based search and then serves
    old code. When the resolver can see one, the message has to include it.
    """
    from divoom_client import binary_resolver
    from divoom_lib.cli_commands import _native_mcp_binary

    monkeypatch.setattr(binary_resolver, "resolve", lambda *a, **k: None)
    monkeypatch.setattr(
        binary_resolver,
        "stale_report",
        lambda *a, **k: [("/opt/divoom/target/release/divoomd", "0.38.0")],
    )
    with pytest.raises(SystemExit):
        _native_mcp_binary()
    err = capsys.readouterr().err
    assert "0.38.0" in err, f"the stale version must be reported: {err}"
    assert "release/divoomd" in err, f"and the path that had it: {err}"


def test_the_handoff_reaches_the_binary_the_resolver_named(monkeypatch) -> None:
    """The exec is the delegation, so assert the exec.

    `os.execv` is mocked rather than performed (performing it would replace the
    test runner), and what matters is checked: the resolved path, the `mcp`
    argument, and the environment the daemon target travels in. This is the one
    assertion that `os.execv` is called at all — a version of this command that
    quietly returned 0 without handing over would satisfy every test above,
    because the client's pipes would simply close.
    """
    import argparse
    import asyncio
    import os as os_mod

    from divoom_lib import cli_commands

    calls: list[tuple] = []

    def fake_execv(path, argv):
        calls.append((path, argv))
        raise SystemExit(0)  # execv never returns; this stands in for success

    monkeypatch.setattr(os_mod, "execv", fake_execv)
    monkeypatch.setattr(cli_commands, "_native_mcp_binary", lambda: "/opt/divoomd")

    args = argparse.Namespace(
        host=None, port=9009, token=None, socket="/tmp/divoom-x.sock", mac=None
    )

    # ensure_daemon is imported inside the function from the client module, so
    # patch it where it lives.
    from divoom_client import daemon_client

    monkeypatch.setattr(daemon_client, "ensure_daemon", lambda *a, **k: object())
    with pytest.raises(SystemExit):
        asyncio.run(cli_commands.cmd_mcp_server(args))

    assert calls, "the command must exec the native server, not return"
    path, argv = calls[0]
    assert path == "/opt/divoomd"
    assert argv == ["/opt/divoomd", "mcp"]
    assert os.environ["DIVOOM_SOCKET"] == "/tmp/divoom-x.sock", (
        "the daemon target has to reach the child in the environment"
    )
