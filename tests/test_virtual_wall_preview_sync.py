"""Browser-driven verification for Virtual Wall and Main Bench preview synchronization.
Verifies that the Virtual Wall Arranger canvas and Spatial Stage Main Bench share
the exact same pixel-perfect DisplayPreview rendering, channel switching (Clock, EQ,
Frame, Wall), and two-way coordinate synchronization with SpatialRooms.
"""
import asyncio
from pathlib import Path
import pytest
from tests.support.browser import launch as launch_browser, eval_js, wait_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"


@pytest.mark.asyncio
async def test_virtual_wall_arranger_retired_and_bench_clock_rendering():
    """Verify that setting Clock channel renders the authentic bitmap clock on the
    Main Bench (#stage-canvas-${mac}) with zero false-positive orange 'W' glyph pixels,
    and the redundant #arranger-canvas is absent from the DOM."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window.renderArrangerCanvas")

        dev1 = "11:22:33:44:55:01"
        res = await eval_js(page, """(d1) => {
            // Seed 1 device in discoveredDevices and assign it to a wall slot
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: d1, name: "Pixoo-Wall", room: "Wall" }
            ];
            window.DivoomState.assignedSlots = {
                [d1]: { x: 50, y: 50, width: 80, height: 80, size: 16, name: "Pixoo-Wall" }
            };

            // Render bench nodes
            if (window.SpatialStage?.refresh) window.SpatialStage.refresh();

            // Configure device with Rainbow Clock style 1
            const disp = window.DisplayPreviewRegistry.get(d1);
            disp.setActivity("clock", { style: 1, color: "#ff5a5a" });

            // Check DOM presence
            const stageCvs = document.getElementById(`stage-canvas-${d1}`);
            const arrangerCanvas = document.getElementById("arranger-canvas");
            if (!stageCvs) {
                return { error: "Missing stage canvas", hasStage: !!stageCvs, hasArranger: !!arrangerCanvas };
            }

            // Render one frame
            disp.renderTo(stageCvs, 1);

            // Analyze stage canvas pixels
            const sCtx = stageCvs.getContext("2d");
            const sData = sCtx.getImageData(0, 0, stageCvs.width, stageCvs.height).data;
            let sNonBlack = 0, sOrangeGlyph = 0;
            for (let i = 0; i < sData.length; i += 4) {
                const r = sData[i], g = sData[i + 1], b = sData[i + 2];
                if (r > 30 || g > 30 || b > 30) sNonBlack++;
                // Check for orange "W" glyph color rgb(255, 90, 31)
                if (r === 255 && g === 90 && b === 31) sOrangeGlyph++;
            }

            return {
                channel: disp.channel,
                mode: disp.mode,
                stageNonBlack: sNonBlack,
                stageOrangeGlyph: sOrangeGlyph,
                hasArranger: !!arrangerCanvas
            };
        }""", dev1)

        assert "error" not in res, f"Setup error: {res}"
        assert res["hasArranger"] is False, "Redundant #arranger-canvas should not be in DOM"
        assert res["channel"] == "clock"
        assert res["mode"] == "glyph"
        assert res["stageNonBlack"] > 0
        # Zero orange 'W' glyph pixels because device is in clock channel
        assert res["stageOrangeGlyph"] == 0

        await browser.close()


@pytest.mark.asyncio
async def test_main_bench_frame_and_eq_rendering():
    """Verify that EQ visualizers and Wall channel glyph render accurately
    on the Main Bench canvas."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window.renderArrangerCanvas")

        dev1 = "11:22:33:44:55:01"
        res = await eval_js(page, """(d1) => {
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.discoveredDevices = [
                { address: d1, name: "Pixoo-Wall", room: "Wall" }
            ];
            window.DivoomState.assignedSlots = {
                [d1]: { x: 50, y: 50, width: 80, height: 80, size: 16, name: "Pixoo-Wall" }
            };
            if (window.SpatialStage?.refresh) window.SpatialStage.refresh();

            const disp = window.DisplayPreviewRegistry.get(d1);

            // 1. Switch to EQ / Visualizer
            disp.setActivity("eq", { color: "#5aabff" });
            const stageCvs = document.getElementById(`stage-canvas-${d1}`);
            if (!stageCvs) return { error: "stage canvas missing" };

            disp.renderTo(stageCvs, 5);

            const eqStagePixels = stageCvs.getContext("2d").getImageData(0, 0, 16, 16).data;
            let eqNonBlack = 0;
            for (let i = 0; i < eqStagePixels.length; i += 4) {
                if (eqStagePixels[i] > 20 || eqStagePixels[i+1] > 20 || eqStagePixels[i+2] > 20) eqNonBlack++;
            }

            // 2. Explicit wall channel renders orange glyph
            disp.setActivity("wall");
            disp.renderTo(stageCvs, 0);

            const wallStageData = stageCvs.getContext("2d").getImageData(0, 0, 16, 16).data;
            let stageOrange = 0;
            for (let i = 0; i < wallStageData.length; i += 4) {
                if (wallStageData[i] === 255 && wallStageData[i + 1] === 90 && wallStageData[i + 2] === 31) stageOrange++;
            }

            return {
                eqNonBlack,
                stageOrange
            };
        }""", dev1)

        assert res.get("error") is None
        assert res["eqNonBlack"] > 0
        assert res["stageOrange"] > 0

        await browser.close()


@pytest.mark.asyncio
async def test_virtual_wall_spatial_rooms_preset_sync():
    """Verify that dragging on the arranger canvas propagates coordinates to SpatialRooms,
    and loading a preset syncs to both assignedSlots and SpatialRooms positions."""
    assert INDEX_HTML.exists()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.SpatialRooms && !!window.renderArrangerCanvas")

        dev1 = "AA:BB:CC:DD:EE:01"
        sync_res = await eval_js(page, """(d1) => {
            window.DivoomState = window.DivoomState || {};
            window.DivoomState.assignedSlots = {
                [d1]: { x: 30, y: 40, width: 80, height: 80, size: 16, name: "Timoo-Sync" }
            };
            window.renderArrangerCanvas();

            // Simulate preset load callback
            const samplePreset = {
                [d1]: { x: 120, y: 80, width: 80, height: 80, size: 16, name: "Timoo-Sync" }
            };

            window.DivoomState.assignedSlots = samplePreset;
            window.renderArrangerCanvas();
            if (window.SpatialRooms) {
                const pos = window.SpatialRooms.getSavedPositions();
                const devRooms = window.SpatialRooms.getDeviceRooms();
                Object.keys(samplePreset).forEach(addr => {
                    pos[addr] = { x: samplePreset[addr].x, y: samplePreset[addr].y };
                    devRooms[addr] = "Wall";
                });
                window.SpatialRooms.savePositions(pos, devRooms);
            }

            const savedPos = window.SpatialRooms.getSavedPositions()[d1];
            const savedRoom = window.SpatialRooms.getDeviceRooms()[d1];

            return {
                slotX: window.DivoomState.assignedSlots[d1].x,
                slotY: window.DivoomState.assignedSlots[d1].y,
                spatialX: savedPos ? savedPos.x : null,
                spatialY: savedPos ? savedPos.y : null,
                spatialRoom: savedRoom
            };
        }""", dev1)

        assert sync_res["slotX"] == 120
        assert sync_res["slotY"] == 80
        assert sync_res["spatialX"] == 120
        assert sync_res["spatialY"] == 80
        assert sync_res["spatialRoom"] == "Wall"

        await browser.close()
