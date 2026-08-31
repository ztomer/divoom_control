#!/usr/bin/env python3
"""check_gui_api_reachable.py — the R70 P5.0 gate.

**Every public `DivoomGuiAPI` method should have a caller in `web_ui/`.**

pywebview exposes the API by NAME, so a method with no JS reference is a
feature with no way to reach it. Nothing said so, and the cost was not
theoretical: `push_weather` had four passing tests and no caller, and
`toggle_audio_visualizer` drove a 150-line pyaudio worker — with 100% test
coverage — that nothing could start. A green suite was the REASON they survived
(R70 hole D). Coverage cannot see this; only reachability can.

**Why `control_server.py` does not count as a caller.** It dispatches by name
out of an HTTP request, so it can reach every method on the class — which would
make this check vacuous if it counted. It is also a test surface, gated behind
`DIVOOM_CONTROL_SERVER`, not a path a user has. Being reachable only from it is
exactly the state this gate exists to surface.

**The allowlist is a list of DECISIONS, not a mute button.** Each entry carries
a reason, and `unreviewed` is a legitimate one: the first run of this check
found 24 methods with no JS caller, and only four of them had been examined.
Claiming the other twenty were dead would have been a guess dressed as a
finding. They are recorded as what they are — flagged, not yet reviewed — so
the list can only shrink and nobody re-discovers them from scratch.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _tui import err, info, ok, warn  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WEB_UI = REPO / "divoom_gui" / "web_ui"

# name -> why it has no web_ui caller. Every entry is a decision someone made.
#
#   r70-delete   confirmed dead by the R70 audit; the phase named removes it
#   unreviewed   flagged by this gate's first run, not yet examined
#
# An entry that stops matching FAILS, so a deleted method takes its exemption
# with it and a newly-wired method stops being excused.
ALLOWLIST: dict[str, str] = {
    # The four the R70 audit confirmed dead were DELETED in P5.1-P5.4, so their
    # entries are gone with them — this gate fails on a stale entry, which is
    # what forces that.
    # ── flagged by P5.0, not yet reviewed ───────────────────────────────────
    # These are NOT claims of deadness. Each needs someone to decide whether the
    # UI lost its wiring, the method is a leftover, or it is reached some way
    # this gate cannot see.
    "apply_system_stats": "unreviewed — sysmon one-shot push; the panel may use live_job_start",
    "batch_sync_artwork": "unreviewed — called from Python (gallery_sync)",
    "custom_art_query_page": "unreviewed — daemon round-trip, possibly UI-less",
    "display_custom_art": "unreviewed",
    "export_settings_to_path": "unreviewed — settings import/export pair",
    "import_settings_from_path": "unreviewed — settings import/export pair",
    "get_scoreboard_state": "unreviewed — scoreboard tool",
    "get_transport_status": "unreviewed — diagnostics",
    "hot_update_status": "unreviewed — hot-channel progress; JS polls hot_update_progress",
    "is_mcp_server_running": "unreviewed — MCP card may use mcp_status instead",
    "is_notification_listener_running": "unreviewed — notification card status",
    "live_job_stop": "unreviewed — JS may stop jobs via another entry point",
    "load_cached_gallery": "unreviewed — called from Python (fetch_gallery)",
    "load_preset_file": "unreviewed — preset file pair",
    "save_preset_file": "unreviewed — preset file pair",
    "probe_lan": "unreviewed — LAN discovery",
    "save_lan_config": "unreviewed — LAN device config",
    "set_clock_rich": "unreviewed — richer clock variant",
    "set_temperature_channel": "unreviewed — channel switch",
    "set_timeplan": "unreviewed — time-plan tool",
}


def api_methods() -> set[str]:
    """The REAL class's public surface.

    Imported rather than AST-scanned on purpose: `DivoomGuiAPI` is assembled
    from a dozen mixins, and an approximation of that MRO could disagree with
    what actually exists at runtime — which is the only thing this gate cares
    about.

    The cost is a dependency, and it must announce itself. Run where pywebview
    is absent this used to raise a bare `ModuleNotFoundError: No module named
    'webview'` traceback, which reads as a broken gate rather than a
    misplaced one. (`tools/_tui.py` exists because four R67 gates did exactly
    that in CI.)
    """
    try:
        from divoom_gui.gui_api import DivoomGuiAPI
    except ImportError as exc:
        raise SystemExit(
            f"[api-reachable] cannot import DivoomGuiAPI ({exc}).\n"
            f"  This gate needs the GUI's dependencies — run it from the job\n"
            f"  that installs requirements.txt, not the dependency-free one."
        ) from exc

    return {
        name
        for name in dir(DivoomGuiAPI)
        if not name.startswith("_") and callable(getattr(DivoomGuiAPI, name, None))
    }


def web_ui_blob() -> str:
    parts = []
    for ext in ("*.js", "*.html"):
        for path in sorted(WEB_UI.rglob(ext)):
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def main() -> int:
    if not WEB_UI.is_dir():
        err(f"[api-reachable] {WEB_UI} does not exist")
        return 1

    methods = api_methods()
    blob = web_ui_blob()
    unreached = {m for m in methods if not re.search(rf"\b{re.escape(m)}\b", blob)}

    # A method that gained a caller must lose its exemption, or the list rots
    # into a place where names go to be forgotten.
    stale = sorted(set(ALLOWLIST) - unreached)
    if stale:
        err(f"[api-reachable] {len(stale)} stale allowlist entr(ies)")
        for name in stale:
            info(f"{name} now HAS a web_ui caller (or no longer exists) — "
                 f"delete it from ALLOWLIST")
        return 1

    offenders = sorted(unreached - set(ALLOWLIST))
    if offenders:
        err(f"[api-reachable] {len(offenders)} API method(s) nothing can call")
        for name in offenders:
            info(f"DivoomGuiAPI.{name} has no reference in divoom_gui/web_ui/")
        info("Wire it up, delete it, or add it to ALLOWLIST with a reason.")
        return 1

    unreviewed = sum(1 for r in ALLOWLIST.values() if r.startswith("unreviewed"))
    ok(f"[api-reachable] OK — {len(methods)} API methods, "
       f"{len(unreached)} allowlisted")
    if unreviewed:
        warn(f"  {unreviewed} are 'unreviewed': flagged by P5.0 and awaiting a "
             f"decision, not confirmed dead")
    return 0


if __name__ == "__main__":
    sys.exit(main())
