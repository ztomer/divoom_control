"""The Full Disk Access prompt is decided by the daemon's code (P3.2).

`settings_notifications.js` used to decide "this is a permission problem" by
searching the error text for `PermissionError`, `sqlite3.OperationalError` or
`Full Disk Access` -- the retired Python daemon's wording. The Rust daemon says
"Database open failed: ..." and "Database read failed (FDA permission?): ...",
so the prompt could never fire. It now branches on `error_code`, which the
daemon sets and the GUI API passes through. Driven under node.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
JS = REPO / "divoom_gui" / "web_ui" / "settings_notifications.js"

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const window = {};
const document = { addEventListener: () => {} };
const [jsPath, casesJson] = process.argv.slice(-2);
vm.runInNewContext(fs.readFileSync(jsPath, "utf8"), { window, document, console });
process.stdout.write(JSON.stringify(JSON.parse(casesJson).map(window.macNotifNeedsPermission)));
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _decide(cases):
    r = subprocess.run(
        ["node", "-e", _HARNESS, "--", str(JS), json.dumps(cases)],
        capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL,
    )
    return json.loads(r.stdout)


@needs_node
def test_the_prompt_follows_the_code_not_the_wording():
    assert _decide([
        # What the Rust daemon actually reports when it lacks Full Disk Access.
        {"error": "Database open failed: unable to open database file",
         "error_code": "notification_db_unreadable"},
        # The old trigger words, with no code: no longer a permission problem.
        {"error": "PermissionError: Full Disk Access"},
        {"error": "macOS Notification Center DB not found",
         "error_code": "notification_db_missing"},
        {"running": True},
        None,
    ]) == [True, False, False, False, False]


def test_the_gui_api_passes_the_code_through(monkeypatch):
    import sys
    import types
    sys.path.insert(0, str(REPO))
    from divoom_gui import gui_api

    class Client:
        def start_notifications(self):
            return {"success": True, "state": "idle",
                    "error": "Database open failed: x",
                    "error_code": "notification_db_unreadable"}

        def notification_status(self):
            return self.start_notifications()

    api = gui_api.DivoomGuiAPI.__new__(gui_api.DivoomGuiAPI)
    monkeypatch.setattr(api, "_client", lambda: Client(), raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    fake = types.SimpleNamespace(
        ROUTING_PATH=Path("/tmp/r.json"), load_routing_table=lambda: [],
        find_notification_db_path=lambda: None)
    monkeypatch.setitem(sys.modules, "divoom_client.macos_notifications", fake)
    assert api.start_notification_listener()["error_code"] == "notification_db_unreadable"
    assert api.get_notification_listener_status()["error_code"] == "notification_db_unreadable"
