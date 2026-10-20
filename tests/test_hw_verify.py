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

THE EXPECTATION IS DERIVED, NOT ASSERTED (the class this file also pins):

  * a panel check shows the operator the frame the DAEMON painted -- the
    packet carries no hand-written description of what the panel shows,
    because a description written here goes stale the moment the daemon's
    renderer changes, and a stale description grades a WORKING widget FAIL
    (the `weather` check said the device "cycles" after the daemon started
    drawing one combined frame);
  * a widget that painted NOTHING is a machine FAIL, not a question for the
    operator;
  * a check whose precondition is unmet (nothing playing) is a SKIP, not a
    FAIL and not a PASS;
  * the packet pushes to, and reads, the panel the operator is watching.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

hw = pytest.importorskip("hw_verify")
hw_expect = pytest.importorskip("hw_expect")


@pytest.fixture(autouse=True)
def _no_settle_sleep(monkeypatch):
    """The packet's settle times are for a real panel, not for a fake client.

    Patched on the `time` module itself: the runner, the checks and the
    frame helpers all sleep through it.
    """
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def _frame_data_url(size: int = 16, colour=(0, 0, 255)) -> str:
    """A real PNG data URL, built by the same encoder the packet uses."""
    png = hw_expect.raw_to_png(bytes(colour) * (size * size), size)
    return "data:image/png;base64," + base64.b64encode(png).decode()


class FakeClient:
    """Enough DaemonClient for the packet, with scriptable replies.

    The defaults are the daemon's HONEST answers: a frame was painted for
    whatever job is running, a widget renders, and something is playing. A
    test that wants a different world says so in `replies`.
    """

    def __init__(self, status=None, call_reply=None, raises=False, replies=None):
        self._status = status if status is not None else {"connected": False, "mac": None}
        self._call_reply = call_reply if call_reply is not None else {"success": True}
        self._raises = raises
        self._replies = replies or {}
        self._kind = ""
        self.calls = []

    def device_status(self):
        if self._raises:
            raise ConnectionRefusedError("no daemon")
        return self._status

    def device_call(self, method, args=None, kwargs=None, *, mac=None):
        self.calls.append(("device_call", method, args, mac))
        if self._raises:
            raise RuntimeError("socket closed")
        return self._replies.get(method, self._call_reply)

    def send_command(self, command, args=None):
        self.calls.append(("send_command", command, args))
        if self._raises:
            raise RuntimeError("socket closed")
        if command == "live_job_start" and isinstance(args, dict):
            self._kind = args.get("kind", "")
        if command in self._replies:
            return self._replies[command]
        if command == "now_playing":
            return {"success": True, "playing": True}
        if command == "get_device_activity":
            return {"success": True,
                    "activity": {"AA:BB": {"kind": self._kind,
                                           "preview": _frame_data_url()}}}
        if command == "render_widget":
            return {"success": True,
                    "frame_rgb_b64": base64.b64encode(bytes((9, 9, 9)) * 256).decode()}
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
    # Any device-bound check exercises this path. Selected by PROPERTY, not
    # by id: R73 pruned the two checks these named, and a hardcoded id turns
    # "the packet shrank" into an IndexError three tests away from the edit.
    checks = [c for c in hw.build_checks() if c.needs_device][:1]
    assert checks, "no device-bound checks left in the packet"
    hw.run_packet(client, checks, interactive=False, results=results)
    assert results[0].verdict == hw.FAIL
    assert "unknown method" in results[0].detail


def test_a_raising_call_is_FAIL_not_a_crash():
    class Boom(FakeClient):
        # BOTH transports, because the packet uses both: the widget checks are
        # `live_job_start` socket commands and only custom_art is a device_call.
        # Raising from device_call alone made this test silently stop covering
        # the first check in the packet the moment that check changed transport.
        def device_call(self, method, args=None, kwargs=None, *, mac=None):
            raise RuntimeError("socket closed")

        def send_command(self, command, args=None):
            raise RuntimeError("socket closed")

    client = Boom(status={"connected": True, "mac": "AA:BB"})
    results = []
    # Any device-bound check exercises this path. Selected by PROPERTY, not
    # by id: R73 pruned the two checks these named, and a hardcoded id turns
    # "the packet shrank" into an IndexError three tests away from the edit.
    checks = [c for c in hw.build_checks() if c.needs_device][:1]
    assert checks, "no device-bound checks left in the packet"
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


def test_self_test_fails_loudly_when_the_probe_ITSELF_raises():
    """A branch that RAISES is a FAIL — never a warning, never a crash.

    This is the shape of the defect that started all of it: the smoke script
    caught the NameError raised while printing a device, reported it as a
    warning, and exited 0. A self-test that crashes is better than one that
    lies, but a self-test that reports FAIL with a non-zero exit is what the
    contract says: 1 = the instrument is broken.
    """
    class Boom(FakeClient):
        def device_call(self, method, args=None):
            raise RuntimeError("socket closed")

    client = Boom(status={"connected": True, "mac": "AA:BB"})
    assert hw.self_test(client) == 1


def test_the_self_test_proves_the_PACKET_records_the_failure():
    """Not only that the daemon refused — that the packet wrote down a FAIL.

    The daemon's answer is the daemon's business. The property the packet
    claims is 'I can report a failure', and that is only true if the verdict
    lands in the results and the exit code follows it.
    """
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": False, "error": "unknown method 'x'"})
    assert hw.self_test(client) == 0

    results = []
    probe = hw.CallCheck(id="_probe", title="t", look="l",
                         method="definitely.not.a.real.method", args=[],
                         needs_device=False)
    hw.run_packet(client, [probe], interactive=False, results=results)
    assert [r.verdict for r in results] == [hw.FAIL], results


def test_the_run_exits_nonzero_when_a_check_fails(monkeypatch):
    """A FAIL in the results must be a non-zero exit, not a red line."""
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": False, "error": "unknown method"})
    monkeypatch.setattr(hw, "require_daemon", lambda path: client)
    monkeypatch.setattr(sys, "argv", ["hw_verify.py"])
    assert hw.main() == 1


def test_the_run_is_PARTIAL_when_nobody_was_watching(monkeypatch):
    """No tty means every LOOK is UNKNOWN — and a run that proved nothing
    must not exit 0. The silent pass is the thing this packet refuses."""
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": True})
    monkeypatch.setattr(hw, "require_daemon", lambda path: client)
    monkeypatch.setattr(sys, "argv", ["hw_verify.py"])
    assert hw.main() == 3


def test_every_check_states_what_to_look_at():
    """A check whose prompt does not describe the SEEN thing cannot be answered."""
    for c in hw.build_checks():
        assert c.look and len(c.look) > 30, f"{c.id} has no usable LOOK text"
        assert c.tags, f"{c.id} is not traceable to a plan step"


def test_an_expected_failure_is_XFAIL_and_does_not_redden_the_run():
    """The weather_city canary fails every run by design.

    Recording that as FAIL would make `hw_verify` permanently red, and a check
    that is always red is one people stop reading — the same reason a randomly
    failing e2e gate teaches `--no-verify`.
    """
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": False, "error": "RC=1 Failed"})
    check = hw.CommandCheck(id="canary", title="t", look="l",
                            command="search_weather_city",
                            expect_fail="known dead server-side")
    results = []
    hw.run_packet(client, [check], interactive=False, results=results)
    assert results[0].verdict == hw.XFAIL
    assert results[0].verdict != hw.FAIL


def test_an_expected_failure_that_SUCCEEDS_is_surfaced_as_XPASS():
    """The canary singing is the whole point of keeping it in the packet."""
    client = FakeClient(status={"connected": True, "mac": "AA:BB"},
                        call_reply={"success": True, "cities": ["London"]})
    check = hw.CommandCheck(id="canary", title="t", look="l",
                            command="search_weather_city",
                            expect_fail="known dead server-side")
    results = []
    hw.run_packet(client, [check], interactive=False, results=results)
    assert results[0].verdict == hw.XPASS, "a revived endpoint must not read as a pass"


# ── The class fix: the expectation is DERIVED from the daemon ─────────────
#
# The packet used to describe what the panel should look like, in prose, and
# the prose went stale: the `weather` check still said the device CYCLES
# after the daemon started drawing ONE combined frame, so a working widget
# was graded FAIL by a human holding the device. A description written here
# is a claim about a renderer that lives in another language; nothing in CI
# could tell when it stopped being true.

def _ctx(tmp_path, mac="AA:BB"):
    return {"mac": mac, "size": 16, "frames_dir": str(tmp_path)}


def _widget_client(preview_url=None, **replies):
    base = {
        "live_job_start": {"success": True},
        "live_jobs_stop_for": {"success": True, "count": 0},
        "get_device_activity": {"success": True, "activity": {}},
    }
    if preview_url:
        base["get_device_activity"] = {
            "success": True,
            "activity": {"AA:BB": {"kind": "sysmon", "preview": preview_url}},
        }
    base.update(replies)
    return FakeClient(status={"connected": True, "mac": "AA:BB"}, replies=base)


def test_no_panel_check_carries_a_hand_written_description():
    """The anti-drift rule: a panel check shows a FRAME, not a sentence.

    Only a socket-level check (no picture exists) may answer in words.
    """
    for c in hw.build_checks():
        if c.look != hw.PANEL_LOOK:
            assert isinstance(c, hw.CommandCheck), (
                f"{c.id} carries a hand-written LOOK; a description written "
                f"here goes stale when the daemon's renderer changes")


def test_a_widget_that_painted_nothing_is_a_machine_FAIL(tmp_path):
    """Nothing on the panel is not a question for the operator."""
    client = _widget_client()
    check = hw.LiveJobCheck(id="sysmon", title="t", kind="sysmon")
    results = []
    hw.run_packet(client, [check], interactive=False, results=results,
                  ctx=_ctx(tmp_path))
    assert [r.verdict for r in results] == [hw.FAIL], results
    assert "painted no" in results[0].detail


def test_the_operator_is_shown_the_frame_the_daemon_painted(tmp_path):
    client = _widget_client(_frame_data_url())
    check = hw.LiveJobCheck(id="sysmon", title="t", kind="sysmon")
    exp = check.expectation(client, _ctx(tmp_path))
    assert exp.verdict == ""
    assert "16x16" in exp.text
    saved = tmp_path / "sysmon.png"
    assert saved.is_file(), "the frame must be SAVED as evidence"
    assert saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_nothing_playing_is_SKIP_not_FAIL(tmp_path):
    """An unmet precondition is neither a failure of the product nor a pass."""
    client = _widget_client(now_playing={"success": True, "playing": False})
    check = hw.LiveJobCheck(id="album_art", title="t", kind="music",
                            needs_now_playing=True)
    exp = check.expectation(client, _ctx(tmp_path))
    assert exp.verdict == hw.SKIP
    assert "nothing" in exp.detail.lower()


def test_a_raising_expectation_is_a_FAIL_not_a_crash(tmp_path):
    class Boom(hw.Check):
        def drive(self, client, ctx):
            return True, "ok"

        def expectation(self, client, ctx):
            raise RuntimeError("no frame")

    client = _widget_client()
    results = []
    hw.run_packet(client, [Boom(id="x", title="t")], interactive=False,
                  results=results, ctx=_ctx(tmp_path))
    assert [r.verdict for r in results] == [hw.FAIL], results
    assert "no frame" in results[0].detail


def test_the_packet_pushes_to_the_panel_it_reads(tmp_path):
    """A mac-less device_call goes to whichever panel connected LAST."""
    image = tmp_path / "img.png"
    image.write_bytes(hw_expect.raw_to_png(bytes((1, 2, 3)) * 256, 16))
    rgb = base64.b64encode(bytes((4, 5, 6)) * 256).decode()
    client = _widget_client(render_widget={"success": True, "frame_rgb_b64": rgb})
    check = hw.ImageCheck(id="custom_art", title="t",
                          method="display.show_image", path_arg="$image")
    ctx = _ctx(tmp_path)
    ctx["image"] = str(image)
    fired, _ = check.drive(client, ctx)
    assert fired
    macs = {c[3] for c in client.calls if c[0] == "device_call"}
    assert macs == {"AA:BB"}, macs


def test_the_image_expectation_is_the_daemons_own_rendering(tmp_path):
    image = tmp_path / "img.png"
    image.write_bytes(hw_expect.raw_to_png(bytes((1, 2, 3)) * 256, 16))
    rgb = base64.b64encode(bytes((4, 5, 6)) * 256).decode()
    client = _widget_client(render_widget={"success": True, "frame_rgb_b64": rgb})
    check = hw.ImageCheck(id="custom_art", title="t",
                          method="display.show_image", path_arg="$image")
    ctx = _ctx(tmp_path)
    ctx["image"] = str(image)
    exp = check.expectation(client, ctx)
    assert exp.verdict == ""
    assert (tmp_path / "custom_art.png").is_file()
    sent = [c for c in client.calls if c[0] == "send_command" and c[1] == "render_widget"]
    assert sent, "the expectation must come from the daemon's own renderer"

