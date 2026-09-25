"""divoom-control CLI command handlers (split from cli.py, REVIEW §1).

The argument parser + dispatcher live in cli.py; this module holds the per-command
coroutines and their helpers. Imported back into cli.py to build COMMANDS.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from divoom_lib.models.capabilities import DEVICE_CAPABILITIES, DeviceRegistry


def _print(data: Any, *, as_json: bool = False) -> None:
    if as_json:
        if isinstance(data, (list, dict)):
            print(json.dumps(data, indent=2, default=str))
        else:
            print(json.dumps({"result": str(data)}, indent=2))
    else:
        if isinstance(data, list):
            for item in data:
                print(item)
        elif isinstance(data, dict):
            for k, v in data.items():
                print(f"{k}: {v}")
        else:
            print(data)


def _err(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _socket_path(args: argparse.Namespace | None = None) -> str:
    """Which daemon this invocation talks to.

    `--socket` reaches every verb through the shared parser. It was on
    `mcp-server` and `daemon` only, which meant every DEVICE verb was pinned to
    the default path: a dev daemon on its own socket could not be reached, and a
    test could not point at a scratch daemon without aiming at the user's own.
    """
    from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH

    return (getattr(args, "socket", None) or DEFAULT_SOCKET_PATH) if args else DEFAULT_SOCKET_PATH


def _daemon_client(args: argparse.Namespace | None = None):
    """The running daemon, or a clear refusal.

    The CLI is a DAEMON CLIENT (2026-09-12, user correction): the daemon is the
    sole owner of device I/O, and the CLI used to be a second implementation
    over bleak. It does not spawn a daemon either -- a shell-spawned one has no
    Bluetooth grant and dies on its first scan with SIGABRT and no message --
    so with nothing running it says what to start.
    """
    from divoom_client.daemon_client import ensure_daemon
    client = ensure_daemon(_socket_path(args), spawn=False)
    if client is None:
        _err("no divoomd daemon is running. Start the Divoom app (it owns the "
             "Bluetooth grant) or the dev daemon bundle "
             "(scripts/make_dev_daemon_app.sh), then retry.", 3)
    return client


def _scan(client, timeout) -> list:
    """The daemon's scan results, or a refusal that SAYS why.

    Found live (2026-09-12): the GUI scans on its own schedule, and a CLI scan
    that collides with it gets `{"success": false, "error": "scan already in
    progress"}`. Reading only `devices` turned that into "(no Divoom devices
    found)", a false answer. Every scan reader goes through here.
    """
    reply = client.scan(timeout=timeout) or {}
    if not reply.get("success", True):
        _err(f"scan failed: {reply.get('error') or reply}", 1)
    return reply.get("devices") or []


# ── Commands ──────────────────────────────────────────────────────────


async def cmd_scan(args: argparse.Namespace) -> int:
    client = _daemon_client()
    results = _scan(client, args.timeout)
    if args.json:
        _print(results, as_json=True)
    else:
        if not results:
            print("(no Divoom devices found)")
        for r in results:
            print(f"{r['address']}  {r['name']}")
    return 0


async def cmd_select(args: argparse.Namespace) -> int:
    """Make a panel the ACTIVE one: the daemon owns the selection, so the
    bench highlights it, the menubar marks it, and mac-less commands go to
    it while it is linked."""
    if not args.mac:
        _err("--mac is required for `select`", 2)
    client = _daemon_client()
    reply = client.select_device(args.mac) or {}
    if not reply.get("success"):
        _err(f"select failed: {reply.get('error') or reply}", 1)
    if args.json:
        _print(reply, as_json=True)
    else:
        print(f"active panel: {args.mac}")
    return 0


async def cmd_pair(args: argparse.Namespace) -> int:
    """Save MAC → device_type to the per-install registry."""
    if not args.mac:
        _err("--mac is required for `pair`", 2)
    if not args.device_type:
        _err("--type is required for `pair`", 2)
    if args.device_type not in DEVICE_CAPABILITIES:
        _err(f"unknown device_type {args.device_type!r}; "
             f"valid: {sorted(DEVICE_CAPABILITIES.keys())}", 2)
    reg = DeviceRegistry()
    reg.register(args.mac, args.device_type)
    if args.json:
        _print({"registered": args.mac, "device_type": args.device_type}, as_json=True)
    else:
        print(f"registered {args.mac} → {args.device_type}")
        print(f"registry file: {reg.path}")
    return 0


async def cmd_identify(args: argparse.Namespace) -> int:
    """Print the raw BLE manufacturer_data for nearby devices. Used to
    populate the ADVERTISED_FINGERPRINTS table as the user identifies new
    devices. Read through the daemon's scan (it carries the advertisement's
    manufacturer data and service UUIDs); the radio has one owner."""
    client = _daemon_client()
    print(f"Scanning for {args.timeout}s...", file=sys.stderr)
    results = _scan(client, args.timeout)
    found = {r["address"]: r for r in results if r.get("manufacturer_data")}
    if not found:
        _err("no devices with manufacturer_data found", 1)

    if args.json:
        out = {
            addr: {"name": r.get("name"), "manufacturer_data": {
                hex(int(k)): v for k, v in r["manufacturer_data"].items()},
                "service_uuids": list(r.get("service_uuids") or [])}
            for addr, r in found.items()
        }
        _print(out, as_json=True)
    else:
        for addr, r in found.items():
            print(f"\n{addr}  {r.get('name')}")
            for company_id, payload in r["manufacturer_data"].items():
                print(f"  manufacturer_data: company_id=0x{int(company_id):04x} bytes={payload}")
            for u in r.get("service_uuids") or []:
                print(f"  service_uuid: {u}")
        print("\nAdd a fingerprint to ADVERTISED_FINGERPRINTS in "
              "divoom_lib/models/capabilities.py as (company_id, prefix_bytes) -> device_type.")
    return 0


def _divoomd_binary() -> str:
    """The ``divoomd`` binary that now provides the server and the device verbs.

    Split out of :func:`cmd_mcp_server` so the "not built" branch is testable.
    It is the one failure the handoffs introduce — before them, these commands
    needed no Rust binary at all — and a branch that can only be reached on a
    machine without a toolchain is exactly the branch that ships untested and
    mis-worded. Named for the binary rather than for its first caller, because
    it now has two.
    """
    from divoom_client import binary_resolver

    exe = binary_resolver.resolve("divoomd")
    if exe is not None:
        return str(exe)
    stale = binary_resolver.stale_report("divoomd")
    detail = f" ({'; '.join(f'{p} reports {v}' for p, v in stale)})" if stale else ""
    _err(
        f"could not find the divoomd binary that provides the MCP server{detail}. "
        f"{binary_resolver.rebuild_hint('divoomd')}"
    )
    raise AssertionError("_err exits; this line is unreachable")


async def cmd_mcp_server(args: argparse.Namespace) -> int:
    """Hand off to the native MCP server: ``divoomd mcp``.

    The server is Rust now (2026-09-25, phase L5). This command is still the
    documented entry point — it is what an MCP client's config names — so it has
    to keep working, but it no longer *implements* a server. The GUI has spawned
    ``divoomd mcp`` directly since R70 P4.2 (``divoom_gui/mcp_control.py``); this
    is the same handoff for the config-file path, and it is what lets
    ``mcp_server.py``/``mcp_tools.py`` go: the Python catalog (13 tools) was a
    strict SUBSET of the native one (14, adding ``list_screens``), so nothing
    reachable is lost.

    Two steps, and both are load-bearing:

    1. The daemon is ensured first. ``divoomd mcp`` connects to a daemon; it
       does not start one, so dropping this step would turn "works on a fresh
       machine" into "fails unless the GUI happens to be running".
    2. The process image is REPLACED (``os.execv``), not spawned-and-waited. An
       MCP stdio server is a pipe: the client owns our stdin and stdout, and
       anything interposed between the client and the server is a place for the
       protocol to be mangled, a signal to be swallowed, or the exit code to be
       laundered. exec hands all three to the real server directly.

    The flags reach the daemon target through the environment, and the variable
    names are identical on both sides (``DIVOOM_DAEMON_HOST``/``_PORT``/
    ``_TOKEN``, ``DIVOOM_SOCKET``) precisely so this needs no translation layer.
    A second mapping would be a second thing to keep in sync with the first.
    """
    import os
    from divoom_client.daemon_protocol import ENV_HOST, ENV_PORT, ENV_SOCKET, ENV_TOKEN
    from divoom_client.daemon_client import ensure_daemon

    # A remote daemon is selected purely via env (DaemonClient.from_env /
    # ensure_daemon read these); mirror the CLI flags into the environment so a
    # single code path handles local + remote.
    host = getattr(args, "host", None)
    if host:
        os.environ[ENV_HOST] = host
        os.environ[ENV_PORT] = str(getattr(args, "port", 9009))
        token = getattr(args, "token", None) or os.environ.get(ENV_TOKEN)
        if token:
            os.environ[ENV_TOKEN] = token

    socket_path = getattr(args, "socket", None) or "/tmp/divoom.sock"
    client = ensure_daemon(socket_path, mac=getattr(args, "mac", None))
    if client is None:
        _err("could not reach or start the divoom daemon", 1)

    # The native server reads the same variable for the local case, so an
    # explicit --socket has to be in the environment too — otherwise the handoff
    # silently connects to /tmp/divoom.sock and reports the daemon as down.
    os.environ[ENV_SOCKET] = socket_path

    exe = _divoomd_binary()
    where = f"{host}:{getattr(args, 'port', 9009)}" if host else socket_path
    sys.stderr.write(f"MCP server: handing off to {exe} (daemon={where})\n")
    sys.stderr.flush()

    # Replaces this process; there is no return. On success the native server
    # owns stdin/stdout/exit status until the client closes the pipe.
    os.execv(str(exe), [str(exe), "mcp"])
    # Only reachable if exec failed. execv raises OSError on a real failure
    # (missing file, not executable), so reaching here means it returned, which
    # it does not do — but a command that must not silently do nothing says so.
    _err(f"could not execute {exe}", 1)


async def cmd_daemon(args: argparse.Namespace) -> int:
    """The Python daemon server was archived 2026-07-13 (explicit user
    sign-off) in favor of the Rust `divoomd` binary — see `docs/ROADMAP.md`'s
    "Native Rust daemon" section. This subcommand is kept only to give a
    clear, actionable error instead of a raw ImportError; the historical
    implementation still exists (moved, not deleted) at
    git history if it's ever needed for reference (recover from git history (archived in 046cdf8, removed in R66 2026-08-17))."""
    print(
        "The Python daemon server has been archived — divoomd (Rust) is now "
        "the only supported daemon. Build/run divoomd directly, or use "
        "divoom_client.daemon_client.ensure_daemon()/spawn_daemon() which "
        "auto-spawns it. The archived Python implementation is kept for "
        "recoverable from git history but is no longer runnable via "
        "this CLI command.",
        file=sys.stderr,
    )
    return 1


def cmd_menubar(args: argparse.Namespace) -> int:
    """The pyobjc menubar was removed 2026-08-17 (R66) in favour of the native
    Rust agent, `divoom-menubar/`, which is what the shipped .app
    has bundled since the native cutover. This subcommand is kept only to give
    a clear, actionable error instead of a raw ImportError -- same treatment
    `cmd_daemon` got when the Python daemon server was archived."""
    print(
        "The Python menubar has been removed — the native Rust agent "
        "(divoom-menubar) is now the only menubar. Run it with "
        "`./run.sh --menubar`, or let the GUI spawn it (`./run.sh`). Build it "
        "with `./build.sh`. Its resubscribe guard lives in "
        "divoom-menubar/src/resubscribe.rs.",
        file=sys.stderr,
    )
    return 1


