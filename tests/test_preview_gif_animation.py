"""Defect #2 (2026-09-12): animated GIF previews on the bench must animate.

`DisplayPreview.renderTo` blitted an HTMLImageElement with drawImage, which
never advances a GIF's frames in WebKit, so bench/ribbon/wall previews sat
on frame 0 while the device animated. The canvas now draws the frame for
"now" through `gif_frames.js` (a client-side GIF decoder + player).

The instrument is calibrated in-test: the same assertion is shown to FAIL
on the old drawImage path (player disabled) before it is trusted on the
new one.
"""
import base64
import io
from pathlib import Path

import pytest

from tests.support.browser import eval_js, launch as launch_browser, wait_js

INDEX_HTML = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui" / "index.html"

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _two_frame_gif(size: int = 16, delay_ms: int = 200) -> str:
    """A red frame then a blue frame, as a data URL, like the gallery sends."""
    PIL = pytest.importorskip("PIL.Image")
    frames = [PIL.new("RGB", (size, size), RED), PIL.new("RGB", (size, size), BLUE)]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=delay_ms, loop=0, disposal=1)
    return "data:image/gif;base64," + base64.b64encode(buf.getvalue()).decode()


PROBE_JS = """([src, disablePlayer]) => {
    const disp = window.DisplayPreviewRegistry.get('GIF:TEST');
    if (disablePlayer) disp.gif = null;   // the pre-fix path, for calibration
    disp.setFrame(src);
    const cvs = document.createElement('canvas');
    cvs.width = 16; cvs.height = 16;
    const px = () => {
        disp.renderTo(cvs, 0);
        const d = cvs.getContext('2d').getImageData(8, 8, 1, 1).data;
        return [d[0], d[1], d[2]];
    };
    return new Promise(resolve => {
        // Let the static <img> path load too, so the calibration branch
        // really is "drawImage of a loaded GIF", not "nothing loaded yet".
        setTimeout(() => {
            const start = performance.now();
            if (disp.gif) disp.gif.startedAt = start;
            const first = px();
            setTimeout(() => {
                const second = px();
                resolve({ first, second, decoded: !!(disp.gif && disp.gif.active),
                          frames: disp.gif && disp.gif.anim ? disp.gif.anim.frames.length : 0,
                          total: disp.gif && disp.gif.anim ? disp.gif.anim.total : 0 });
            }, 260);
        }, 150);
    });
}"""


async def _open(p):
    browser = await launch_browser(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 850})
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DisplayPreviewRegistry && !!window.GifFrames")
    return browser, page


@pytest.mark.asyncio
async def test_bench_preview_advances_gif_frames():
    from playwright.async_api import async_playwright

    src = _two_frame_gif()
    async with async_playwright() as p:
        browser, page = await _open(p)
        res = await eval_js(page, PROBE_JS, [src, False])
        assert res["decoded"], "the player did not recognise the GIF"
        assert res["frames"] == 2 and res["total"] == 400, res
        assert tuple(res["first"]) == RED, res
        assert tuple(res["second"]) == BLUE, f"preview did not advance to frame 2: {res}"
        await browser.close()


@pytest.mark.asyncio
async def test_calibration_the_old_drawimage_path_freezes():
    """The assertion above must be able to fail: with the player disabled
    (exactly the pre-fix code path) the same probe reads the same colour
    both times, or reads nothing animated at all."""
    from playwright.async_api import async_playwright

    src = _two_frame_gif()
    async with async_playwright() as p:
        browser, page = await _open(p)
        res = await eval_js(page, PROBE_JS, [src, True])
        assert not res["decoded"]
        assert res["first"] == res["second"], f"old path unexpectedly animated: {res}"
        await browser.close()


@pytest.mark.asyncio
async def test_static_png_and_non_gif_sources_take_the_static_path():
    from playwright.async_api import async_playwright

    PIL = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    PIL.new("RGB", (16, 16), BLUE).save(buf, format="PNG")
    png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    async with async_playwright() as p:
        browser, page = await _open(p)
        res = await eval_js(page, """(src) => {
            const disp = window.DisplayPreviewRegistry.get('PNG:TEST');
            disp.setFrame(src);
            return new Promise(resolve => setTimeout(() => {
                const cvs = document.createElement('canvas'); cvs.width = 16; cvs.height = 16;
                disp.renderTo(cvs, 0);
                const d = cvs.getContext('2d').getImageData(8, 8, 1, 1).data;
                resolve({ decoded: !!(disp.gif && disp.gif.active), px: [d[0], d[1], d[2]],
                          nonGif: window.GifFrames.decode('data:image/png;base64,AAAA') });
            }, 200));
        }""", png)
        assert not res["decoded"], "a PNG must not be treated as an animation"
        assert tuple(res["px"]) == BLUE, res
        assert res["nonGif"] is None
        await browser.close()
