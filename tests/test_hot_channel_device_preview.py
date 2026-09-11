"""Tests for Hot Channel preview and Device Preview integration."""
import asyncio
import json
from pathlib import Path
import pytest

from tests.support.browser import launch as launch_browser, eval_js, wait_js, add_init_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"
MOCK_GIF_RED = "data:image/gif;base64,R0lGODlhEAAQAPAAAAAAAAAAACH5BAEAAAAALAAAAAAQABAAAAIOhI+py+0Po5y02ouzPgUAOw=="
MOCK_GIF_BLUE = "data:image/gif;base64,R0lGODlhEAAQAPAAAAAAAAAAACH5BAEAAAAALAAAAAAQABAAAAIOhI+py+0Po5y02ouzPgUAOw=="

_MOCK_API = f"""
window.__calls = [];
window.__mock_hot_items = [
    {{ file_id: "group1/M00/1B/EB/hot_red.bin", name: "Red Nebula", version: 10, likes: 450, preview_url: "" }},
    {{ file_id: "group1/M00/1B/EB/hot_blue.bin", name: "Blue Pulse", version: 9, likes: 320, preview_url: "" }}
];
window.pywebview = {{
    api: {{
        switch_channel: async (channel) => {{
            window.__calls.push({{ method: "switch_channel", args: [channel] }});
            return true;
        }},
        hot_update_preview: async () => {{
            window.__calls.push({{ method: "hot_update_preview" }});
            return JSON.stringify({{ success: true, count: 2, items: window.__mock_hot_items }});
        }},
        get_animated_preview: async (fileId) => {{
            window.__calls.push({{ method: "get_animated_preview", fileId }});
            if (fileId.includes("hot_red")) return "{MOCK_GIF_RED}";
            return "{MOCK_GIF_BLUE}";
        }},
        hot_channel_update: async () => {{
            window.__calls.push({{ method: "hot_channel_update" }});
            setTimeout(() => {{
                if (window.Divoom && window.Divoom.onHotProgress) {{
                    window.Divoom.onHotProgress({{
                        type: "hot_progress",
                        phase: "done",
                        progress: 100,
                        result: {{ served: ["hot_red.bin", "hot_blue.bin"], manifest: 2, downloaded: 2 }}
                    }});
                }}
            }}, 100);
            return JSON.stringify({{ success: true, started: true }});
        }},
        hot_get_check: async () => {{
            return JSON.stringify({{ checked_at: Math.floor(Date.now() / 1000), manifest: 2, downloaded: 2, served: 2 }});
        }},
        get_cached_gallery_files: async () => "[]",
        get_device_state: async () => JSON.stringify({{}}),
        get_topology: async () => JSON.stringify({{ screens: [] }}),
        connect_single_device: async (addr) => true,
        set_device_activity: async (mac, kind, name, png) => true
    }}
}};
"""


@pytest.mark.asyncio
async def test_hot_preview_and_device_preview():
    """Verify that hot channel grid loads GIFs and hot update sets device preview."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1200, "height": 850})
        await add_init_js(page, _MOCK_API)
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!window.DivoomState")
        await eval_js(page, "() => { window.DivoomState.appConnected = true; }")

        # Setup 2 devices
        await eval_js(page, """() => {
            window.DivoomState.discoveredDevices = [
                { address: "11:22:33:44:55:01", name: "Timebox-Evo-1", connected: true },
                { address: "11:22:33:44:55:02", name: "Ditoo-Pro-2", connected: true }
            ];
            if (window.connectDevice) {
                window.connectDevice("Timebox-Evo-1", "11:22:33:44:55:01");
            }
        }""")
        await page.wait_for_timeout(300)

        # 1. Hot Channel Grid
        await page.click('.nav-btn[data-tab="pixel-art"]')
        await page.wait_for_timeout(200)
        await page.click('.tab-btn[data-pixel-tab="pixel-hot-channel"]')
        await page.wait_for_timeout(500)

        thumbs = await eval_js(page, """() => {
            const list = document.getElementById("hot-preview-list");
            return list ? Array.from(list.querySelectorAll(".hot-preview-thumb")).map(t => t.src) : [];
        }""")
        assert len(thumbs) == 2
        assert "data:image/gif" in thumbs[0]

        # 2. Hot Update -> Device Preview
        await page.click("#hot-update-btn")
        await page.wait_for_timeout(300)

        act = await eval_js(page, """() => {
            const mac = "11:22:33:44:55:01";
            return window.DivoomState.deviceActivity ? window.DivoomState.deviceActivity[mac] : null;
        }""")
        assert act is not None
        assert act["kind"] == "cloud"
        assert act["src"].startswith("data:image/gif")

        # 3. Device 2 independence
        dev2_act = await eval_js(page, """() => {
            return window.DivoomState.deviceActivity ? window.DivoomState.deviceActivity["11:22:33:44:55:02"] : null;
        }""")
        assert dev2_act is None or dev2_act.get("kind") != "cloud"

        await browser.close()
