"""E2E device-status chips -- scan-merge and miss-downgrade.

Split from ``test_e2e_device_status_chips.py`` (which covers how each chip
state RENDERS): these drive the discovery merge -- union by address, restored
devices marked not-in-range until a scan confirms them, the scan-miss counter
and its threshold, and the exemptions (daemon-owned, active). Skipped if
Playwright / a browser isn't installed.
"""

import pytest
from tests.support.browser import eval_js, require_browser, wait_js
from tests.support.device_chips_page import _open


@pytest.mark.asyncio
async def test_merge_discovered_devices_unions_by_address():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'old'}];
                const merged = window.mergeDiscoveredDevices([
                    {address:'AA', name:'new'}, {address:'BB', name:'Pixoo'}]);
                const aa = merged.find(d => d.address === 'AA');
                return { count: merged.length, aaName: aa.name };
            }""",
            )
            assert res["count"] == 2  # AA not duplicated
            assert res["aaName"] == "new"  # fresh scan wins
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices =
                    [{address:'AA', name:'Ditoo', unconfirmed:true}];
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '',
                         title: c.title };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices =
                    [{address:'AA', name:'Ditoo', unconfirmed:true}];
                window.mergeDiscoveredDevices([{address:'AA', name:'Ditoo'}]);
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.mergeDiscoveredDevices([]);   // one miss
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.mergeDiscoveredDevices([]);   // miss 1 -- below threshold
                window.mergeDiscoveredDevices([]);   // miss 2 -- hits threshold
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.mergeDiscoveredDevices([]);                    // miss 1
                window.mergeDiscoveredDevices([{address:'AA', name:'Ditoo'}]);  // re-detected -- resets
                window.mergeDiscoveredDevices([]);                    // miss 1 again, not 2
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { known: c.classList.contains('chip-known') };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
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
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices =
                    [{address:'AA', name:'Ditoo', unconfirmed:true}];
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         known: c.classList.contains('chip-known'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '',
                         title: c.title };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [];
                window.__knownUndetectedDevices = [];
                window.DivoomState.registeredLanDevices = [];
                window.renderDeviceDots();
                return document.querySelectorAll('#device-dots .device-chip').length;
            }""",
            )
            assert res == 0
        finally:
            await browser.close()
