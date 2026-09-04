"""
Font consistency guard.

Rule (enforced): ``gui/web_ui/style.css`` is the SINGLE SOURCE OF TRUTH
for all fonts. Every other CSS file, every inline JS style, and the
Google Fonts <link> in index.html must reference one of:

    --font-display  (Outfit)
    --font-sans     (Inter)
    --font-mono     (Inter Mono)

If you add a new font, add it to style.css AND to index.html AND to
this test's ``ALLOWED_FONT_FAMILIES`` allow-list.

This file is the regression net for R14 §5.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


WEB_UI = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui"
STYLE_CSS = WEB_UI / "style.css"
INDEX_HTML = WEB_UI / "index.html"

# These are the only font names allowed anywhere in the GUI.
# The variable form (`var(--font-*)`) is the canonical way to use a font;
# the raw form is allowed only in style.css (the source of truth) and
# in index.html (the Google Fonts request).
ALLOWED_FONT_FAMILIES: set[str] = {
    "Outfit",
    "Inter",
    "Inter Mono",
    # Generic CSS family fallbacks (only allowed inside style.css).
    "sans-serif",
    "ui-monospace",
    "monospace",
}


def _all_css_files() -> list[Path]:
    return sorted(WEB_UI.glob("*.css"))


def _font_family_declarations(css: str) -> list[tuple[int, str]]:
    """Return list of (line_no, font_family_value) for every
    ``font-family: ...;`` declaration in ``css``. We split on ``;`` so
    each declaration is on its own logical line."""
    out: list[tuple[int, str]] = []
    # Use a tolerant regex; multi-line values are joined.
    for m in re.finditer(r"font-family\s*:\s*([^;]+);", css):
        # Line number of the start of the match.
        line_no = css[: m.start()].count("\n") + 1
        out.append((line_no, m.group(1).strip()))
    return out


# ── style.css is the source of truth ──────────────────────────────────


def test_style_css_defines_all_three_font_variables() -> None:
    """``--font-display``, ``--font-sans``, ``--font-mono`` must all
    be defined in style.css."""
    text = STYLE_CSS.read_text()
    for var in ("--font-display", "--font-sans", "--font-mono"):
        assert f"{var}:" in text, f"style.css missing {var} definition"


def test_style_css_font_variables_use_allowed_families() -> None:
    """The font families referenced inside the --font-* variables must
    be in the allow-list."""
    text = STYLE_CSS.read_text()
    for var in ("--font-display", "--font-sans", "--font-mono"):
        m = re.search(rf"{var}\s*:\s*([^;]+);", text)
        assert m, f"{var} not found in style.css"
        value = m.group(1)
        # Split on commas. Each comma-separated token is either a
        # quoted family name ('Outfit', "Inter Mono") or a generic
        # CSS family identifier (sans-serif, ui-monospace, monospace).
        for token in value.split(","):
            t = token.strip().strip("'\"")
            if not t:
                continue
            if t in {"sans-serif", "serif", "ui-monospace", "monospace",
                     "cursive", "fantasy", "system-ui", "inherit"}:
                continue
            assert t in ALLOWED_FONT_FAMILIES, (
                f"{var} references unknown family {t!r}; "
                f"allowed: {sorted(ALLOWED_FONT_FAMILIES)}"
            )


# ── Other CSS files may not use raw font names ────────────────────────


@pytest.mark.parametrize("css_file", _all_css_files())
def test_css_files_use_only_var_font_references(css_file: Path) -> None:
    """Every font-family declaration outside style.css must use a
    ``var(--font-*)`` reference, NOT a raw font name. ``inherit`` is
    also allowed (used by form controls)."""
    if css_file.name == "style.css":
        pytest.skip("style.css is the source of truth; not subject to this rule")
    text = css_file.read_text()
    for line_no, value in _font_family_declarations(text):
        # Allowed forms: var(--font-*) or inherit.
        ok = bool(re.search(r"var\(--font-", value)) or value.strip() == "inherit"
        assert ok, (
            f"{css_file.name}:{line_no}  font-family: {value!r}\n"
            f"Use var(--font-display | --font-sans | --font-mono) instead. "
            f"See the FONT POLICY header in style.css."
        )


# ── JS inline styles use var(--font-*) only ──────────────────────────


def test_js_inline_styles_use_var_font_references() -> None:
    """Inline ``style="font-family: ..."`` in JS files must use a
    ``var(--font-*)`` reference. Empty / no font-family inline styles
    are fine."""
    for js_file in sorted(WEB_UI.glob("*.js")):
        text = js_file.read_text()
        for m in re.finditer(r"font-family\s*:\s*([^;\"']+)", text):
            value = m.group(1).strip()
            ok = bool(re.search(r"var\(--font-", value)) or value == "inherit"
            assert ok, (
                f"{js_file.name}: inline font-family: {value!r}\n"
                f"Use var(--font-display | --font-sans | --font-mono) instead."
            )


# ── index.html Google Fonts request matches style.css ────────────────


def test_index_html_google_fonts_matches_style_css() -> None:
    """The Google Fonts <link> in index.html must request every family
    declared in style.css's --font-* variables. This prevents drift
    (e.g. adding a font to CSS but forgetting to load it)."""
    style = STYLE_CSS.read_text()
    html = INDEX_HTML.read_text()
    for var in ("--font-display", "--font-sans", "--font-mono"):
        m = re.search(rf"{var}\s*:\s*'([^']+)'", style)
        assert m, f"{var} not found in style.css"
        family = m.group(1)
        # Google Fonts CSS uses ``family=Name+With+Plus``.
        # We accept either ``Inter`` or ``Inter+Mono`` style in the URL.
        url_form = family.replace(" ", "+")
        assert url_form in html, (
            f"index.html <link> does not request {family!r} (looking for "
            f"{url_form!r}). Add it to the Google Fonts URL."
        )


# ── Allow-list drift detection ────────────────────────────────────────


def test_allow_list_includes_all_required_families() -> None:
    """If style.css starts using a new family, this test reminds you
    to add it to ALLOWED_FONT_FAMILIES. Caught at lint time."""
    style = STYLE_CSS.read_text()
    used: set[str] = set()
    for m in re.finditer(r"--font-\w+\s*:\s*'([^']+)'", style):
        used.add(m.group(1))
    for family in used:
        assert family in ALLOWED_FONT_FAMILIES, (
            f"style.css uses {family!r} but it's not in "
            f"ALLOWED_FONT_FAMILIES. Add it to the allow-list."
        )
