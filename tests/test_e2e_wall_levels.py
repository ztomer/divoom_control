"""Real chain: with the wall selected, the deck's levels are the wall's (P6.6).

The bridge wrote the wall's brightness and volume (`set_brightness` /
`set_volume` with `MatrixWall`) and, since P6.4, answered which panel did not
take them -- but nothing on the page sent either. The deck's sliders belonged
to whichever panel the bench had selected (`window.PanelLevels` in
`divoom_gui/web_ui/panel_facts.js`), so with the wall chosen as the display a
brightness gesture changed one panel of it and left the rest.

No fake between the gesture and the panels: the real web UI, the real
`DivoomGuiAPI` (`tests/e2e_gui_bridge.py`) and a real `divoomd` with two mock
panels on a wall, Desk and Shelf. What a panel received is read off its own
wire (the daemon's `mock_sent`), not taken from the daemon's reply.

* one slider gesture reaches BOTH slots, once each;
* the volume row is shown only when every slot has a speaker, which each slot
  reports through `device_status`'s `features.speaker` (the vendor app's
  per-model switch, `divoomd/src/panel_features.rs`) -- a Pixoo has none.

A slot that does not take the write is named in the toast: the gestures are
in `tests/test_e2e_wall_write_names_the_panel.py` with the other wall writes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tests.support.browser import add_init_js, eval_js, install_toast_recorder, launch, require_browser, wait_js, wait_toast
from tests.support.daemon_binary import find_divoomd
from tests.support.gui_daemon_stack import IsolatedStack

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"
A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"
SLOTS = {A: {"x": 0, "y": 0, "size": 16, "name": "Desk", "room": "wall"},
         B: {"x": 1, "y": 0, "size": 16, "name": "Shelf", "room": "wall"}}

_REAL_BRIDGE_API = """
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) =>
    fetch(window.__BRIDGE_URL__ + '/call', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: name, args: args}),
    }).then(r => r.json()).then(d => { if (d.error) throw new Error(d.error); return d.result; })
})};
"""

_VOLUME_SHOWN = """() => { const r = document.getElementById('deck-volume-container');
    return !!r && !r.hidden && getComputedStyle(r).display !== 'none'; }"""


def _stack(panels):
    """A real daemon with mock panels `(mac, model name)`, or a skip."""
    require_browser()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.skip("the real DivoomGuiAPI bridge needs a macOS GUI session; runs locally")
    bin_path = find_divoomd()
    if bin_path is None:
        pytest.skip("divoomd for this tree is not built (cargo build -p divoomd)")
    s = IsolatedStack(bin_path)
    try:
        for mac, name in panels:
            reply = s.client.send_command("connect", {"mock": True, "mac": mac, "name": name})
            assert reply.get("success") is True, reply
    except BaseException:
        s.close()
        raise
    return s


def _sent(stack, mac, command_id):
    """Every `command_id` write `mac`'s mock panel was asked to send."""
    reply = stack.client.send_command("mock_sent", {"mac": mac})
    assert reply.get("success") is True, reply
    return [args for cid, args in reply["sent"] if cid == command_id]


def _wait_sent(stack, macs, command_id, before, timeout=15.0):
    """Each mac's new `command_id` writes since `before`, once every mac has
    one or the budget runs out (then what each had)."""
    deadline = time.monotonic() + timeout
    while True:
        new = {m: _sent(stack, m, command_id)[len(before[m]):] for m in macs}
        if all(new.values()) or time.monotonic() > deadline:
            time.sleep(0.3)   # a second sender would land here; count it
            return {m: _sent(stack, m, command_id)[len(before[m]):] for m in macs}
        time.sleep(0.1)


async def _wall_page(p, stack, names, bench_on):
    """The page with both panels owned, the bench on `bench_on`, then the
    wall chosen as the display (the selector's Virtual Wall button)."""
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await install_toast_recorder(page)
    await add_init_js(page, f"window.__BRIDGE_URL__ = {json.dumps(stack.bridge_url)};\n" + _REAL_BRIDGE_API)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.Divoom?.onOwnedDevices && !!window.PanelLevels")
    await eval_js(page, """([a, b, na, nb]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: na, kind: 'clock', state: 'active'},
        {address: b, name: nb, kind: 'clock', state: 'active'}]})""", [A, B, *names])
    # What each panel IS (its speaker) is the daemon's word, read after the
    # fleet arrives.
    await wait_js(page, f"() => {json.dumps([A, B])}.every(m => typeof window.panelHasSpeaker(m) === 'boolean')",
                  timeout=10000)
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", bench_on)
    await eval_js(page, """async (slots) => {
        window.DivoomState.assignedSlots = slots;
        await window.pywebview.api.update_wall_slots(JSON.stringify(slots));
        window.connectDevice('Virtual Wall', 'MatrixWall'); }""", SLOTS)
    await wait_js(page, "() => window._activeDeviceMac() === 'MatrixWall'", timeout=10000)
    return browser, page


def _slide(slider_id, value):
    return f"""(() => {{ const s = document.getElementById('{slider_id}');
        s.value = {value}; s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); }})()"""


@pytest.mark.asyncio
async def test_one_slider_gesture_reaches_every_slot_of_the_wall():
    from playwright.async_api import async_playwright

    stack = _stack([(A, "Ditoo-Plus"), (B, "Ditoo-Plus")])
    try:
        async with async_playwright() as p:
            browser, page = await _wall_page(p, stack, ("Desk", "Shelf"), bench_on=A)
            try:
                for slider, cid, value in (("global-brightness-slider", 0x74, 40),
                                           ("appbar-volume-slider", 0x08, 7)):
                    before = {m: _sent(stack, m, cid) for m in (A, B)}
                    await eval_js(page, f"() => {{ window.__divoomToasts.length = 0; {_slide(slider, value)}; }}")
                    got = _wait_sent(stack, (A, B), cid, before)
                    assert got == {A: [[value]], B: [[value]]}, (
                        f"one {slider} gesture on the wall must reach each slot once: {got}")
                    await wait_toast(page, "Wall", kind="success", timeout=10000)
                assert await eval_js(page, _VOLUME_SHOWN), "both slots have a speaker; the wall's volume must show"
            finally:
                await browser.close()
    finally:
        stack.close()


@pytest.mark.asyncio
async def test_the_wall_volume_is_hidden_when_a_slot_has_no_speaker():
    from playwright.async_api import async_playwright

    # The bench is on Desk, which HAS a speaker: the deck must answer for the
    # wall, where Shelf (a Pixoo) has none.
    stack = _stack([(A, "Ditoo-Plus"), (B, "Pixoo")])
    try:
        async with async_playwright() as p:
            browser, page = await _wall_page(p, stack, ("Desk", "Shelf"), bench_on=A)
            try:
                facts = await eval_js(page, "([a, b]) => [window.panelHasSpeaker(a), window.panelHasSpeaker(b)]", [A, B])
                assert facts == [True, False], f"the daemon's speaker facts for Desk and Shelf: {facts}"
                try:
                    await wait_js(page, f"() => !({_VOLUME_SHOWN})()", timeout=10000)
                except Exception as exc:
                    pytest.fail(f"Shelf has no speaker; the wall must offer no volume ({exc})")
                name = await eval_js(page, "() => document.getElementById('deck-device-name').textContent")
                assert "Wall" in name, f"the deck must say it is showing the wall: {name!r}"
                assert await eval_js(page, """() => { const s = document.getElementById('global-brightness-slider');
                    return !!s && !s.closest('.deck-slider-row').hidden; }"""), "the wall's brightness must show"
            finally:
                await browser.close()
    finally:
        stack.close()
