#!/usr/bin/env python3
"""The packet's checks — what it asks the device, and what it expects to see.

Split out of `hw_verify.py` (the RUNNER) so the expectations live in one
place and the runner stays small enough to read.

THE EXPECTATION IS DERIVED, NOT ASSERTED
-----------------------------------------
Every check that puts something on a panel is graded against a frame the
DAEMON produced — the frame it painted, or the frame it says it renders —
never against a sentence this repo wrote about what the panel looks like.
That sentence is how the packet graded a working `weather` widget FAIL
(the daemon draws one combined frame now; the packet still said the device
"cycles"), and how it graded a working command FAIL twice before that.

So: `look` is the shared instruction from `hw_expect.PANEL_LOOK`, and the
picture itself arrives at run time. A check that cannot show a frame (a
socket-level command) says what its answer looks like in words, because
there is no picture to show.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import hw_expect as expect
import hw_mcp_lease

# Re-exported so the runner and the gates can import everything from one place.
from hw_expect import Expectation, PANEL_LOOK  # noqa: F401


@dataclass
class Check:
    id: str
    title: str
    look: str = PANEL_LOOK
    needs_device: bool = True
    expect_fail: str = ""         # why this check is EXPECTED to fail
    tags: list[str] = field(default_factory=list)
    setup: str = ""               # what the operator must DO first (never what it looks like)

    def drive(self, client, ctx: dict) -> tuple[bool, str]:
        """`ctx` carries what only the live daemon knows: `mac`, `size`, `image`."""
        raise NotImplementedError

    def expectation(self, client, ctx: dict) -> Expectation:
        """What the operator will be shown, and what the machine concluded."""
        return Expectation()


@dataclass
class CallCheck(Check):
    """Fire one device_call, then ask what appeared on the panel."""
    method: str = ""
    args: list = field(default_factory=list)
    settle: float = 1.5

    def drive(self, client, ctx):
        args = [ctx[a[1:]] if isinstance(a, str) and a.startswith("$") else a
                for a in self.args]
        # The mac matters: a mac-less call goes to whichever panel connected
        # LAST, and with a fleet of four that is not the one the operator is
        # watching (the packet reads THAT panel's activity record).
        reply = client.device_call(self.method, args, mac=ctx.get("mac"))
        time.sleep(self.settle)
        if not isinstance(reply, dict):
            return False, f"non-dict reply: {reply!r}"
        if reply.get("success") is False:
            return False, str(reply.get("error") or reply)
        return True, json.dumps(reply)[:200]


@dataclass
class CommandCheck(Check):
    """Fire one socket command (not a device call)."""
    command: str = ""
    cargs: dict = field(default_factory=dict)
    needs_device: bool = False

    def drive(self, client, ctx):
        cargs = {k: (ctx[v[1:]] if isinstance(v, str) and v.startswith("$") else v)
                 for k, v in self.cargs.items()}
        reply = client.send_command(self.command, cargs)
        if not isinstance(reply, dict):
            return False, f"non-dict reply: {reply!r}"
        if reply.get("success") is False:
            return False, str(reply.get("error") or reply)
        return True, json.dumps(reply)[:200]


@dataclass
class LiveJobCheck(Check):
    """Start one live widget job and watch the panel.

    The four widget checks are `live_job_start`, NOT `device_call`. That is
    the whole reason this packet failed five for five on 2026-09-07: it named
    `live_jobs.start` / `media.push_album_art` / `display.show_weather`, none of
    which the daemon has ever answered, and the R12 visual pass sat in the
    roadmap as "needs a device" when it would have failed identically with no
    device attached. The names now come from the daemon's own match arms and are
    held there by `tools/check_hw_verify_methods.py`.
    """
    kind: str = ""
    params: dict = field(default_factory=dict)
    settle: float = 8.0
    motion_window: float = 0.0     # seconds to wait and re-read the frame
    needs_now_playing: bool = False

    def drive(self, client, ctx):
        # Clear whatever the previous check left running: the jobs share one
        # panel, so a music job still pushing album art would sit on top of the
        # weather face and the operator would grade the wrong widget.
        client.send_command("live_jobs_stop_for", {"mac": ctx["mac"]})
        params = dict(self.params)
        params.setdefault("size", ctx["size"])
        reply = client.send_command(
            "live_job_start",
            {"mac": ctx["mac"], "kind": self.kind, "params": params})
        if not isinstance(reply, dict):
            return False, f"non-dict reply: {reply!r}"
        if reply.get("success") is False:
            return False, str(reply.get("error") or reply)
        time.sleep(self.settle)
        return True, json.dumps(reply)[:200]

    def expectation(self, client, ctx):
        if self.needs_now_playing:
            playing = expect.reply_of(client, "now_playing")
            if not playing.get("playing"):
                return Expectation(
                    verdict="SKIP",
                    detail="nothing is playing — the music job has nothing to "
                           "push, so there is no cover to grade. Start some "
                           "music and run this check again.")
        png, record = expect.painted_png(
            client, ctx["mac"], kind=self.kind, wait=expect.FRAME_WAIT)
        if png is None:
            return Expectation(
                verdict="FAIL",
                detail=f"the daemon painted no {self.kind} frame within "
                       f"{expect.FRAME_WAIT:.0f}s (its activity record says "
                       f"kind={record.get('kind') or 'nothing'})")
        path = expect.save_png(png, ctx["frames_dir"], f"{self.id}.png")
        text = expect.describe(png, path)
        if self.motion_window:
            time.sleep(self.motion_window)
            later, _ = expect.painted_png(client, ctx["mac"], kind=self.kind)
            if later:
                changed, total = expect.diff_png(png, later)
                text += (f"\n{self.motion_window:.0f}s later the daemon's own "
                         f"frame differs in {changed} of {total} pixels")
        return Expectation(text=text)


@dataclass
class ImageCheck(Check):
    """Push a local file to the panel and compare it with the daemon's own
    rendering of that file.

    The expectation is `render_widget album_art` on the same bytes: the
    daemon's `display.show_image` and its `render_widget album_art` run the
    SAME downscaler (`process_image_bytes`), so the picture this packet shows
    is the picture the panel was sent — not a guess at it.
    """
    method: str = ""
    path_arg: str = ""              # the ctx key holding the file path
    settle: float = 3.0
    render_kind: str = "album_art"

    def drive(self, client, ctx):
        path = ctx[self.path_arg[1:]] if self.path_arg.startswith("$") else self.path_arg
        reply = client.device_call(self.method, [path], mac=ctx.get("mac"))
        time.sleep(self.settle)
        if not isinstance(reply, dict):
            return False, f"non-dict reply: {reply!r}"
        if reply.get("success") is False:
            return False, str(reply.get("error") or reply)
        return True, json.dumps(reply)[:200]

    def expectation(self, client, ctx):
        path = ctx[self.path_arg[1:]]
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            return Expectation(verdict="FAIL", detail=f"cannot read {path}: {exc}")
        reference = expect.rendered_png(
            client, self.render_kind, size=ctx["size"],
            params={"image_b64": base64.b64encode(raw).decode()})
        if reference is None:
            return Expectation(
                verdict="FAIL",
                detail=f"the daemon would not render {path} at "
                       f"{ctx['size']}x{ctx['size']} — there is nothing to "
                       f"compare the panel against")
        saved = expect.save_png(reference, ctx["frames_dir"], f"{self.id}.png")
        text = expect.describe(reference, saved)
        text += ("\n(this is the daemon's OWN rendering of that file at panel "
                 "size — the same downscaler `display.show_image` uses)")
        return Expectation(text=text)


# Phase 4's exit, built on this file's `Check` (its module keeps this one
# under the size cap).
McpLeaseCheck = hw_mcp_lease.bind(Check)


def build_checks() -> list[Check]:
    """The packet. Each entry names what a person must SEE, not what returned 0."""
    return [
        LiveJobCheck(
            id="sysmon", tags=["P2.2"],
            title="System-monitor gauges on a matrix",
            setup="watch the panel for ~15s: the gauges are redrawn every few "
                  "seconds, so the picture must change under you",
            kind="sysmon", settle=12.0, motion_window=10.0,
        ),
        LiveJobCheck(
            id="album_art", tags=["P2.3", "R12"],
            title="Album cover on the device",
            setup="PLAY SOMETHING FIRST — with no track this job has nothing "
                  "to push, and the packet records that as SKIP, not FAIL",
            kind="music", settle=10.0, needs_now_playing=True,
        ),
        LiveJobCheck(
            id="weather", tags=["P2.3", "R12"],
            title="Weather widget on the device",
            setup="the frame is what the daemon just painted; compare the "
                  "panel with it",
            kind="weather", settle=12.0,
        ),
        ImageCheck(
            id="custom_art", tags=["P2.3", "R12"],
            title="Custom art (local image) on the device",
            setup="the daemon downsizes the file to the panel; the frame "
                  "below is that same downsize",
            method="display.show_image", path_arg="$image",
        ),
        McpLeaseCheck(
            id="mcp_lease",
            title="An MCP agent borrows a 64x64 panel and gives it back (P4 exit)",
            setup="watch the panel from the moment this check starts: an agent "
                  "takes it for about 8 s, then lets the lease lapse",
        ),
        CommandCheck(
            id="weather_city", tags=["P2.6"],
            title="search_weather_city on the CONFIGURED account",
            look="EXPECTED TO FAIL with `RC=1 Failed` — R73 disproved the "
                 "success path on the real, logged-in account, isolated by "
                 "elimination (GetCategoryFileListV2 and Channel/GetDialType "
                 "succeeded on the same daemon, credentials and minute). This "
                 "check is now a CANARY: a non-empty list means the server "
                 "changed and the feature can be revived. Anything else — a "
                 "guest-login RC=10, a transport error — means the harness "
                 "moved, not the endpoint",
            command="search_weather_city", cargs={"keyword": "London"},
            expect_fail="R73 disproved the success path on the real account "
                        "(RC=1). A FAILURE here is the known state and no news; "
                        "a SUCCESS means the server changed.",
        ),
    ]
