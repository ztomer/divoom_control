"""E2E device-status reporting — the per-device selector chips.

Drives the real web_ui in headless Chromium with a mock ``pywebview.api`` and
asserts the sidebar device chips always reflect the REAL state of each screen:
the active device, a daemon-owned streaming device, a degraded link, a
known-but-undetected device (R50), LAN devices, and daemon-owned devices that a
scan missed. Backend honesty is in ``test_device_status.py``; the appbar dot in
``test_e2e_device_status_dot.py``. Skipped if Playwright / a browser isn't
installed.
"""
import pytest
from pathlib import Path
from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

# A permissive mock daemon API. `get_*` calls return "{}" (valid JSON the app
# parses); tests override individual methods via window.__api[name].
_MOCK_API = """
window.__api = {};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page()
    await add_init_js(page, _MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.renderDeviceDots")
    return browser, page


@pytest.mark.asyncio
async def test_active_device_chip_is_marked_active():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         aria: c.getAttribute('aria-selected') };
            }""")
            assert res["active"] is True
            assert res["aria"] == "true"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_streaming_chip_shows_kind_and_clears_when_active():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            idle = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{
                    address:'AA', name:'Ditoo', daemonOwned:true,
                    activityKind:'music', activityState:'connected'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { streaming: c.classList.contains('chip-streaming'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert idle["streaming"] is True
            assert "music" in idle["badge"]
            active = await eval_js(page, """() => {
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         streaming: c.classList.contains('chip-streaming') };
            }""")
            assert active["active"] is True
            assert active["streaming"] is False   # active device isn't "streaming"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_degraded_chip_shows_reconnecting_badge():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{
                    address:'AA', name:'Ditoo', activityState:'degraded'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { degraded: c.classList.contains('chip-degraded'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert res["degraded"] is True
            assert "reconnecting" in res["badge"]
            # A degraded link on the ACTIVE device still shows both states.
            both = await eval_js(page, """() => {
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         degraded: c.classList.contains('chip-degraded') };
            }""")
            assert both["active"] and both["degraded"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_known_undetected_chip_is_distinct():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.__knownUndetectedDevices = [{address:'BB', name:'Pixoo'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const chips = [...document.querySelectorAll('#device-dots .device-chip')];
                const bb = chips.find(c => c.dataset.value === 'BB');
                const aa = chips.find(c => c.dataset.value === 'AA');
                return {
                    count: chips.length,
                    bbKnown: bb.classList.contains('chip-known'),
                    bbActive: bb.classList.contains('chip-active'),
                    bbStreaming: bb.classList.contains('chip-streaming'),
                    bbBadge: bb.querySelector('.device-chip-state')?.textContent || '',
                    bbTitle: bb.title,
                    aaKnown: aa.classList.contains('chip-known'),
                    aaBadge: aa.querySelector('.device-chip-state')?.textContent || '',
                };
            }""")
            assert res["count"] == 2
            assert res["bbKnown"] is True
            assert res["bbActive"] is False
            assert res["bbStreaming"] is False
            assert res["aaKnown"] is False
            # A faded chip alone is too subtle at a glance - it must SAY it's
            # not currently reachable, not just look dimmer (the actual bug
            # report: "4 devices listed, only 3 online" with no clear signal
            # of which was which).
            assert "not in range" in res["bbBadge"]
            assert "not in range" in res["bbTitle"]
            assert res["aaBadge"] == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_detected_device_is_not_known_chip():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.__knownUndetectedDevices = [{address:'AA', name:'Ditoo'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const chips = [...document.querySelectorAll('#device-dots .device-chip')];
                const aa = chips.filter(c => c.dataset.value === 'AA');
                return { count: aa.length,
                         known: aa[0]?.classList.contains('chip-known') };
            }""")
            assert res["count"] == 1          # not duplicated
            assert res["known"] is False      # detected wins over cache
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_lan_device_renders_as_chip():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [];
                window.__knownUndetectedDevices = [];
                window.DivoomState.registeredLanDevices = [{ip:'10.0.0.5'}];
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { value: c?.dataset.value, text: c?.textContent || '' };
            }""")
            assert res["value"] == "LAN:10.0.0.5"
            assert "Wi-Fi" in res["text"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_duplicate_known_address_not_double_rendered():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.__knownUndetectedDevices = [{address:'AA', name:'Ditoo'}];
                window.renderDeviceDots();
                const aa = [...document.querySelectorAll('#device-dots .device-chip')]
                    .filter(c => c.dataset.value === 'AA');
                return aa.length;
            }""")
            assert res == 1
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_owned_devices_event_adds_daemon_owned_missing_from_scan():
    # R59: the daemon PUSHES owned-device changes as `owned_devices` events; the
    # old 4s get_device_activity poll (refreshOwnedDevices) is gone. Drive the
    # live handler window.Divoom.onOwnedDevices directly.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [];
                return window.Divoom.onOwnedDevices({type:'owned_devices', devices:[
                    {address:'AA', name:'Ditoo', kind:'weather', state:'connected'}]});
            }""")
            await wait_js(page, 
                "() => !!document.querySelector('#device-dots .device-chip')",
                timeout=4000)
            res = await eval_js(page, """() => {
                const c = document.querySelector('#device-dots .device-chip');
                return { value: c.dataset.value,
                         streaming: c.classList.contains('chip-streaming'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert res["value"] == "AA"
            assert res["streaming"] is True
            assert "weather" in res["badge"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_merge_discovered_devices_unions_by_address():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'old'}];
                const merged = window.mergeDiscoveredDevices([
                    {address:'AA', name:'new'}, {address:'BB', name:'Pixoo'}]);
                const aa = merged.find(d => d.address === 'AA');
                return { count: merged.length, aaName: aa.name };
            }""")
            assert res["count"] == 2          # AA not duplicated
            assert res["aaName"] == "new"     # fresh scan wins
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_restored_device_shows_not_in_range_until_confirmed():
    # R61 follow-up (user-reported): session-restore populates discoveredDevices
    # from the persisted known-devices cache — NOT devices confirmed present
    # this session. Before the fix, these looked identical to a live/detected
    # chip; unconfirmed:true must produce the same "not in range" treatment as
    # the knownPending merge already gets.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices =
                    [{address:'AA', name:'Ditoo', unconfirmed:true}];
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '',
                         title: c.title };
            }""")
            assert res["known"] is True
            assert "not in range" in res["badge"]
            assert "not in range" in res["title"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_scan_merge_clears_unconfirmed_flag():
    # A device restored as unconfirmed that a REAL scan then finds must lose
    # the "not in range" badge — mergeDiscoveredDevices' union-only merge (R46
    # #5) can add/update an address but never on its own downgrades one, so
    # clearing unconfirmed explicitly on a scan hit is what actually fixes it.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices =
                    [{address:'AA', name:'Ditoo', unconfirmed:true}];
                window.mergeDiscoveredDevices([{address:'AA', name:'Ditoo'}]);
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert res["known"] is False
            assert res["badge"] == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_single_scan_miss_does_not_downgrade():
    # R62 (user-reported): a device present all session that a scan just
    # happens to skip once must NOT immediately flash "not in range" — a
    # single miss isn't reliable proof of absence.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.mergeDiscoveredDevices([]);   // one miss
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert res["known"] is False
            assert res["badge"] == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_mid_session_scan_misses_downgrade_after_threshold():
    # R62 fix: unlike a one-shot session-restore flag, a device confirmed
    # present THIS session must ALSO show "not in range" if it later drops
    # out of BLE range mid-session -- consecutive scan misses (not just one)
    # now downgrade it live, the same badge the restore path already gets.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.mergeDiscoveredDevices([]);   // miss 1 -- below threshold
                window.mergeDiscoveredDevices([]);   // miss 2 -- hits threshold
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""")
            assert res["known"] is True
            assert "not in range" in res["badge"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_redetection_resets_the_miss_counter():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.mergeDiscoveredDevices([]);                    // miss 1
                window.mergeDiscoveredDevices([{address:'AA', name:'Ditoo'}]);  // re-detected -- resets
                window.mergeDiscoveredDevices([]);                    // miss 1 again, not 2
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known') };
            }""")
            assert res["known"] is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_daemon_owned_device_exempt_from_scan_miss_downgrade():
    # R47: an owned/streaming device intentionally doesn't advertise (it's
    # connected, not idle) so a scan ALWAYS misses it -- that must never be
    # read as "not in range".
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [{
                    address:'AA', name:'Ditoo', daemonOwned:true,
                    activityKind:'music', activityState:'connected'}];
                window.mergeDiscoveredDevices([]);
                window.mergeDiscoveredDevices([]);
                window.mergeDiscoveredDevices([]);
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         streaming: c.classList.contains('chip-streaming') };
            }""")
            assert res["known"] is False
            assert res["streaming"] is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_active_device_never_shows_not_in_range_even_if_unconfirmed():
    # A device can be BOTH the currently-connected/active one AND still
    # carry a stale unconfirmed flag (the confirming scan/activity update
    # hasn't landed yet) — the active dot is the stronger, more current
    # signal and must never be contradicted by a "not in range" badge.
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices =
                    [{address:'AA', name:'Ditoo', unconfirmed:true}];
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '',
                         title: c.title };
            }""")
            assert res["active"] is True
            assert res["known"] is False
            assert res["badge"] == ""
            assert "not in range" not in res["title"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_render_device_dots_empty_state_no_crash():
    require_browser()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(page, """() => {
                window.DivoomState.discoveredDevices = [];
                window.__knownUndetectedDevices = [];
                window.DivoomState.registeredLanDevices = [];
                window.renderDeviceDots();
                return document.querySelectorAll('#device-dots .device-chip').length;
            }""")
            assert res == 0
        finally:
            await browser.close()
