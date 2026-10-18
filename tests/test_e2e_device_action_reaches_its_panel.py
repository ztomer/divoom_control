"""Real chain: a Tools write and a live widget reach the panel selected at the CLICK (P5.7).

P5.6 closed this race for the channel writes
(`tests/test_e2e_channel_write_reaches_its_panel.py`). The Tools tab, the live
widgets and the gallery push still sent no mac: the Python side acted on
`current_divoom`, the panel the bench had told the backend to select by the
time the call RAN, so a click followed by a click on another panel acted on
the second one.

This drives the whole chain with no mock in it except the panels' transport:
the real web UI, the real `DivoomGuiAPI` (in `tests/e2e_gui_bridge.py`'s
subprocess) and a real `divoomd` with two mock panels. The page's bridge proxy
holds the write back for a moment -- the time a pywebview call can sit before
its thread runs -- while the selection change goes through at once. What is
asserted is what the DAEMON did: the name each mock panel now reports
(`device.get_device_name` on that mac) and the live jobs each one runs
(`live_job_list`).

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
from tests.test_e2e_channel_write_reaches_its_panel import _REAL_BRIDGE_API

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"


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


def _name_of(stack, mac):
    reply = stack.client.send_command(
        "device_call", {"method": "device.get_device_name", "args": [], "kwargs": {}, "mac": mac})
    return reply.get("result"), reply


def _jobs_on(stack, mac):
    reply = stack.client.send_command("live_job_list", {"mac": mac})
    return sorted(j.get("kind") for j in (reply.get("jobs") or [])
                  if not j.get("done") and not j.get("cancelled")), reply


async def _page(p, stack):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await add_init_js(page, f"window.__BRIDGE_URL__ = {json.dumps(stack.bridge_url)};\n"
                      + _REAL_BRIDGE_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.SpatialStage"
                        " && !!window.ChannelSettings && !!document.getElementById('device-name-save')"
                        " && !!document.getElementById('widget-card-sysmon')")
    await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: 'Desk', kind: 'clock', state: 'active'},
        {address: b, name: 'Kitchen', kind: 'clock', state: 'active'}]})""", [A, B])
    return browser, page


async def _select(page, mac, n):
    """Select `mac` and wait until the backend has taken it (the n-th select)."""
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", mac)
    await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{mac}'")
    await wait_js(page, f"() => window.__landed.filter(n => n === 'select_device').length >= {n}",
                  timeout=5000)


def _alive(stack, page_calls):
    died = stack.daemon_proc.poll()
    if died is not None:
        _out, err = stack._drain(stack.daemon_proc)
        pytest.fail(f"divoomd exited ({died}) mid-test; calls {page_calls}; stderr tail: {err[-3000:]}")


@pytest.mark.asyncio
async def test_a_rename_lands_on_the_panel_clicked_not_the_one_selected_since(stack):
    from playwright.async_api import async_playwright

    before_b, _ = _name_of(stack, B)
    async with async_playwright() as p:
        browser, page = await _page(p, stack)
        try:
            await _select(page, A, 1)
            await eval_js(page, "() => { window.__hold.set_device_name = 1200; }")
            await eval_js(page, "() => { document.getElementById('device-name-input').value = 'Desk 2';"
                                " document.getElementById('device-name-save').click(); }")
            await _select(page, B, 2)
            assert stack.client.send_command("device_status", {}).get("selected") == B, (
                "the selection reached the backend before the held write")

            await wait_js(page, "() => window.__landed.includes('set_device_name')", timeout=10000)
            _alive(stack, await eval_js(page, "() => window.__sent.map(c => c.name)"))
            on_a, reply = _name_of(stack, A)
            on_b, _ = _name_of(stack, B)
            assert on_a == "Desk 2", f"the rename clicked on A must reach A: {reply}"
            assert on_b == before_b, f"B was selected after the click and must keep its name: {on_b}"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_live_widget_starts_on_the_panel_clicked_not_the_one_selected_since(stack):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _page(p, stack)
        try:
            await _select(page, A, 1)
            await eval_js(page, "() => document.querySelector('.nav-btn[data-tab=\"data-sources\"]').click()")
            await eval_js(page, "() => { document.getElementById('sysmon-live').checked = true;"
                                " window.__hold.toggle_sysmon_sync = 1200; }")
            await eval_js(page, "() => document.getElementById('widget-card-sysmon').click()")
            await _select(page, B, 2)

            await wait_js(page, "() => window.__landed.includes('toggle_sysmon_sync')", timeout=10000)
            sent = await eval_js(page, "() => window.__sent.filter(c => c.name.startsWith('toggle_'))")
            _alive(stack, sent)
            on_a, reply = _jobs_on(stack, A)
            on_b, _ = _jobs_on(stack, B)
            assert on_a == ["sysmon"], f"the widget clicked on A must run on A: {reply}; calls {sent}"
            assert on_b == [], f"B was selected after the click and must run nothing: {on_b}"
        finally:
            await browser.close()
