#!/usr/bin/env python3
"""
automated_visual_tester.py — Automated Visual and E2E Navigation Test Runner.
Fires up the PyWebView controller, simulates user tab transitions via JS evaluation,
captures screenshots of the dashboard under test, and logs reports.
"""

import os
import sys
import time
import subprocess
import threading
import tempfile
from pathlib import Path
import json

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))
from divoom_gui.gui_main import DivoomGuiAPI
import webview

def print_info(message):
    print(f"[ ==> ] {message}")

def print_ok(message):
    print(f"[ Ok  ] {message}")

def print_err(message):
    print(f"[ Err ] {message}")

class HeadlessGuiTester:
    def __init__(self):
        self.api = DivoomGuiAPI()
        # Screenshots are large + transient (and may show account/cloud info), so
        # they live in a temp dir — never in the repo. Recreated fresh each run.
        # Override with DIVOOM_TEST_REPORTS if you want them elsewhere.
        import os
        import shutil
        base = Path(os.environ.get("DIVOOM_TEST_REPORTS",
                                   Path(tempfile.gettempdir()) / "divoom_test_reports"))
        self.reports_dir = base
        self.screenshots_dir = base / "screenshots"
        shutil.rmtree(base, ignore_errors=True)   # clean up on every run
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.test_success = True
        self.results = []

    def capture_screenshot(self, name: str):
        """Uses macOS native screencapture to grab a snapshot of the active window area."""
        output_path = self.screenshots_dir / f"{name}.png"
        print_info(f"Visual Test: Capturing UI snapshot to {output_path.name}...")
        try:
            # Retrieve the window ID of the regression tester window via Quartz API
            window_id = ""
            try:
                import Quartz
                window_list = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, 0)
                for window in window_list:
                    win_name = window.get("kCGWindowName", "")
                    win_num = window.get("kCGWindowNumber", "")
                    if "Divoom Visual Regression Tester" in win_name or "Divoom Control Center" in win_name:
                        window_id = str(win_num)
                        break
            except Exception as e:
                print_info(f"Quartz window ID lookup failed: {e}")
            
            if window_id and window_id.isdigit():
                print_info(f"Visual Test: Found window ID {window_id}, capturing single window...")
                # -x: mute sound, -o: no shadow, -l: window ID
                subprocess.run(["screencapture", "-x", "-o", "-l", window_id, str(output_path)], check=True)
            else:
                print_info("Visual Test: Window ID not found, falling back to full monitor capture...")
                subprocess.run(["screencapture", "-x", "-m", str(output_path)], check=True)
                
            print_ok(f"Captured Visual snapshot: {output_path.name}")
            self.results.append({"step": name, "status": "Success", "screenshot": str(output_path.relative_to(Path(__file__).parent.parent))})
        except Exception as e:
            print_err(f"Failed to capture screenshot: {e}")
            self.results.append({"step": name, "status": "Failed", "error": str(e)})

    def run_e2e_cycle(self, window):
        """Clicks through tabs, evaluates visual states, and saves snapshots."""
        try:
            print_info("Visual Test: Starting automated tab cycle...")
            time.sleep(3.0)  # Wait for WKWebView layout engine to stabilize

            # Debug prints
            js_errors = window.evaluate_js('window.__js_errors ? JSON.stringify(window.__js_errors) : "[]"')
            templates_exist = window.evaluate_js('window.DivoomTemplates ? Object.keys(window.DivoomTemplates).join(",") : "none"')
            gallery_html_len = window.evaluate_js('document.getElementById("gallery") ? document.getElementById("gallery").innerHTML.length : "null_elem"')
            load_btn_exists = window.evaluate_js('document.getElementById("load-gallery-btn") ? "yes" : "no"')
            print_info(f"DEBUG E2E: js_errors={js_errors}")
            print_info(f"DEBUG E2E: templates_exist={templates_exist}, gallery_html_len={gallery_html_len}, load_btn_exists={load_btn_exists}")

            # Step 1: Control Center View
            window.evaluate_js('document.querySelector(".nav-btn[data-tab=\'control-panel\']").click();')
            time.sleep(1.0)
            self.capture_screenshot("1_control_center")

            # Step 2: Virtual Wall Arranger View
            window.evaluate_js('document.querySelector(".nav-btn[data-tab=\'display-wall\']").click();')
            time.sleep(1.0)
            self.capture_screenshot("2_virtual_wall")

            # Step 3: Gallery View
            window.evaluate_js('document.querySelector(".nav-btn[data-tab=\'gallery\']").click();')
            time.sleep(1.0)
            
            # Gallery auto-fetches on tab activation — no button click needed
            print_info("E2E Test: Waiting for gallery to auto-fetch...")
            
            # Poll until gallery items are rendered to handle cold caches or slower network/decoding
            print_info("E2E Test: Polling for gallery items to render...")
            max_wait = 25.0
            poll_interval = 0.5
            elapsed = 0.0
            rendered = False
            while elapsed < max_wait:
                count_val = window.evaluate_js('document.querySelectorAll(".gallery-item-preview").length')
                try:
                    count = int(count_val) if count_val is not None else 0
                except (ValueError, TypeError):
                    count = 0
                if count > 0:
                    rendered = True
                    print_info(f"E2E Test: Gallery rendered {count} items after {elapsed:.1f}s.")
                    time.sleep(1.5)  # Short stabilization wait for images to load
                    break
                time.sleep(poll_interval)
                elapsed += poll_interval

            if not rendered:
                raise AssertionError("Timed out waiting for gallery items to render")
            
            # Assert correct previews are rendered
            js_assert = """
            (function() {
                const previews = document.querySelectorAll(".gallery-item-preview");
                if (previews.length === 0) return JSON.stringify({error: "No gallery items rendered at all"});
                const list = [];
                previews.forEach((img, idx) => {
                    list.push({
                        idx: idx,
                        src: img.src,
                        is_mockup: img.src.includes("assets/pixoo.png"),
                        is_badge: img.src.includes("eEwpPWIfSLqEFi3ZAAAAAEVtmrs365"),
                        is_cached: img.src.startsWith("data:image/") || img.src.includes("assets/cache_gallery/")
                    });
                });
                return JSON.stringify({error: null, items: list});
            })()
            """
            assert_res_json = window.evaluate_js(js_assert)
            assert_res = json.loads(assert_res_json)
            
            if assert_res.get("error"):
                raise AssertionError(f"E2E Gallery Assert: {assert_res.get('error')}")
                
            items = assert_res.get("items", [])
            print_info(f"E2E Gallery Assert: Validating {len(items)} rendered previews...")
            for item in items:
                if item["is_mockup"]:
                    raise AssertionError(f"E2E Gallery Assert: Card {item['idx']} shows empty checkerboard grid mockup fallback!")
                if item["is_badge"]:
                    raise AssertionError(f"E2E Gallery Assert: Card {item['idx']} displays duplicate orange 'V' ambassador badge instead of artwork!")
                if not item["is_cached"]:
                    raise AssertionError(f"E2E Gallery Assert: Card {item['idx']} preview URL '{item['src']}' is not fetched/cached locally!")
                    
            print_ok("E2E Gallery Assert: ALL gallery item previews rendered ACTUAL pixel art thumbnails successfully!")
            self.capture_screenshot("3_gallery")

            # Step 4: Live Widgets View
            window.evaluate_js('document.querySelector(".nav-btn[data-tab=\'data-sources\']").click();')
            time.sleep(1.0)
            self.capture_screenshot("4_live_widgets")

            # Step 5: Settings / Devices View
            window.evaluate_js('document.querySelector("[data-tab=\'settings\']").click();')
            time.sleep(1.0)
            self.capture_screenshot("5_settings_devices")

            # Step 6: Settings / Divoom Cloud View
            window.evaluate_js('document.querySelector(".settings-tab-btn[data-settings-tab=\'settings-divoom\']").click();')
            time.sleep(1.0)
            self.capture_screenshot("6_settings_divoom_cloud")

            # Step 7: Settings / Appearance View
            window.evaluate_js('document.querySelector(".settings-tab-btn[data-settings-tab=\'settings-appearance\']").click();')
            time.sleep(1.0)
            self.capture_screenshot("7_settings_appearance")

            print_ok("E2E Visual transitions completed successfully!")
        except Exception as e:
            print_err(f"E2E navigation failed: {e}")
            self.test_success = False
        finally:
            # Terminate testing session
            print_info("Visual Test: Visual test cycles completed, tearing down...")
            time.sleep(1.0)
            window.destroy()

    def start(self):
        web_ui_dir = Path(__file__).parent.parent / "divoom_gui" / "web_ui"
        index_html = web_ui_dir / "index.html"

        # Start visual cycle thread
        url_str = f"{index_html.as_uri()}?t={int(time.time())}"
        window = webview.create_window(
            title="Divoom Visual Regression Tester",
            url=url_str,
            js_api=self.api,
            width=1024,
            height=768,
            resizable=True,
            frameless=True,
            easy_drag=True,
            background_color="#0a0b10"
        )
        self.api.window = window

        # Launch background runner thread
        tester_thread = threading.Thread(target=self.run_e2e_cycle, args=(window,), daemon=True)
        tester_thread.start()

        # Start pywebview loop
        webview.start()
        
        # Write JSON Test outcomes report
        report_file = self.reports_dir / "visual_test_report.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps({
            "test_success": self.test_success,
            "results": self.results,
            "timestamp": time.time()
        }, indent=2), encoding="utf-8")
        print_ok(f"Visual Report saved successfully to {report_file.name}")

if __name__ == "__main__":
    tester = HeadlessGuiTester()
    tester.start()
    if tester.test_success:
        sys.exit(0)
    else:
        sys.exit(1)
