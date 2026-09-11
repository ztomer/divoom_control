"""Browser-driven verification for DisplayPreviewRegistry and per-display isolation.
"""
import asyncio
import pytest
from pathlib import Path
from tests.support.browser import launch as launch_browser, eval_js, wait_js, add_init_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"


@pytest.mark.asyncio
async def test_browser_display_preview_registry():
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1200, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry")

        # 1. Verify DisplayPreview and DisplayPreviewRegistry exist in window
        res = await eval_js(page, """() => {
            return {
                hasDisplayPreview: typeof window.DisplayPreview === "function",
                hasRegistry: typeof window.DisplayPreviewRegistry === "object" && window.DisplayPreviewRegistry !== null,
            };
        }""")
        assert res["hasDisplayPreview"] is True
        assert res["hasRegistry"] is True

        # 2. Setup 2 distinct devices in DivoomState
        dev1 = "11:22:33:44:55:01"
        dev2 = "11:22:33:44:55:02"
        isolation_res = await eval_js(page, """([d1, d2]) => {
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: d1, name: "Pixoo-Desk" },
                { address: d2, name: "Ditoo-Shelf" }
            ];
            window.DisplayPreviewRegistry.syncFromFleet(window.DivoomState.discoveredDevices);

            const p1 = window.DisplayPreviewRegistry.get(d1);
            const p2 = window.DisplayPreviewRegistry.get(d2);

            // Set d1 to clock, d2 to visualizer
            p1.setActivity("clock", { style: 1, color: "#ff5a5a" });
            p2.setActivity("visualizer", { color: "#00cc66" });

            // Now set a real image frame on d1 only
            const testFrame = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
            p1.setFrame(testFrame);

            return {
                d1_channel: p1.channel,
                d1_mode: p1.mode,
                d1_frame: p1.frameSrc,
                d2_channel: p2.channel,
                d2_mode: p2.mode,
                d2_frame: p2.frameSrc,
                isolated: (p1.frameSrc !== p2.frameSrc) && (p1.channel !== p2.channel)
            };
        }""", [dev1, dev2])

        assert isolation_res["isolated"] is True
        assert isolation_res["d1_channel"] == "clock"
        assert isolation_res["d1_mode"] == "frame"
        assert isolation_res["d2_channel"] == "visualizer"
        assert isolation_res["d2_mode"] == "glyph"
        assert isolation_res["d2_frame"] is None

        # 3. Verify Canvas rendering with integer pixel sharpness (non-blank)
        canvas_res = await eval_js(page, """(d1) => {
            const p1 = window.DisplayPreviewRegistry.get(d1);
            p1.setActivity("clock", { style: 0, color: "#ffffff" });

            const canvas = document.createElement("canvas");
            canvas.width = 16;
            canvas.height = 16;
            p1.renderTo(canvas, 1);

            const ctx = canvas.getContext("2d");
            const imgData = ctx.getImageData(0, 0, 16, 16).data;

            let nonBlackPixels = 0;
            for (let i = 0; i < imgData.length; i += 4) {
                const r = imgData[i];
                const g = imgData[i + 1];
                const b = imgData[i + 2];
                if (r > 30 || g > 30 || b > 30) {
                    nonBlackPixels++;
                }
            }
            return { nonBlackPixels, total: 256 };
        }""", dev1)

        assert canvas_res["nonBlackPixels"] > 0
        assert canvas_res["nonBlackPixels"] < 256

        await browser.close()


@pytest.mark.asyncio
async def test_browser_channel_controls_two_way_sync():
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1200, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window.syncChannelControlsToDisplay")

        dev1 = "11:22:33:44:55:01"
        dev2 = "11:22:33:44:55:02"

        sync_res = await eval_js(page, """([d1, d2]) => {
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: d1, name: "Pixoo-Desk", room: "Desk" },
                { address: d2, name: "Ditoo-Shelf", room: "Wall" }
            ];
            window.DisplayPreviewRegistry.syncFromFleet(window.DivoomState.discoveredDevices);

            const p1 = window.DisplayPreviewRegistry.get(d1);
            const p2 = window.DisplayPreviewRegistry.get(d2);

            // Configure d1 with Clock Rainbow (1) and #ff5a5a
            p1.setActivity("clock", { style: 1, color: "#ff5a5a" });
            // Configure d2 with Clock Analog Square (3) and #5aabff
            p2.setActivity("clock", { style: 3, color: "#5aabff" });

            // Step 1: Sync to d1
            window.syncChannelControlsToDisplay(d1);
            const d1_style = window.DivoomState.selectedClockStyle;
            const d1_activeTile = document.querySelector("#clock-faces-grid .selector-cell.active")?.getAttribute("data-value");
            const d1_color = document.getElementById("clock-color-input")?.value;

            // Step 2: Sync to d2
            window.syncChannelControlsToDisplay(d2);
            const d2_style = window.DivoomState.selectedClockStyle;
            const d2_activeTile = document.querySelector("#clock-faces-grid .selector-cell.active")?.getAttribute("data-value");
            const d2_color = document.getElementById("clock-color-input")?.value;

            // Step 3: Switch back to d1
            window.syncChannelControlsToDisplay(d1);
            const back_d1_style = window.DivoomState.selectedClockStyle;
            const back_d1_activeTile = document.querySelector("#clock-faces-grid .selector-cell.active")?.getAttribute("data-value");
            const back_d1_color = document.getElementById("clock-color-input")?.value;

            return {
                d1_style, d1_activeTile, d1_color,
                d2_style, d2_activeTile, d2_color,
                back_d1_style, back_d1_activeTile, back_d1_color
            };
        }""", [dev1, dev2])

        assert sync_res["d1_style"] == 1
        assert sync_res["d1_activeTile"] == "1"
        assert sync_res["d1_color"] == "#ff5a5a"

        assert sync_res["d2_style"] == 3
        assert sync_res["d2_activeTile"] == "3"
        assert sync_res["d2_color"] == "#5aabff"

        assert sync_res["back_d1_style"] == 1
        assert sync_res["back_d1_activeTile"] == "1"
        assert sync_res["back_d1_color"] == "#ff5a5a"

        await browser.close()


@pytest.mark.asyncio
async def test_browser_multi_screen_streamer_isolation():
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1200, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window.markActiveDeviceFrame")

        dev1 = "11:22:33:44:55:01"
        dev2 = "11:22:33:44:55:02"

        stream_res = await eval_js(page, """([d1, d2]) => {
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: d1, name: "Pixoo-Desk" },
                { address: d2, name: "Ditoo-Shelf" }
            ];
            window.DisplayPreviewRegistry.syncFromFleet(window.DivoomState.discoveredDevices);

            const p1 = window.DisplayPreviewRegistry.get(d1);
            const p2 = window.DisplayPreviewRegistry.get(d2);

            // Bind d1 to sysmon
            p1.bindJob("sysmon");
            // Bind d2 to clock
            p2.setActivity("clock", { style: 2, color: "#00ffcc" });

            // Active device in UI is switched to d2 (Clock screen)
            const banner = document.getElementById("banner-device-mac");
            if (banner) banner.textContent = d2;

            // Background streamer pushes a new sysmon frame
            const sysmonFrame = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAADklEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
            window.markActiveDeviceFrame(sysmonFrame, null, "sysmon");

            return {
                d1_bound: p1.isBoundTo("sysmon"),
                d1_mode: p1.mode,
                d1_has_frame: p1.frameSrc === sysmonFrame,
                d2_bound: p2.isBoundTo("sysmon"),
                d2_channel: p2.channel,
                d2_mode: p2.mode,
                d2_has_no_frame: p2.frameSrc === null,
            };
        }""", [dev1, dev2])

        assert stream_res["d1_bound"] is True
        assert stream_res["d1_mode"] == "frame"
        assert stream_res["d1_has_frame"] is True

        assert stream_res["d2_bound"] is False
        assert stream_res["d2_channel"] == "clock"
        assert stream_res["d2_mode"] == "glyph"
        assert stream_res["d2_has_no_frame"] is True

        await browser.close()


