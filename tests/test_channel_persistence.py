"""Browser-driven verification for per-device active channel persistence.
Verifies that:
1. Channel choices and options are saved per-MAC in localStorage ('divoom_device_channels').
2. When loading / refreshing devices, DisplayPreviewRegistry and the channel panel UI
   are rehydrated with the authentic active channel.
3. Daemon broadcast 'activity' events invoke window.Divoom.onActivity, syncing
   preview and UI controls across external clients (CLI/menubar/GUI).
"""
import asyncio
from pathlib import Path
import pytest
from tests.support.browser import launch as launch_browser, eval_js, wait_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"


@pytest.mark.asyncio
async def test_save_and_get_device_channel():
    """Verify saveDeviceChannel and getDeviceChannel write/read localStorage accurately."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => typeof window.saveDeviceChannel === 'function'")

        mac = "AA:BB:CC:11:22:33"
        res = await eval_js(page, """(m) => {
            window.saveDeviceChannel(m, 'cloud', { style: 1 });
            const saved = window.getDeviceChannel(m);
            const lowerSaved = window.getDeviceChannel(m.toLowerCase());
            const rawStorage = localStorage.getItem('divoom_device_channels');
            return {
                saved,
                lowerSaved,
                rawStorage: rawStorage ? JSON.parse(rawStorage) : null
            };
        }""", mac)

        assert res["saved"]["channel"] == "cloud"
        assert res["saved"]["opts"] == {"style": 1}
        assert res["lowerSaved"]["channel"] == "cloud"
        assert res["lowerSaved"]["opts"] == {"style": 1}
        assert mac in res["rawStorage"]
        assert res["rawStorage"][mac]["channel"] == "cloud"

        await browser.close()


@pytest.mark.asyncio
async def test_rehydration_on_bench_refresh():
    """Verify that stored active channel rehydrates preview and active tab on refresh."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window.SpatialStage")

        dev = "22:33:44:55:66:77"
        res = await eval_js(page, """(mac) => {
            // Seed saved channel in localStorage before refresh
            window.saveDeviceChannel(mac, 'visualizer', { style: 3 });

            // Seed device and refresh bench
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: mac, name: "Pixoo-Living", room: "Desk" }
            ];

            if (window.SpatialStage?.refresh) window.SpatialStage.refresh();

            const preview = window.DisplayPreviewRegistry.get(mac);
            const activeBtn = document.querySelector('.tab-btn.active[data-channel]');
            const activeTab = activeBtn ? activeBtn.getAttribute('data-channel') : null;

            return {
                channel: preview.channel,
                mode: preview.mode,
                activeTab: activeTab
            };
        }""", dev)

        assert res["channel"] == "visualizer"
        assert res["mode"] == "glyph"
        assert res["activeTab"] == "visualizer"

        await browser.close()


@pytest.mark.asyncio
async def test_on_activity_event_sync():
    """Verify window.Divoom.onActivity updates preview and active channel UI."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.Divoom?.onActivity")

        dev = "33:44:55:66:77:88"
        res = await eval_js(page, """(mac) => {
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: mac, name: "Timoo-Desk", room: "Desk" }
            ];
            if (window.SpatialStage?.refresh) window.SpatialStage.refresh();

            // Simulate daemon broadcast: channel switch to clock
            window.Divoom.onActivity({
                type: 'activity',
                mac: mac,
                kind: 'clock',
                style: 2
            });

            const saved = window.getDeviceChannel(mac);
            const preview = window.DisplayPreviewRegistry.get(mac);
            const activeBtn = document.querySelector('.tab-btn.active[data-channel]');
            const activeTab = activeBtn ? activeBtn.getAttribute('data-channel') : null;

            return {
                saved,
                channel: preview.channel,
                mode: preview.mode,
                activeTab: activeTab
            };
        }""", dev)

        assert res["saved"]["channel"] == "clock"
        assert res["channel"] == "clock"
        assert res["mode"] == "glyph"
        assert res["activeTab"] == "clock"

        await browser.close()


@pytest.mark.asyncio
async def test_on_activity_with_pixels_updates_the_preview():
    """2026-09-12: a live job's frame arrives on the bus with its pixels
    (`preview`); the panel's DisplayPreview must switch to that frame so the
    bench mirrors the device without any tab polling."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.Divoom?.onActivity")

        dev = "44:55:66:77:88:AA"
        png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
               "AAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")
        res = await eval_js(page, """([mac, png]) => {
            window.DivoomState.discoveredDevices = [{ address: mac, name: "Pixoo-Frame", room: "Desk" }];
            if (window.SpatialStage?.refresh) window.SpatialStage.refresh();
            window.Divoom.onActivity({ type: 'activity', mac, kind: 'music', preview: png });
            const disp = window.DisplayPreviewRegistry.get(mac);
            return { mode: disp.mode, src: disp.frameSrc, channel: disp.channel };
        }""", [dev, png])
        assert res["channel"] == "music"
        assert res["mode"] == "frame", "the preview must show the frame, not a glyph"
        assert res["src"] == png
        await browser.close()
