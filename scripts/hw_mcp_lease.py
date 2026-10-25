#!/usr/bin/env python3
"""Phase 4's exit on real glass: an MCP agent borrows a 64x64 panel and gives it back.

`divoomd/tests/mcp_lease_e2e.rs` is the exit against a mock 64x64 panel: the
real `divoomd mcp` entry point, a real daemon, a live widget, a lease, a
full-resolution multi-frame draw read back off the mock's wire, and the widget
painted back when the lease lapses. What no test can do is look at a panel.
This check runs THAT scenario, through the same entry point, against the panel
the operator is watching, and then asks what they saw.

    scripts/hw_verify.py --only mcp_lease

Driven over MCP exactly as a client's config launches it (`divoomd mcp`, with
`DIVOOM_SOCKET` naming the daemon this packet talks to), so the path under
test is the agent's path, not the socket's.

**What it refuses to grade.** The exit is about a 64x64 panel, so a panel the
daemon does not describe as 64x64 is a SKIP that says so -- never a PASS on a
16x16 panel. A panel linked over Wi-Fi is a SKIP too, with its reason: the
daemon has no image command on its LAN transport (ROADMAP P6.2), so neither
the agent's draw nor the live widget can reach it, and a FAIL there would
blame the panel for a gap in the daemon.

**What the machine decides before anyone looks.** The lease is granted; the
draw is answered at 64 with every frame; a caller WITHOUT the lease is refused
and told who holds it; after the TTL the lapsed lease cannot be renewed. Any
of those wrong is a FAIL with the reply quoted. Only then is a person asked.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import time
from dataclasses import dataclass, field

import hw_expect as expect
from hw_expect import Expectation

# The exit's own panel size. Not a parameter: a check that accepted 16 here
# would be a different check wearing this one's name.
EXIT_SIZE = 64

# The agent's animation: four solid frames, long enough each to see.
AGENT_FRAMES = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
FRAME_MS = 500

# Every name this check sends, so `tools/check_hw_verify_methods.py` can hold
# them to the daemon's MCP catalog and socket command table.
MCP_TOOLS = ("get_capabilities", "lease_acquire", "push_animation",
             "show_text", "lease_renew")
SOCKET_COMMANDS = ("device_status", "live_jobs_stop_for", "live_job_start")


def agent_gif(size: int = EXIT_SIZE) -> bytes:
    """The agent's multi-frame GIF, at the panel's full resolution."""
    from PIL import Image  # pillow is a runtime dependency (requirements.txt)

    frames = [Image.new("RGB", (size, size), rgb) for rgb in AGENT_FRAMES]
    out = io.BytesIO()
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, loop=0)
    return out.getvalue()


class McpSession:
    """`divoomd mcp` over stdio, one JSON-RPC line each way, as a client runs it."""

    def __init__(self, binary: str, socket_path: str, timeout: float = 15.0):
        env = {**os.environ, "DIVOOM_SOCKET": socket_path}
        env.pop("DIVOOM_DAEMON_HOST", None)
        self._timeout = timeout
        self._id = 0
        self._proc = subprocess.Popen(
            [binary, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, text=True)
        self._rpc("initialize", {"protocolVersion": "2025-06-18",
                                 "capabilities": {},
                                 "clientInfo": {"name": "hw_verify",
                                                "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params})
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError(f"`divoomd mcp` closed its output during {method}")
        return json.loads(line)

    def call(self, name: str, arguments: dict) -> tuple[bool, dict]:
        """`(is_error, the tool's JSON)` for one `tools/call`."""
        reply = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if "error" in reply:
            return True, {"error": reply["error"]}
        result = reply.get("result") or {}
        text = ((result.get("content") or [{}])[0]).get("text") or "{}"
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = {"text": text}
        return bool(result.get("isError")), value

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)


def resolve_divoomd(override: str = "") -> str:
    """The `divoomd` the GUI would run, by the same resolver."""
    from divoom_client import binary_resolver

    found = binary_resolver.resolve(
        "divoomd", override=override or os.environ.get("DIVOOM_RUST_BINARY"))
    if not found:
        raise RuntimeError("no divoomd binary found (build it, or pass --divoomd)")
    return str(found)


def precondition(status: dict) -> str:
    """Why this panel cannot run the exit, or "" when it can."""
    if status.get("lan_ip"):
        return ("the panel is linked over Wi-Fi, and the daemon has no image "
                "command on its LAN transport (ROADMAP P6.2): neither the "
                "agent's draw nor the live widget can reach it. Link a 64x64 "
                "panel over Bluetooth, or land P6.2 first")
    w, h = status.get("width"), status.get("height")
    if (w, h) != (EXIT_SIZE, EXIT_SIZE):
        said = f"{w}x{h}" if w and h else "of unknown size (no model name)"
        return (f"the exit is a {EXIT_SIZE}x{EXIT_SIZE} panel and the daemon "
                f"describes this one as {said}; select a 64x64 panel (the "
                f"packet drives the selected one) and run it again")
    return ""


def run_scenario(client, ctx: dict, session, ttl_ms: int,
                 sleep=time.sleep) -> tuple[list[str], dict]:
    """Drive the exit. Returns `(faults, evidence)`; no faults is a clean run."""
    mac = ctx["mac"]
    faults: list[str] = []
    evidence: dict = {}

    client.send_command("live_jobs_stop_for", {"mac": mac})
    job = client.send_command(
        "live_job_start",
        {"mac": mac, "kind": "sysmon", "params": {"size": EXIT_SIZE}})
    if not isinstance(job, dict) or job.get("success") is False:
        return [f"the live widget did not start: {job}"], evidence
    sleep(ctx.get("job_settle", 6.0))

    bad, cap = session.call("get_capabilities", {"mac": mac})
    if bad or (cap.get("width"), cap.get("height")) != (EXIT_SIZE, EXIT_SIZE):
        return [f"get_capabilities over MCP does not say 64x64: {cap}"], evidence

    bad, lease = session.call(
        "lease_acquire", {"mac": mac, "ttl_ms": ttl_ms, "holder": "hw_verify agent"})
    token = lease.get("lease") if not bad else None
    if not token:
        return [f"lease_acquire was not granted: {lease}"], evidence

    data = base64.b64encode(agent_gif()).decode()
    bad, drawn = session.call(
        "push_animation", {"mac": mac, "data": data, "lease": token})
    evidence["drawn"] = drawn
    if bad or drawn.get("size") != EXIT_SIZE or drawn.get("frames") != len(AGENT_FRAMES):
        faults.append(f"the agent's draw was not {EXIT_SIZE} px with "
                      f"{len(AGENT_FRAMES)} frames: {drawn}")

    bad, refused = session.call(
        "show_text", {"mac": mac, "text": "No", "size": 16})
    evidence["refused"] = refused
    if not bad or "hw_verify agent" not in str(refused.get("error", "")):
        faults.append(f"a caller without the lease was not refused by name: {refused}")

    # The agent goes quiet, as a crashed one would. Past the TTL the lease
    # must be gone, and the widget back.
    sleep(ttl_ms / 1000 + ctx.get("lapse_margin", 2.0))
    bad, renewed = session.call("lease_renew", {"lease": token, "ttl_ms": ttl_ms})
    evidence["renewed"] = renewed
    if not bad:
        faults.append(f"the lapsed lease could still be renewed: {renewed}")
    return faults, evidence


def bind(check_base):
    """Build the packet's check class on the packet's own `Check` base.

    Defined here (not in `hw_packet`) to keep that file under its size cap;
    bound there so the runner, the gates and the tests see one `Check` type.
    """

    @dataclass
    class McpLease(check_base):
        """Phase 4's exit, on the panel the operator is watching."""
        ttl_ms: int = 8000
        divoomd: str = ""
        session_factory: object = None   # a seam: tests inject a fake session
        tags: list[str] = field(default_factory=lambda: ["P4"])

        def drive(self, client, ctx):
            ctx.pop("mcp_lease", None)
            status = client.send_command("device_status", {"mac": ctx["mac"]})
            status = status if isinstance(status, dict) else {}
            why = precondition(status)
            if why:
                ctx["mcp_lease"] = {"skip": why}
                return True, f"precondition: {why}"
            factory = self.session_factory or (
                lambda: McpSession(resolve_divoomd(ctx.get("divoomd", self.divoomd)),
                                   ctx["socket"]))
            session = factory()
            try:
                faults, evidence = run_scenario(client, ctx, session, self.ttl_ms)
            finally:
                session.close()
            ctx["mcp_lease"] = {"faults": faults, "evidence": evidence}
            return True, json.dumps(evidence.get("drawn", {}))[:200]

        def expectation(self, client, ctx):
            run = ctx.get("mcp_lease") or {}
            if run.get("skip"):
                return Expectation(verdict="SKIP", detail=run["skip"])
            if run.get("faults"):
                return Expectation(verdict="FAIL", detail="; ".join(run["faults"]))
            lines = []
            for i, rgb in enumerate(AGENT_FRAMES):
                png = expect.raw_to_png(bytes(rgb) * (EXIT_SIZE * EXIT_SIZE), EXIT_SIZE)
                path = expect.save_png(png, ctx["frames_dir"], f"{self.id}_agent_{i}.png")
                lines.append(f"the agent's frame {i}: solid RGB{rgb}, "
                             f"{FRAME_MS} ms, saved: {path}")
            lines.append(f"those {len(AGENT_FRAMES)} frames looped for "
                         f"{self.ttl_ms / 1000:.0f} s, then the lease lapsed")
            png, record = expect.painted_png(
                client, ctx["mac"], kind="sysmon", wait=expect.FRAME_WAIT)
            if png is None:
                return Expectation(
                    verdict="FAIL",
                    detail=f"after the lease lapsed the daemon painted no sysmon "
                           f"frame within {expect.FRAME_WAIT:.0f}s (activity "
                           f"kind={record.get('kind') or 'nothing'})")
            path = expect.save_png(png, ctx["frames_dir"], f"{self.id}_widget.png")
            lines.append("and then the widget came back:")
            lines.append(expect.describe(png, path))
            return Expectation(text="\n".join(lines))

    return McpLease
