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
from tests.support.browser import eval_js, require_browser, wait_js
from tests.support.device_chips_page import _open


@pytest.mark.asyncio
async def test_active_device_chip_is_marked_active():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         aria: c.getAttribute('aria-selected') };
            }""",
            )
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
            idle = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{
                    address:'AA', name:'Ditoo', daemonOwned:true,
                    activityKind:'music', activityState:'connected'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { streaming: c.classList.contains('chip-streaming'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""",
            )
            assert idle["streaming"] is True
            assert "music" in idle["badge"]
            active = await eval_js(
                page,
                """() => {
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         streaming: c.classList.contains('chip-streaming') };
            }""",
            )
            assert active["active"] is True
            assert active["streaming"] is False  # active device isn't "streaming"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_degraded_chip_shows_reconnecting_badge():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{
                    address:'AA', name:'Ditoo', activityState:'degraded'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { degraded: c.classList.contains('chip-degraded'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""",
            )
            assert res["degraded"] is True
            assert "reconnecting" in res["badge"]
            # A degraded link on the ACTIVE device still shows both states.
            both = await eval_js(
                page,
                """() => {
                document.getElementById('banner-device-mac').textContent = 'AA';
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { active: c.classList.contains('chip-active'),
                         degraded: c.classList.contains('chip-degraded') };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
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
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.__knownUndetectedDevices = [{address:'AA', name:'Ditoo'}];
                document.getElementById('banner-device-mac').textContent = '';
                window.renderDeviceDots();
                const chips = [...document.querySelectorAll('#device-dots .device-chip')];
                const aa = chips.filter(c => c.dataset.value === 'AA');
                return { count: aa.length,
                         known: aa[0]?.classList.contains('chip-known') };
            }""",
            )
            assert res["count"] == 1  # not duplicated
            assert res["known"] is False  # detected wins over cache
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_lan_device_renders_as_chip():
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
                window.DivoomState.registeredLanDevices = [{ip:'10.0.0.5'}];
                window.renderDeviceDots();
                const c = document.querySelector('#device-dots .device-chip');
                return { value: c?.dataset.value, text: c?.textContent || '' };
            }""",
            )
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
            res = await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [{address:'AA', name:'Ditoo'}];
                window.__knownUndetectedDevices = [{address:'AA', name:'Ditoo'}];
                window.renderDeviceDots();
                const aa = [...document.querySelectorAll('#device-dots .device-chip')]
                    .filter(c => c.dataset.value === 'AA');
                return aa.length;
            }""",
            )
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
            await eval_js(
                page,
                """() => {
                window.DivoomState.discoveredDevices = [];
                return window.Divoom.onOwnedDevices({type:'owned_devices', devices:[
                    {address:'AA', name:'Ditoo', kind:'weather', state:'connected'}]});
            }""",
            )
            await wait_js(page, "() => !!document.querySelector('#device-dots .device-chip')")
            res = await eval_js(
                page,
                """() => {
                const c = document.querySelector('#device-dots .device-chip');
                return { value: c.dataset.value,
                         streaming: c.classList.contains('chip-streaming'),
                         badge: c.querySelector('.device-chip-state')?.textContent || '' };
            }""",
            )
            assert res["value"] == "AA"
            assert res["streaming"] is True
            assert "weather" in res["badge"]
        finally:
            await browser.close()
