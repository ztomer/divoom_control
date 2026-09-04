"""Every id the web UI *reads* must be an id something *defines*.

**R73.** `getElementById` returns `null` for an id that does not exist, and the
codebase's prevailing style is the optional chain -- `document.getElementById(x)
?.checked || false`, `?.value || "#ffffff"`. That is good defensive style and it
is also how this failure hides: rename an id in `index.html` and the reader does
not throw, it quietly yields `false`/`""` forever. The feature is dead and the
console is clean.

That is the same shape as the two methods R73 deleted after taking them to real
hardware -- code that ran without error and did nothing -- so it gets a gate
rather than a habit.

**Written while the tree is clean.** The scan found 0 unresolved ids across
every file in `web_ui/` on 2026-08-31. A parity gate is only cheap to add at
that moment; once there are 91 violations it becomes an allowlist nobody reads.

An id counts as DEFINED if it appears as `id="..."` in any HTML file, or is
built by any JS file (elements are routinely created by one module and read by
another, so definitions are pooled across the whole directory rather than
per-file). Ids assembled from template interpolation (`id="item-${n}"`) are not
readable by a literal `getElementById("...")` call, so they are out of scope in
both directions.
"""
from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "divoom_gui" / "web_ui"

# `id="foo"` in markup.
HTML_ID = re.compile(r'id="([^"${]+)"')
# `id="foo"` / `id='foo'` / escaped forms inside JS strings that build markup,
# plus `el.id = "foo"`. Rejects anything with `${` -- interpolated ids cannot be
# the target of a literal getElementById.
JS_ID = re.compile(r"""\bid\s*=\s*\\?['"]([a-zA-Z][\w-]*)\\?['"]""")
# Only literal lookups; a variable argument is not checkable here.
LOOKUP = re.compile(r'getElementById\(\s*"([^"${]+)"\s*\)')


def _read(pattern: re.Pattern, suffix: str) -> set[str]:
    return {m for p in sorted(UI.rglob(f"*{suffix}"))
            for m in pattern.findall(p.read_text(encoding="utf-8"))}


def defined_ids() -> set[str]:
    return _read(HTML_ID, ".html") | _read(JS_ID, ".js")


def looked_up() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for js in sorted(UI.rglob("*.js")):
        found = set(LOOKUP.findall(js.read_text(encoding="utf-8")))
        if found:
            out[js.name] = found
    return out


def test_no_js_reads_an_element_that_nothing_defines():
    have = defined_ids()
    problems = {name: sorted(ids - have) for name, ids in looked_up().items()
                if ids - have}
    assert not problems, (
        "web_ui JS reads element id(s) that nothing defines:\n"
        + "\n".join(f"  {k}: {v}" for k, v in problems.items())
        + "\ngetElementById returns null here, and the `?.` style in this "
          "codebase turns that into a silent false/empty value rather than an "
          "error -- the control is dead and the console stays clean."
    )


def test_the_clock_rich_controls_are_wired_end_to_end():
    """R73's own wiring, pinned specifically.

    `set_clock_rich` was confirmed on hardware and wired into the clock panel;
    it had sat unreachable in the allowlist for three releases. This asserts the
    full chain -- checkbox in markup, read in JS, API call present -- so it
    cannot silently regress to unreachable again.
    """
    html = (UI / "index.html").read_text(encoding="utf-8")
    js = (UI / "channels_grids.js").read_text(encoding="utf-8")

    for box in ("clock-rich-weather", "clock-rich-date",
                "clock-rich-humidity", "clock-rich-24h"):
        assert f'id="{box}"' in html, f"{box} checkbox missing from index.html"
        assert box in js, f"{box} is defined in markup but nothing reads it"

    assert "set_clock_rich(" in js, "the rich clock API call is gone from the JS"
    assert "set_clock(" in js, (
        "the plain set_clock path disappeared -- with no extras ticked the "
        "behaviour is supposed to be unchanged")


def test_the_scan_actually_finds_things():
    """Calibration: a regex that silently matched nothing would pass the gate
    above vacuously. Both sides must be non-trivial."""
    have = defined_ids()
    reads = looked_up()
    assert len(have) > 100, len(have)
    assert len(reads) > 10, sorted(reads)
    assert sum(len(v) for v in reads.values()) > 100


def test_the_gate_would_catch_a_renamed_id():
    """Prove it can fail: a lookup for an id nothing defines must be flagged."""
    have = defined_ids()
    assert "clock-rich-weather" in have
    assert "clock-rich-weatherr" not in have, "typo-id unexpectedly defined"

