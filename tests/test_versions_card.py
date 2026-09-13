"""Settings > Version (user request 2026-09-13): the dashboard's version and
the daemon's own report, side by side, with a note when they differ."""
import json
import subprocess
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SETTINGS_JS = REPO / "divoom_gui" / "web_ui" / "settings_hardware.js"


class _Client:
    def __init__(self, reply):
        self._reply = reply
    def send_command(self, cmd, args, read_timeout=None):
        assert cmd == "get_status"
        return self._reply


def _host(client, app="0.37.0"):
    from divoom_gui.lifecycle_mixin import LifecycleSettingsMixin
    h = LifecycleSettingsMixin.__new__(LifecycleSettingsMixin)
    h._client = lambda: client
    h._app_version = lambda: app
    return h


def test_get_versions_reports_app_daemon_and_protocol():
    out = json.loads(_host(_Client({"success": True, "daemon_version": "0.37.0", "protocol_version": "1.1"})).get_versions())
    assert out == {"app": "0.37.0", "daemon": "0.37.0", "protocol": "1.1", "daemon_reachable": True}


def test_get_versions_without_a_daemon_says_so():
    out = json.loads(_host(None).get_versions())
    assert out["app"] == "0.37.0" and out["daemon"] is None and out["daemon_reachable"] is False
    class _Boom:
        def send_command(self, *a, **k):
            raise RuntimeError("socket gone")
    out = json.loads(_host(_Boom()).get_versions())
    assert out["daemon_reachable"] is False


_HARNESS = r"""
const fs = require("fs"); const vm = require("vm");
const els = {};
const el = (id) => els[id] || (els[id] = { textContent: "", hidden: false });
const window = { pywebview: null, addEventListener: () => {} };
const document = { getElementById: el, addEventListener: () => {}, querySelectorAll: () => [], querySelector: () => null };
const [jsPath, casesJson] = process.argv.slice(-2);
vm.runInNewContext(fs.readFileSync(jsPath, "utf8"), { window, document, setTimeout, console, localStorage: { getItem: () => null, setItem: () => {} } });
const out = {};
for (const [name, v] of JSON.parse(casesJson)) {
    window.renderVersions(v);
    out[name] = { app: el("version-app").textContent, daemon: el("version-daemon").textContent,
                  proto: el("version-protocol").textContent, noteHidden: el("version-note").hidden, note: el("version-note").textContent };
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_card_renders_a_mismatch_as_a_note_and_a_missing_daemon_honestly():
    cases = [
        ["same", {"app": "0.37.0", "daemon": "0.37.0", "protocol": "1.1", "daemon_reachable": True}],
        ["stale", {"app": "0.38.0", "daemon": "0.37.0", "protocol": "1.1", "daemon_reachable": True}],
        ["down", {"app": "0.37.0", "daemon": None, "protocol": None, "daemon_reachable": False}],
    ]
    r = subprocess.run(["node", "-e", _HARNESS, "--", str(SETTINGS_JS), json.dumps(cases)], capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    assert out["same"] == {"app": "0.37.0", "daemon": "0.37.0", "proto": "1.1", "noteHidden": True, "note": ""}
    assert out["stale"]["noteHidden"] is False and "0.37.0" in out["stale"]["note"] and "0.38.0" in out["stale"]["note"]
    assert out["down"]["daemon"] == "not running" and out["down"]["noteHidden"] is True
