"""P7.2 — the connection dot's states, told apart WITHOUT colour.

The dot in the app's lower-right corner (``#global-status-dot``) is the only
thing that says what the app's link is doing. Before P7.2 it was ONE circle
whose only carrier was colour: BLE / LAN / Wall differed by hue alone, and
"connecting" and "degraded" differed by pulse PERIOD alone. Measured in
greyscale and static (the tray's own metric), every pair of live states
differed by 0 px — one channel doing all the work, and failing the repo's own
P7.1 gate applied to the web surface.

This is that gate, for the web surface: it renders the REAL states in the REAL
page (the real cascade, the real funnel), with the motion DISABLED — a pulsing
dot is not reproducible: two screenshots of the same pulsing dot 180 ms apart
differ in 400 of 400 px — converts them to greyscale, and asserts that every
pair differs by at least 5% of the MARK'S OWN square.

Three things make it a gate and not a description:

  * it drives ``window.setConnectionState`` — the funnel, the one writer — so
    it measures what the product writes, not a class name a test invented;
  * it reads the pixels back out of the browser, because a CSS-text assertion
    cannot see a shape, and a canvas reimplementation would be a parallel
    renderer (the lesson ``tools/render_tray_icon.py`` was rewritten for);
  * a CALIBRATION test proves the gate goes RED when two states share a look.
    A gate that has never been seen to fail is not known to be a gate.

The metric is the tray's own (``divoom-menubar/src/glyph.rs:210``): a luma
step of 64, and a floor of 5% of the mark's square — 400 device px at 2x for a
10 CSS px dot, so 20 device px.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from tests.support.browser import (
    add_init_js,
    eval_js,
    launch as launch_browser,
    require_browser,
    wait_js,
)

INDEX_HTML = Path(__file__).parent.parent / "divoom_gui" / "web_ui" / "index.html"

#: The tray's luma step (divoom-menubar/src/glyph.rs:156): below this two
#: greys are the same grey.
VISIBLE = 64

#: The floor: 5% of the mark's OWN square. The dot is 10 CSS px, so at 2x its
#: square is 20x20 = 400 device px, and 5% of that is 20 device px.
FLOOR = (20 * 20) // 20

#: A permissive mock daemon API, exactly as the sibling dot suites use it.
MOCK_API = """
window.__api = {};
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (window.__api && typeof window.__api[name] === 'function')
        return Promise.resolve(window.__api[name](...args));
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true);
}})};
"""

#: The six live states, as the FUNNEL is told about them — not as class
#: names. The test drives the real ``window.setConnectionState`` and reads
#: back the class it wrote, so the vocabulary under test is the product's.
STATES = (
    ("disconnected", {"mode": "inactive"}),
    ("connecting", {"mode": "connecting", "mac": "AA:BB:CC:DD:EE:FF"}),
    ("linked · Bluetooth", {"mode": "active", "mac": "AA:BB:CC:DD:EE:FF"}),
    ("linked · Wi-Fi", {"mode": "active", "mac": "LAN:10.0.0.5"}),
    ("linked · Virtual Wall", {"mode": "active", "mac": "MatrixWall"}),
    ("degraded", {"mode": "degraded", "mac": "AA:BB:CC:DD:EE:FF"}),
)

#: What the funnel must write for each state. The shape class is the
#: transport and the fill class is the link — one class string, two axes.
EXPECTED_CLASS = {
    "disconnected": "transport-mark mark-ble mark-open",
    "connecting": "transport-mark mark-ble mark-pending",
    "linked · Bluetooth": "transport-mark mark-ble mark-linked",
    "linked · Wi-Fi": "transport-mark mark-lan mark-linked",
    "linked · Virtual Wall": "transport-mark mark-wall mark-linked",
    "degraded": "transport-mark mark-ble mark-fault",
}

#: Motion off. The pulse is the one thing in the mark that a still frame
#: cannot hold, and the fill is what this gate measures.
NO_MOTION_CSS = (
    "*, *::before, *::after { animation: none !important; transition: none !important; }"
)


def _luma(png: bytes) -> list[list[float]]:
    """The screenshot's greyscale luma, row by row."""
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    return [
        [
            0.2126 * r + 0.7152 * g + 0.0722 * b
            for (r, g, b) in (img.getpixel((x, y)) for x in range(img.width))
        ]
        for y in range(img.height)
    ]


def _differing(a: list[list[float]], b: list[list[float]]) -> int:
    """Pixels the eye would call different: the tray's metric, unchanged."""
    return sum(
        1
        for row_a, row_b in zip(a, b)
        for pa, pb in zip(row_a, row_b)
        if abs(pa - pb) >= VISIBLE
    )


def _ink(rows: list[list[float]], backdrop: list[list[float]]) -> int:
    """Pixels that stand out from the backdrop by the tray's step."""
    return sum(
        1
        for row, brow in zip(rows, backdrop)
        for px, pb in zip(row, brow)
        if abs(px - pb) >= VISIBLE
    )


def _assert_pairs_distinct(rendered: dict[str, list[list[float]]]) -> None:
    """The gate itself: every pair of states must differ by the floor."""
    names = list(rendered)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            n = _differing(rendered[a], rendered[b])
            assert n >= FLOOR, (
                f"{a} and {b} differ in only {n} px in greyscale "
                f"(the floor is {FLOOR} — 5% of the mark's own square at 2x)"
            )


async def _open(p):
    """The real page, at 2x, with the motion off."""
    browser = await launch_browser(p)
    context = await browser.new_context(device_scale_factor=2)
    page = await context.new_page()
    await add_init_js(page, MOCK_API)
    await page.goto(f"file://{INDEX_HTML}")
    await page.wait_for_load_state("domcontentloaded")
    await wait_js(page, "() => !!window.DivoomState && !!window.setConnectionState")
    await eval_js(page, """(css) => {
        const style = document.createElement('style');
        style.id = 'no-motion';
        style.textContent = css;
        document.head.appendChild(style);
        window.DivoomState.discoveredDevices = [];
        return true;
    }""", NO_MOTION_CSS)
    return browser, page


async def _shoot(page) -> list[list[float]]:
    """The dot's pixels, as the browser rendered them."""
    raw = await page.locator("#global-status-dot").screenshot()
    return _luma(raw)


async def _render_states(page) -> dict[str, list[list[float]]]:
    """Render every state through the funnel; return {name: greyscale}."""
    rendered: dict[str, list[list[float]]] = {}
    for name, args in STATES:
        await eval_js(page, "() => window.setConnectionState(%s)" % json.dumps(args))
        cls = await eval_js(
            page, "() => document.getElementById('global-status-dot').className"
        )
        assert cls == EXPECTED_CLASS[name], (
            f"{name}: the funnel wrote {cls!r}, expected {EXPECTED_CLASS[name]!r}"
        )
        rendered[name] = await _shoot(page)
    return rendered


async def _backdrop(page) -> list[list[float]]:
    """The page behind the dot — what an "ink" is measured against.

    The dot is made transparent rather than hidden: a hidden element has no
    box to screenshot, and the box is exactly what the backdrop is read from.
    """
    await eval_js(page, """() => {
        const style = document.createElement('style');
        style.id = 'hide-dot';
        style.textContent = '#global-status-dot { opacity: 0 !important; }';
        document.head.appendChild(style);
        return true;
    }""")
    rows = await _shoot(page)
    await eval_js(page, """() => {
        const s = document.getElementById('hide-dot');
        if (s) s.remove();
        return true;
    }""")
    return rows


@pytest.mark.asyncio
async def test_the_key_teaches_the_vocabulary_in_settings_devices():
    """The KEY: three silhouettes do not teach themselves.

    The key lives in Settings -> Devices and uses the SAME classes the dot
    uses, so it cannot drift from it -- there is one vocabulary, not a legend
    of its own. This also pins that the key is ON SCREEN: a key in a
    stylesheet teaches nobody.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page()
        await add_init_js(page, MOCK_API)
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")
        await wait_js(page, "() => !!document.querySelector('.transport-key')")
        key = await eval_js(page, """() => {
            const items = Array.from(
                document.querySelectorAll('.transport-key .transport-key-item'));
            return {
                labels: items.map(i => i.textContent.trim()),
                classes: items.map(i => {
                    const m = i.querySelector('.transport-mark');
                    return m ? m.className : null;
                }),
            };
        }""")
        assert len(key["classes"]) == 3, key
        assert key["classes"] == [
            "transport-mark mark-ble mark-linked",
            "transport-mark mark-lan mark-linked",
            "transport-mark mark-wall mark-linked",
        ], key
        # Each mark sits beside the name it teaches.
        for label, cls in zip(key["labels"], key["classes"]):
            assert label, key
            assert cls.split()[1] in ("mark-ble", "mark-lan", "mark-wall")
        assert "Bluetooth" in key["labels"][0]
        assert "Wi-Fi" in key["labels"][1]
        assert "Virtual Wall" in key["labels"][2]
        await browser.close()


@pytest.mark.asyncio
async def test_every_pair_of_dot_states_differs_in_greyscale():
    """The P7.2 gate: no two states may share a look once colour is gone."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            rendered = await _render_states(page)
            _assert_pairs_distinct(rendered)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_disconnected_mark_differs_from_a_full_strength_hollow_in_ink():
    """Disconnected is a DIM hollow; a connect in flight is a FULL one.

    They are the same shape on purpose — the shape carries the transport, and
    the fill carries the link — so what separates them is the ink. The rule
    is that the dimmed mark must differ in the AMOUNT of ink, not merely in
    the ratio of one tone to another: a reader (or a screen) must be able to
    tell "no link" from "a connect is in flight" with the motion gone.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            rendered = await _render_states(page)
            backdrop = await _backdrop(page)
            ink_open = _ink(rendered["disconnected"], backdrop)
            ink_pending = _ink(rendered["connecting"], backdrop)
            assert ink_pending - ink_open >= FLOOR, (
                "the dimmed Disconnected mark and the full-strength hollow of a "
                f"connect in flight differ in only {ink_pending - ink_open} px of ink "
                f"(the floor is {FLOOR}): {ink_open} against {ink_pending}"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_gate_goes_red_when_two_states_share_a_look():
    """The calibration: a gate that has never failed is not known to be a gate.

    Two DIFFERENT states are forced to carry the same mark, and the gate must
    notice. The forcing happens on the real page, through the real class
    string, so this proves the gate bites on the product's own rendering and
    not merely on a synthetic duplicate.
    """
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p)
        try:
            rendered = await _render_states(page)
            # The Wi-Fi state now wears the Bluetooth mark: two different
            # states, one look.
            await eval_js(page, """() => {
                const d = document.getElementById('global-status-dot');
                d.className = 'transport-mark mark-ble mark-linked';
                return true;
            }""")
            rendered["linked · Wi-Fi"] = await _shoot(page)
            with pytest.raises(AssertionError):
                _assert_pairs_distinct(rendered)
        finally:
            await browser.close()
