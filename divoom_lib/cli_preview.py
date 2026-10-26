"""``divoom-control preview``: what each panel is showing (WG.5a).

READ-ONLY. It asks the running daemon for ``screen_previews`` -- the frames
the daemon itself streamed to each panel, recorded where they were sent
(``divoomd/src/screen_previews.rs``) -- and prints them. It sends nothing to
any panel, starts no daemon, and changes no setting.

Every entry carries ``state``; only ``state == "frame"`` carries pixels. Every
other state carries a ``reason`` and ``frame: null``, so a widget can never
draw an absent screen as a blank image that looks like data (house rule #12).
States the daemon reports: ``frame``, ``nothing_sent``, ``device_rendered``,
``undecoded``, ``offline``. States this command adds, for panels the daemon
cannot speak for: ``not_linked`` (registered in the app's settings, but the
daemon holds no link to it), ``unknown`` (``--mac`` named a panel the daemon
has never linked), ``daemon_not_running``, ``daemon_unsupported`` (the
running daemon predates ``screen_previews``) and ``error`` (a running daemon
refused ``screen_previews`` for another reason; ``reason`` carries its error,
and ``daemon.state`` is ``error`` too).

The same answer is the MCP tool ``get_screen_previews`` (``divoomd mcp``,
``divoomd/src/mcp_preview.rs``), with each frame as MCP image content.

Output (``--json``)::

    {"daemon": {"state": "running"|"not_running"|"unsupported"|"error",
                "reason": str|null},
     "now_ms": int|null,
     "devices": [{"id", "name", "connected", "selected", "model", "width",
                  "height", "model_source", "state", "reason", "source",
                  "at_ms", "age_s",
                  "frame": {"data_url", "mime", "width", "height", "frames",
                            "path"?} | null}]}

``--out DIR`` also writes each frame to ``DIR/<id>.png`` (or ``.gif`` for an
animation) and adds its ``path``. The command exits 0 whenever it printed an
answer, absent states included: the JSON is the answer.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

#: The keys every device entry carries, so a consumer can rely on the shape.
ENTRY_KEYS = ("id", "name", "connected", "selected", "model", "width", "height",
              "model_source", "state", "reason", "source", "at_ms", "age_s", "frame")

_EXT = {"image/png": "png", "image/gif": "gif"}


def _absent(device_id: str, state: str, reason: str) -> dict:
    """An entry for a panel the daemon cannot speak for."""
    entry = {k: None for k in ENTRY_KEYS}
    entry.update(id=device_id, state=state, reason=reason, connected=False)
    return entry


def _registered() -> list[str]:
    """The panels the app's settings register (never raises)."""
    try:
        from divoom_lib.settings_devices import registered_devices
        return [addr for addr, _ in registered_devices()]
    except Exception:  # a broken settings file is not a crash here
        return []


def _linked_without_previews(client, why: str) -> list[dict]:
    """The panels an older daemon still describes (two read-only commands it
    has always served), each absent for ``why``: who and how big, no frame."""
    status = client.send_command("device_status", {}) or {}
    owned = client.send_command("owned_devices", {}) or {}
    names = {str(d.get("address", "")).lower(): d.get("name")
             for d in owned.get("devices") or []}
    out = []
    for d in status.get("devices") or []:
        entry = _absent(str(d.get("mac")), "daemon_unsupported", why)
        entry.update({k: d.get(k) for k in ("connected", "selected", "model", "width",
                                             "height", "model_source")})
        entry["name"] = names.get(str(d.get("mac")).lower())
        out.append(entry)
    return out


def collect(client, mac: str | None = None) -> dict:
    """The preview answer, from ``client`` (a ``DaemonClient``)."""
    args = {"mac": mac} if mac else {}
    reply = client.send_command("screen_previews", args) or {}
    known = [mac] if mac else _registered()
    if reply.get("unreachable"):
        why = ("no divoomd daemon is answering; start the Divoom app, which owns "
               "the Bluetooth grant")
        return {"daemon": {"state": "not_running", "reason": why}, "now_ms": None,
                "devices": [_absent(d, "daemon_not_running", why) for d in known]}
    if reply.get("code") == "unknown_command":
        why = ("the running divoomd predates screen_previews; update the Divoom "
               "app to read previews")
        devices = _linked_without_previews(client, why)
        listed = {str(d["id"]).lower() for d in devices}
        devices += [_absent(d, "daemon_unsupported", why) for d in known
                    if d.lower() not in listed]
        return {"daemon": {"state": "unsupported", "reason": why}, "now_ms": None,
                "devices": devices}
    daemon = {"state": "running", "reason": None}
    if reply.get("code") == "unknown_device" and mac:
        why = f"the daemon has never linked {mac}: {reply.get('error')}"
        return {"daemon": daemon, "now_ms": None,
                "devices": [_absent(mac, "unknown", why)]}
    if not reply.get("success"):
        why = f"the daemon refused screen_previews: {reply.get('error') or reply}"
        return {"daemon": {"state": "error", "reason": why}, "now_ms": None,
                "devices": [_absent(d, "error", why) for d in known]}
    devices = list(reply.get("devices") or [])
    listed = {str(d.get("id", "")).lower() for d in devices}
    for addr in known:
        if addr.lower() not in listed:
            devices.append(_absent(
                addr, "not_linked",
                "registered in the app's settings, but the daemon holds no link "
                "to it; what it shows is unknown"))
    return {"daemon": daemon, "now_ms": reply.get("now_ms"), "devices": devices}


def write_frames(answer: dict, out: Path) -> None:
    """Write every frame to ``out/<id>.<ext>`` and record its ``path``."""
    out.mkdir(parents=True, exist_ok=True)
    for d in answer["devices"]:
        frame = d.get("frame")
        if not frame:
            continue
        url = frame.get("data_url") or ""
        _, _, b64 = url.partition(",")
        ext = _EXT.get(frame.get("mime") or "", "bin")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(d.get("id") or "panel"))
        path = out / f"{name}.{ext}"
        path.write_bytes(base64.b64decode(b64))
        frame["path"] = str(path)


def _line(d: dict) -> str:
    size = f"{d['width']}x{d['height']}" if d.get("width") else "?x?"
    label = d.get("name") or d.get("id")
    if d.get("state") == "frame":
        f = d["frame"]
        return (f"{label}  {size}  frame {f['width']}x{f['height']} "
                f"({f['frames']} frame(s), {d['source']}, {d['age_s']:.0f}s ago)")
    return f"{label}  {size}  {d.get('state')}: {d.get('reason')}"


async def cmd_preview(args: argparse.Namespace) -> int:
    from divoom_client.daemon_protocol import DaemonClient
    from divoom_lib.cli_commands import _socket_path

    answer = collect(DaemonClient(_socket_path(args)), args.mac)
    if getattr(args, "out", None):
        write_frames(answer, Path(args.out))
    if args.json:
        print(json.dumps(answer, indent=2))
    else:
        if answer["daemon"]["reason"]:
            print(f"daemon: {answer['daemon']['state']}: {answer['daemon']['reason']}")
        for d in answer["devices"]:
            print(_line(d))
    return 0
