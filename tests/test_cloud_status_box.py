"""The Settings cloud status box has ONE renderer and says where the password lives.

v0.37 step 6 moved the Divoom password out of config.ini into the OS store.
Settings has to say so, and the box had two painters (startup and the save
path) that had already drifted in wording. Both now call
`window.renderCloudStatus`; this drives it under node with a stub DOM.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SETTINGS_JS = REPO / "divoom_gui" / "web_ui" / "settings_hardware.js"
APP_INIT_JS = REPO / "divoom_gui" / "web_ui" / "app_init.js"

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
function el() {
    return { style: {}, text: "", children: [],
             replaceChildren(...parts) {
                 this.text = parts.map(p => typeof p === "string" ? p : p.textContent).join("");
             } };
}
const box = el();
const window = { pywebview: null };
const document = {
    getElementById: id => (id === "divoom-cloud-status-box" ? box : null),
    createElement: () => ({ textContent: "" }),
    addEventListener: () => {},
};
const [jsPath, casesJson] = process.argv.slice(-2);
vm.runInNewContext(fs.readFileSync(jsPath, "utf8"), { window, document, setTimeout, console });
const out = {};
for (const [name, state, conf] of JSON.parse(casesJson)) {
    window.renderCloudStatus(state, conf);
    out[name] = { text: box.text, color: box.style.color, display: box.style.display };
}
process.stdout.write(JSON.stringify(out));
"""


def _render(cases):
    r = subprocess.run(
        ["node", "-e", _HARNESS, "--", str(SETTINGS_JS), json.dumps(cases)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@needs_node
def test_connected_names_the_account_and_where_the_password_lives():
    out = _render([
        ["keychain", "connected", {"cloud_email": "me@x.com", "cloud_password_store": "Keychain"}],
        ["file", "connected", {"cloud_email": "me@x.com", "cloud_password_store": "config.ini"}],
        ["old_daemon", "connected", {"cloud_email": "me@x.com"}],
    ])
    assert out["keychain"]["text"] == "Connected as me@x.com Password stored in Keychain."
    assert out["file"]["text"] == "Connected as me@x.com Password stored in config.ini."
    # A daemon that does not report the store gets no claim, not a wrong one.
    assert out["old_daemon"]["text"] == "Connected as me@x.com"
    assert all(v["display"] == "flex" for v in out.values())


@needs_node
def test_signed_out_is_a_setup_step_not_an_alarm():
    out = _render([
        ["out", "signed_out", {}],
        ["failed", "failed", {}],
    ])
    assert "Not signed in" in out["out"]["text"]
    assert out["out"]["color"] != out["failed"]["color"], "signed-out painted like a fault"
    assert out["failed"]["color"] == "#ef4444"
    assert "failed" in out["failed"]["text"]


def test_both_writers_go_through_the_one_renderer():
    for js in (SETTINGS_JS, APP_INIT_JS):
        src = js.read_text()
        assert "renderCloudStatus(" in src, js.name
        # No second painter: nobody else touches the box's innerHTML/style.
        body = src.replace(src[src.index("window.renderCloudStatus = function"):
                               src.index("window.refreshCloudStatus")], "") \
            if "window.renderCloudStatus = function" in src else src
        assert "divoom-cloud-status-box" not in body, f"{js.name} paints the box itself"
