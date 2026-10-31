"""E2E -- the Hot tab's lasting verdict line (U.5, P5.13 option A).

The owner, 2026-10-26: "The hot channel update status is very unclear and need
to be rethought." Picked 2026-10-31: "A: verdict line (Recommended)". Under the
Update Hot Channel button, ONE line per panel that stays: what the newest run
by ANY path did (the button, Sync Now, the daily schedule), read from the
daemon's per-panel record (``hotchannel_state.json`` ``panels``), a failure
replacing the earlier success, nothing vanishing after 3 s.

What these tests found red on the old code: the button's verdict lived 3 s
and was gone; the stamp under it was written only by a SUCCESSFUL button run
and read a different file than the schedule wrote, so the owner's failed
scheduled run (2026-10-26, "connect already in progress" on all four panels)
showed nowhere; and a progress event naming another panel drove this panel's
button.

Drives the real web UI with a mocked bridge; skipped without --run-browser.
"""
import time

import pytest

from tests.support.browser import add_init_js, eval_js, install_toast_recorder, launch, require_browser, wait_js
from tests.test_e2e_hot_channel_sync_button import INDEX_HTML

PANEL = "f90d2cc9-420e-65f9-9e06-f9554470fced"
OTHER = "a9fccb71-3d3d-4de3-c381-0de382cdc4aa"


def now() -> int:
    return int(time.time())


_MOCK_API = """
window.__updates = [];
window.__verdicts = %VERDICTS%;
window.__api = {
    hot_channel_update: (mac) => { window.__updates.push(mac); return JSON.stringify({success: true, started: true}); },
    hot_verdict: (mac) => JSON.stringify(window.__verdicts[mac] || {}),
    hot_verdicts: () => JSON.stringify(window.__verdicts),
};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""



def schedule_failed(age_s: int) -> dict:
    """The owner's scheduled run of 2026-10-26, as the daemon now records it."""
    return {"at": now() - age_s, "by": "schedule", "outcome": "failed",
            "error": f"Connection to {PANEL} failed: connect already in progress",
            "offered": 0, "fetched": 0, "delivered": 0}

_LINE = """() => { const el = document.getElementById('hot-verdict');
    return {text: el.textContent, kind: el.dataset.kind,
            glyph: el.querySelector('.hot-verdict-glyph')?.textContent}; }"""


async def _open(p, verdicts):
    import json
    browser = await launch(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API.replace("%VERDICTS%", json.dumps(verdicts)))
    await install_toast_recorder(page)
    await page.goto(f"file://{INDEX_HTML}")
    await wait_js(page, "() => !!window.DivoomState && !!window.Divoom?.onOwnedDevices"
                        " && !!window.SpatialStage && !!window.HotVerdict")
    await eval_js(page, """([a, b]) => window.Divoom.onOwnedDevices({type: 'owned_devices', devices: [
        {address: a, name: 'Timoo-light-4', kind: 'clock', state: 'active'},
        {address: b, name: 'Pixoo-1', kind: 'clock', state: 'active'}]})""", [PANEL, OTHER])
    await eval_js(page, "(m) => window.Divoom.onSelection({type: 'selection', mac: m})", PANEL)
    await wait_js(page, f"() => window.SpatialStage.getSelectedMac() === '{PANEL}'")
    await page.click('.nav-btn[data-tab="pixel-art"]')
    await page.click('[data-pixel-tab="pixel-hot-channel"]')
    await page.wait_for_selector("#pixel-hot-channel.active")
    return browser, page


@pytest.mark.asyncio
async def test_the_scheduled_runs_failure_shows_under_the_button():
    """The schedule's run is a verdict like a button press: the owner's failed
    run of 2026-10-26 reads, in words and glyph, where the owner looks."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, {PANEL: schedule_failed(2 * 3600)})
        try:
            await wait_js(page, "() => document.getElementById('hot-verdict').dataset.kind === 'fail'")
            line = await eval_js(page, _LINE)
            assert line["glyph"] == "✗", line
            assert "Failed 2 h ago: connect already in progress" in line["text"], line
            assert "by the schedule" in line["text"], line
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_failure_replaces_the_success_and_nothing_vanishes():
    """The newest record wins whatever path wrote it, and the line stays."""
    require_browser()
    from playwright.async_api import async_playwright

    ok = {"at": now() - 600, "by": "button", "outcome": "ok", "offered": 23, "fetched": 23, "delivered": 0}
    async with async_playwright() as p:
        browser, page = await _open(p, {PANEL: ok})
        try:
            await wait_js(page, "() => document.getElementById('hot-verdict').dataset.kind === 'ok'")
            line = await eval_js(page, _LINE)
            assert line["glyph"] == "✓" and "Up to date · checked 10 min ago" in line["text"], line

            await eval_js(page, """([m, v]) => window.Divoom.onHotStatus(
                {type: 'hot_status', mac: m, verdict: v})""", [PANEL, schedule_failed(60)])
            await wait_js(page, "() => document.getElementById('hot-verdict').dataset.kind === 'fail'")
            await page.wait_for_timeout(3500)   # the old verdict was gone after 3 s
            line = await eval_js(page, _LINE)
            assert line["kind"] == "fail" and line["glyph"] == "✗", line

            # Another panel's record changes nothing here.
            await eval_js(page, """([m, v]) => window.Divoom.onHotStatus(
                {type: 'hot_status', mac: m, verdict: v})""", [OTHER, ok])
            assert (await eval_js(page, _LINE))["kind"] == "fail"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_button_starts_and_shows_progress_and_the_line_carries_the_result():
    """The button only starts and shows progress; on `done` it is the button
    again at once, the line is the record, and no toast repeats it."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, {})
        try:
            await wait_js(page, "() => document.getElementById('hot-verdict').dataset.kind === 'none'")
            assert "Never checked" in (await eval_js(page, _LINE))["text"]

            await page.click("#hot-update-btn")
            assert await eval_js(page, "() => window.__updates") == [PANEL]
            await eval_js(page, """(m) => window.Divoom.onHotProgress(
                {type: 'hot_progress', mac: m, phase: 'uploading', current: 4, total: 23})""", PANEL)
            text = await eval_js(page, "() => document.getElementById('hot-progress-text').textContent")
            assert "2/2 Uploading to device 4/23" in text
            assert (await eval_js(page, _LINE))["kind"] == "busy"

            # The daemon records the verdict, THEN publishes `done`.
            await eval_js(page, """([m, now]) => {
                window.__verdicts[m] = {at: now, by: 'button', outcome: 'ok',
                                        offered: 23, fetched: 23, delivered: 3};
                window.Divoom.onHotProgress({type: 'hot_progress', mac: m, phase: 'done',
                                             result: {served: ['a', 'b', 'c'], manifest: 23, downloaded: 23}});
            }""", [PANEL, now()])
            await wait_js(page, "() => document.getElementById('hot-update-btn').disabled === false",
                          timeout=1000)
            await wait_js(page, "() => document.getElementById('hot-verdict').dataset.kind === 'new'")
            line = await eval_js(page, _LINE)
            assert line["glyph"] == "↓" and "3 new files · just now" in line["text"], line
            toasts = await eval_js(page, "() => (window.__divoomToasts || []).map(t => t.message)")
            assert not any("Hot channel" in t for t in toasts), toasts
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_run_on_another_panel_leaves_this_panels_button_alone():
    """Progress events name their panel; Sync Now on the Pixoo is not the
    Timoo's button."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, {})
        try:
            await eval_js(page, """(m) => window.Divoom.onHotProgress(
                {type: 'hot_progress', mac: m, phase: 'downloading', current: 3, total: 23})""", OTHER)
            assert await eval_js(page, "() => document.getElementById('hot-update-btn').disabled") is False
            await eval_js(page, """(m) => window.Divoom.onHotProgress(
                {type: 'hot_progress', mac: m, phase: 'error', error: 'boom'})""", OTHER)
            assert await eval_js(page, "() => document.getElementById('hot-update-btn').disabled") is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_every_verdict_is_told_apart_by_glyph_and_words_not_colour():
    """Never one channel (UI rule 5): render each kind, drop the colour, and
    the glyph and the words still differ."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, {})
        try:
            lines = await eval_js(page, """(now) => {
                const L = (e, o) => window.HotVerdict.line(e, Object.assign({nowMs: now * 1000}, o || {}));
                const base = {at: now - 7200, offered: 23, fetched: 23};
                const kinds = {
                    never: L(null),
                    ok: L(Object.assign({by: 'button', outcome: 'ok', delivered: 0}, base)),
                    fresh: L(Object.assign({by: 'button', outcome: 'ok', delivered: 3}, base)),
                    partial: L({at: now - 7200, by: 'button', outcome: 'ok', offered: 23, fetched: 19, delivered: 0}),
                    failed: L({at: now - 7200, by: 'schedule', outcome: 'failed', error: 'could not connect'}),
                    stored: L({at: now - 7200, by: 'schedule', outcome: 'ok', offered: 5, fetched: 5, delivered: 5}),
                    short_failed: L({at: now - 7200, by: 'schedule', outcome: 'failed', error: 'x'}, {short: true}),
                };
                return kinds;
            }""", now())
            core = [lines[k] for k in ("never", "ok", "fresh", "partial", "failed")]
            assert len({line["glyph"] for line in core}) == 5, lines
            assert len({line["text"] for line in core}) == 5, lines
            assert lines["ok"]["text"] == "Up to date · checked 2 h ago", lines
            assert lines["partial"]["text"].startswith("4 of 23 files could not be fetched"), lines
            assert lines["failed"]["text"] == "Failed 2 h ago: could not connect · by the schedule", lines
            assert lines["stored"]["text"] == "5 files stored · 2 h ago by the schedule", lines
            assert lines["short_failed"]["text"] == "Failed · 2 h ago", lines
        finally:
            await browser.close()
