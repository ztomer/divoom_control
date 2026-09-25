"""L5 item 2: the CLI's device verbs run in `divoomd`, not in Python.

Same shape as `test_mcp_delegation.py`, and for the same reason. `divoom-control
set-volume 5` used to validate, resolve a panel, connect it and issue a
`device_call` from Python. The device command now lives in `divoomd`; the CLI
keeps one thing, `resolve_target_mac`, because scanning for a panel when none
is linked and connecting one that is down are conveniences the daemon does not
provide.

What these tests prove, stated plainly so nobody reads more into them: the REAL
entry point runs, against a REAL BLE-free daemon, and the command SUCCEEDS with
the native verb's exact output. The mock transport records the bytes it was sent
in-process, where a Python test over a socket cannot see them, so the wire
assertions for the verb itself live in `divoomd/src/verbs_tests.rs` — against a
real socket, with the request read back. What is proved HERE is the half only
this side can prove: that the command a user types reaches the native binary and
comes back as that binary's result.

The native output is what distinguishes the two implementations. The Python one
printed `set volume to 5/15 (ok=True)`; the native one prints `set volume to
5/15` and carries failure in the exit code. Asserting the exact sentence is
therefore a real assertion about which implementation ran, not a formatting
preference.
"""
from __future__ import annotations

import os
import subprocess as sp
import sys
import tempfile
import time
from pathlib import Path

import pytest

from tests.support.daemon_binary import require_divoomd

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def live_daemon(tmp_path):
    """A real divoomd with a MOCK device connected, on a short socket path.

    Short, because a Unix socket path is capped at 104 bytes and pytest's
    `tmp_path` is already longer than that — the daemon then fails to bind and
    the fixture reports "never bound", which reads like a daemon bug.
    """
    from divoom_client.daemon_client import DaemonClient, daemon_alive, spawn_daemon

    require_divoomd()
    sock_dir = tempfile.mkdtemp(prefix="divoom-verbs-")
    socket_path = os.path.join(sock_dir, "d.sock")
    assert len(socket_path) < 104, socket_path
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
        # A mock device, so the call has something to succeed against. No radio.
        conn = client.send_command("connect", {"mock": True})
        assert conn.get("success") is True, conn
        yield socket_path
    finally:
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


def _run(*argv: str) -> sp.CompletedProcess:
    """Run the real CLI entry point."""
    return sp.run(
        [sys.executable, "-m", "divoom_lib.cli", *argv],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )


def test_set_volume_reaches_the_native_verb(live_daemon) -> None:
    proc = _run("set-volume", "5", "--socket", live_daemon)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    # The native sentence, with no `(ok=...)`: the Python implementation could
    # not produce this line, so it is the handoff being observed.
    assert proc.stdout.strip() == "set volume to 5/15", proc.stdout
    assert "handing off to" in proc.stderr, proc.stderr


def test_set_brightness_reaches_the_native_verb(live_daemon) -> None:
    proc = _run("set-brightness", "40", "--socket", live_daemon)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert proc.stdout.strip() == "set brightness to 40%", proc.stdout


def test_json_output_is_the_native_structures_not_a_python_repr(live_daemon) -> None:
    """`--json` used to print a Python-captured string; it is now real JSON.

    Asserted by PARSING it. A test that compared the text would pass against a
    Python dict repr and against whatever the native binary prints, which is
    exactly the ambiguity this is here to end.
    """
    import json

    proc = _run("set-volume", "7", "--socket", live_daemon, "--json")
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True, payload
    assert payload["level"] == 7, payload


def test_push_image_reaches_the_native_verb(live_daemon, tmp_path) -> None:
    # A REAL png, written with the repo's own encoder rather than hex typed by
    # hand: the first draft of this test carried a hand-typed 1x1 whose digit
    # count was odd, and the test failed on `bytes.fromhex` — a fixture bug that
    # reads exactly like a product bug. The daemon decodes this one, so a
    # failure below is the daemon refusing a valid image.
    from PIL import Image

    raw = bytes([(x * 16) % 256 for x in range(16 * 16 * 3)])
    img = tmp_path / "probe.png"
    Image.frombytes("RGB", (16, 16), raw).save(img)
    proc = _run("push-image", str(img), "--socket", live_daemon)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "probe.png" in proc.stdout, proc.stdout


def test_an_out_of_range_value_is_refused_before_the_daemon_is_touched(live_daemon) -> None:
    """The ordering property, which is why the check stayed in Python.

    Validation runs before `resolve_target_mac`, so a bad number cannot make the
    CLI connect to a panel on its way to reporting a typo. The error text is the
    Python one, which is why this can be asserted exactly.
    """
    proc = _run("set-volume", "16", "--socket", live_daemon)
    assert proc.returncode == 2, proc
    assert "volume must be 0..15" in proc.stderr, proc.stderr
    assert "handing off" not in proc.stderr, (
        f"it must not have reached the native verb: {proc.stderr}"
    )


def test_the_weather_verb_reaches_the_native_verb(live_daemon) -> None:
    # The baseline capability table has has_weather=True, so this needs no
    # --type: it is the mock panel's documented default.
    proc = _run("set-temperature", "18", "--weather", "clear", "--socket", live_daemon)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "18" in proc.stdout and "clear" in proc.stdout, proc.stdout


def test_the_radio_verb_reaches_the_native_verb(live_daemon) -> None:
    # FM is NOT in the baseline table, so the capability check refuses unless a
    # type with a radio is named. That refusal is the point: it proves the check
    # is still in Python and still runs BEFORE the handoff.
    refused = _run("set-radio", "911", "--socket", live_daemon)
    assert refused.returncode == 1, refused
    assert "has no FM radio" in refused.stderr, refused.stderr
    assert "handing off" not in refused.stderr, (
        f"it must not have reached divoomd: {refused.stderr}"
    )

    # With a radio-capable type it goes through. DITOO is in the table.
    proc = _run("set-radio", "911", "--type", "DITOO", "--socket", live_daemon)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "91.1 MHz" in proc.stdout, proc.stdout


def test_the_alarm_verb_reaches_the_native_verb(live_daemon) -> None:
    proc = _run("set-alarm", "07:30", "--socket", live_daemon)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "07:30" in proc.stdout, proc.stdout


def test_a_malformed_alarm_time_is_refused_by_the_native_verb(live_daemon) -> None:
    """`25:00` passes the CLI's own split-and-int check and is caught by the
    native one, which knows the ranges. Both are needed: the CLI's catches a
    non-number, the native's catches an impossible hour."""
    proc = _run("set-alarm", "25:00", "--socket", live_daemon)
    assert proc.returncode != 0, proc
    assert "0..23" in proc.stderr, proc.stderr


def test_a_missing_daemon_still_says_what_to_start(live_daemon, tmp_path) -> None:
    """The delegation must not cost the CLI its best error message.

    This one has to keep working with no daemon at all, which is the situation
    the message exists for — so the socket has to be one nothing is listening
    on, not the fixture's.
    """
    missing = str(tmp_path / "definitely-not-here.sock")
    proc = _run("set-volume", "5", "--socket", missing)
    assert proc.returncode == 3, proc
    assert "no divoomd daemon is running" in proc.stderr, proc.stderr
    assert "Bluetooth grant" in proc.stderr, proc.stderr
