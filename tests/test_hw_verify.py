"""The hardware packet must not be able to pass by silence (R71 P2.0/P2.1).

A verification checklist that cannot report failure is a form, not an
instrument -- and this repo has the receipts: `pic_scan_ctrl` has been
"accepted without error" since 2026-07-13 and nobody has ever seen it do
anything, while sysmon and the album cover were "verified" at the socket and
never once looked at.

So the packet's HONESTY properties are pinned here, not its checks:

  * with nobody watching, a LOOK is UNKNOWN -- never PASS;
  * with no device attached, a device check is FAIL -- never SKIP, because
    going quiet when the hardware is absent is how a form behaves;
  * it refuses to start a daemon (macOS TCC: a shell-launched one dies on its
    first scan with SIGABRT and an empty stderr, which reads as a product
    crash and is not one);
  * and the self-test distinguishes "failed for the right reason" from "failed
    at a precondition" -- the first version did not, and reported a green line
    it had not earned.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

hw = pytest.importorskip("hw_verify")


class FakeClient:
    """Enough DaemonClient for the packet, with scriptable replies."""

    def __init__(self, status=None, call_reply=None, raises=False):
        self._status = status if status is not None else {"connected": False, "mac": None}
        self._call_reply = call_reply if call_reply is not None else {"success": True}
        self._raises = raises

    def device_status(self):
        if self._raises:
            raise ConnectionRefusedError("no daemon")
        return self._status

    def device_call(self, method, args=None):
        return self._call_reply

    def send_command(self, command, args=None):
        return self._call_reply


def test_look_is_unknown_when_nobody_is_watching():
    """The single most important property: no tty cannot mean PASS."""
    verdict, note = hw.ask("did you see it?", interactive=False)
    assert verdict == hw.UNKNOWN
    assert verdict != hw.PASS
    assert "nobody" in note.lower()


def test_device_check_with_no_device_is_FAIL_not_SKIP():
    results = []
    checks = [c for c in hw.build_checks() if c.needs_device][:1]
    hw.run_packet(FakeClient(), checks, interactive=False, results=results)
    assert len(results) == 1
    assert results[0].verdict == hw.FAIL, results[0]
    assert "no device" in results[0].detail.lower()


def test_rejected_command_is_FAIL_even_with_a_device():
    """A daemon that says success:False must not be read as 'sent, so fine'."""
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": False, "error": "unknown method"})
    results = []
    checks = [c for c in hw.build_checks() if c.id == "pic_scan"]
    hw.run_packet(client, checks, interactive=False, results=results)
    assert results[0].verdict == hw.FAIL
    assert "unknown method" in results[0].detail


def test_a_raising_call_is_FAIL_not_a_crash():
    class Boom(FakeClient):
        def device_call(self, method, args=None):
            raise RuntimeError("socket closed")

    client = Boom(status={"connected": True, "mac": "AA:BB"})
    results = []
    checks = [c for c in hw.build_checks() if c.id == "pic_scan"]
    hw.run_packet(client, checks, interactive=False, results=results)
    assert results[0].verdict == hw.FAIL
    assert "socket closed" in results[0].detail


def test_require_daemon_refuses_rather_than_spawning():
    """It must never start a daemon: TCC makes a shell-launched one die blind."""
    with pytest.raises(SystemExit) as exc:
        hw.require_daemon("/tmp/divoom_hw_verify_definitely_absent.sock")
    assert exc.value.code == 2


def test_self_test_flags_a_precondition_refusal_as_partial():
    """The first version called this a pass. It had not earned one.

    With no device attached the daemon refuses an invalid method at the
    no-device precondition, before it ever looks at the name -- so 'the packet
    rejects a bogus method' is still untested and must not read as green.
    """
    client = FakeClient(status={"connected": False, "mac": None},
                        call_reply={"success": False, "error": "no device connected"})
    assert hw.self_test(client) == 3


def test_self_test_passes_when_the_rejection_is_about_the_method():
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": False, "error": "unknown method 'x'"})
    assert hw.self_test(client) == 0


def test_self_test_fails_loudly_if_a_bogus_call_reports_success():
    """If an invalid method returns success, no PASS in the packet means anything."""
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": True})
    assert hw.self_test(client) == 1


def test_every_check_states_what_to_look_at():
    """A check whose prompt does not describe the SEEN thing cannot be answered."""
    for c in hw.build_checks():
        assert c.look and len(c.look) > 30, f"{c.id} has no usable LOOK text"
        assert c.tags, f"{c.id} is not traceable to a plan step"
