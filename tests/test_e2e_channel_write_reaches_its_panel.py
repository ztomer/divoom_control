"""Real chain: a channel write reaches the panel selected at the CLICK (P5.6).

P5.2 made every channel control resolve the selected display at the gesture
(`divoom_gui/web_ui/channel_settings.js`), but the bridge call it then made
carried no mac: the Python side sent it to `current_divoom`, i.e. whichever
panel the bench had told the backend to select by the time the call RAN. A
selection change between the click and the backend's write therefore sent the
setting to the wrong panel.

This drives the whole chain with no mock in it except the panels' transport:
the real web UI, the real `DivoomGuiAPI` (in `tests/e2e_gui_bridge.py`'s
subprocess) and a real `divoomd` with two mock panels. The page's bridge
proxy holds the channel write back for a moment -- the time a pywebview call
can sit before its thread runs -- while the selection change goes through at
once, exactly the race a user makes by clicking a channel and then the other
panel. The daemon records a `switch_channel` per panel (`get_device_activity`),
so the assertion is what the daemon did, not what the page believes.

Skipped like the rest of the real-daemon suite: no browser, no divoomd built
for this tree, or a headless CI runner (pywebview needs an Aqua session).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js
from tests.support.daemon_binary import find_divoomd
from tests.support.gui_daemon_stack import IsolatedStack

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"

# The real bridge, with one seam: `window.__hold[name]` ms before a call is
# sent. `window.__landed` names every call whose reply came back.
_REAL_BRIDGE_API = """
window.__hold = {};
window.__landed = [];
window.__sent = [];
// The page's own record of what it showed (`set_device_activity`) is answered
// here: the daemon must record the switch on A by ITSELF, from the routed call.
const LOCAL = { set_device_activity: true };
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (name in LOCAL) return Promise.resolve(LOCAL[name]);
    const send = () => fetch(window.__BRIDGE_URL__ + '/call', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: name, args: args}),
    }).then(r => r.json()).then(d => {
        window.__sent.push({name, args, reply: d});
        window.__landed.push(name);
        if (d.error) throw new Error(d.error);
        return d.result;
    });
    const ms = window.__hold[name] || 0;
    return ms ? new Promise(r => setTimeout(r, ms)).then(send) : send();
}})};
"""


@pytest.fixture
def stack():
    require_browser()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.skip("the real DivoomGuiAPI bridge needs a macOS GUI session; runs locally")
    bin_path = find_divoomd()
    if bin_path is None:
        pytest.skip("divoomd for this tree is not built (cargo build -p divoomd)")
    s = IsolatedStack(bin_path)
    try:
        for mac, name in [(A, "Ditoo-Plus"), (B, "Pixoo64")]:
            reply = s.client.send_command("connect", {"mock": True, "mac": mac, "name": name})
            assert reply.get("success") is True, reply
        yield s
    finally:
        s.close()


def _kind_on(stack, mac):
    reply = stack.client.send_command("get_device_activity", {})
    return ((reply.get("activity") or {}).get(mac) or {}).get("kind"), reply


@pytest.mark.asyncio
async def test_a_channel_switch_lands_on_the_panel_clicked_not_the_one_selected_since(stack):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch(p)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await add_init_js(page, f"window.__BRIDGE_URL__ = {json.dumps(stack.bridge_url)};\n"
                              + _REAL_BRIDGE_API)
            await page.goto(f"file://{INDEX_HTML}")
            await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage"
                                " && !!document.querySelector('.tab-btn[data-channel=\"vj\"]')")
            await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
                {address: a, name: 'Desk', kind: 'clock', state: 'active'},
                {address: b, name: 'Kitchen', kind: 'clock', state: 'active'}]})""", [A, B])

            await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", A)
            await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{A}'")
            # The backend has taken A as the selection.
            await wait_js(page, "() => window.__landed.includes('select_device')", timeout=5000)
            assert stack.client.send_command("device_status", {}).get("selected") == A

            # Click VJ on A; its write is held while the user moves to B.
            await eval_js(page, "() => { window.__hold.switch_channel = 1200; }")
            await eval_js(page, "() => document.querySelector('.tab-btn[data-channel=\"vj\"]').click()")
            await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", B)
            await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{B}'")
            await wait_js(page, "() => window.__landed.filter(n => n === 'select_device').length >= 2",
                          timeout=5000)
            assert stack.client.send_command("device_status", {}).get("selected") == B, (
                "the selection reached the backend before the held write")

            await wait_js(page, "() => window.__landed.includes('switch_channel')", timeout=10000)
            on_a, reply = _kind_on(stack, A)
            on_b, _ = _kind_on(stack, B)
            sent = [c for c in await eval_js(page, "() => window.__sent")
                    if c["name"] in ("switch_channel", "select_device")]
            died = stack.daemon_proc.poll()
            if died is not None:
                out, err = stack._drain(stack.daemon_proc)
                every = [(c["name"], c["args"]) for c in await eval_js(page, "() => window.__sent")]
                pytest.fail(f"divoomd exited ({died}) mid-test; calls {every}; stderr tail: {err[-3000:]}")
            assert on_a == "vj", f"the VJ switch clicked on A must reach A: {reply}; calls {sent}"
            assert on_b != "vj", f"B was selected after the click and must not get it: {reply}"
        finally:
            await browser.close()
