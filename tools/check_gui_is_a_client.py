#!/usr/bin/env python3
"""check_gui_is_a_client.py — the R70 gate.

**The GUI is a client. It is not a second implementation.**

`divoomd` owns BLE, LAN and cloud; the Python GUI asks it for things and draws
the answers. That rule was already written down (AGENTS.md, and the ROADMAP's
"where the GUI EXECUTES Python that duplicates a daemon job, that IS a real
defect"), enforced by nobody, and violated twelve times — cloud browse in five
panels, gallery HTTP hand-rolled against `appin.divoom-gz.com`, a second stock
renderer, a second bitmap font, a `bleak` import in the one process that must
never own BLE. Every one of them passed a 2935-test suite, because a test that
mocks `CloudClient` PINS the wrong architecture instead of noticing it.

Two rule families, both scoped to `divoom_gui/`:

1. **Forbidden imports** — transports and second implementations. If the GUI
   can `import divoom_lib.cloud`, sooner or later a panel will, because that is
   easier than adding a `daemon_protocol` wrapper. That is the literal history
   of all five cloud panels.

2. **Pixel CONSTRUCTION** — `Image.new`, `Image.open`, `ImageDraw`, `.resize()`,
   `font.render()`. A GUI that builds its own frames is a second renderer, and
   a second renderer drifts: the album-art preview resized LANCZOS while the
   device got NEAREST, under a docstring claiming they shared a path.

   **Decoding is not constructing.** `Image.frombytes(...)` over raw daemon RGB
   is the CORRECT shape (`divoom_gui/sysmon_widget.py`) and stays legal. A gate
   that banned PIL outright would have no way to express that difference, and
   would be worked around within a week.

**The allowlist is a RATCHET, not an exemption list.** It is seeded with exactly
the violations present when this gate was written; each R70 phase deletes the
entries it earned; the class is closed when it is EMPTY. Two properties make it
a ratchet rather than a rug:

* a violation NOT on the list fails, so no new ones can be added; and
* an entry that no longer MATCHES anything also fails, so a fixed violation
  cannot leave a permanent hole behind for the next one to slip through.

The second is the one that is easy to omit and is why stale allowlists rot into
rubber stamps.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GUI_DIR = REPO / "divoom_gui"

# ── rule 1: imports the GUI must not have ────────────────────────────────────
#
# Matched against the dotted module path, prefix-wise: "divoom_lib.cloud" also
# catches "divoom_lib.cloud.something". Each entry says what the GUI should do
# INSTEAD, because a gate that only says "no" gets worked around.
FORBIDDEN_IMPORTS: dict[str, str] = {
    "bleak": "the GUI must never link BLE — divoomd owns the radio",
    "pyaudio": "audio capture belongs in the daemon, if anywhere",
    "psutil": "ask the daemon: `sysmon`",
    "numpy": "signal processing is not the UI's job",
    "urllib.request": "ask the daemon; it owns every outbound HTTP call",
    "requests": "ask the daemon; it owns every outbound HTTP call",
    "httpx": "ask the daemon; it owns every outbound HTTP call",
    "divoom_lib.cloud": "ask the daemon: get_dial_types, get_my_playlists, ...",
    "divoom_lib.divoom": "device access goes through DaemonDeviceProxy",
    "divoom_lib.wall": "wall access goes through DaemonDeviceProxy(target='wall')",
    "divoom_lib.fonts": "ask the daemon to render text — it has the same font",
    "divoom_lib.tools.hot_update": "ask the daemon: hot_update / its manifest",
    "divoom_lib.utils.media_source": "ask the daemon: render_widget",
    "divoom_lib.media_decoder": "ask the daemon: get_animated_preview",
}

# ── rule 2: calls that CONSTRUCT pixels ──────────────────────────────────────
#
# `Image.frombytes` is the one legal `Image` call: it wraps bytes the daemon
# already rendered. Everything else on `Image` builds or decodes a picture the
# GUI then treats as its own.
IMAGE_ALLOWED_ATTRS = {"frombytes"}

# Bare method names that resample or rasterise. In `divoom_gui/` these have
# exactly one meaning; if a legitimate `.render()` ever appears the allowlist
# takes it WITH A REASON, which is the review this deserves.
FORBIDDEN_METHODS = {
    "resize": "resampling in the GUI drifts from the daemon's filter",
    "render": "text rasterising belongs to the daemon's BitmapFont",
}

FORBIDDEN_MODULE_ATTRS = {"ImageDraw", "ImageFont"}

# ── the ratchet ──────────────────────────────────────────────────────────────
#
# (relative path, kind, symbol, why it is still here / which phase removes it)
# `kind` is "import" or "call".
ALLOWLIST: list[tuple[str, str, str, str]] = [
    # R70 P2 — cloud browse moves to the daemon.
    #   (P2 DONE: the five CloudClient panels, the gallery HTTP and the
    #    hot-channel manifest+preview are all daemon calls now.)
    # R70 P3 — the renderers move to the daemon.
    # P3.1 removed the stock renderer; the ONLY remaining user is
    # trigger_notification, which no JS calls and which P5.4 deletes.
    ("media_sync.py", "import", "divoom_lib.utils.media_source", "R70 P5.4"),
    ("api/lighting.py", "import", "divoom_lib.fonts", "R70 P3.3"),
    ("api/lighting.py", "call", "Image.new", "R70 P3.3"),
    ("api/lighting.py", "call", "resize", "R70 P3.3"),
    ("api/lighting.py", "call", "render", "R70 P3.3"),
    # R70 P5 — dead weight deleted.
    ("gui_main.py", "import", "bleak", "R70 P5.1"),
    ("gui_main.py", "import", "divoom_lib.divoom", "R70 P5.1"),
    ("gui_main.py", "import", "divoom_lib.wall", "R70 P5.1"),
    ("audio_visualizer.py", "import", "pyaudio", "R70 P5.2"),
    ("audio_visualizer.py", "import", "numpy", "R70 P5.2"),
]


def _module_names(node: ast.AST) -> list[str]:
    """Dotted module paths an import statement brings in.

    `from divoom_lib.utils import media_source` must resolve to
    `divoom_lib.utils.media_source`, not `divoom_lib.utils` — the GUI imports
    it exactly that way, and matching only the package would either miss it or
    ban every sibling.
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:  # relative import: not one of ours
            return []
        return [base] + [f"{base}.{a.name}" for a in node.names]
    return []


def _forbidden_import(dotted: str) -> tuple[str, str] | None:
    """Longest matching prefix, so `divoom_lib.cloud` wins over a broader rule."""
    best: tuple[str, str] | None = None
    for mod, why in FORBIDDEN_IMPORTS.items():
        if dotted == mod or dotted.startswith(mod + "."):
            if best is None or len(mod) > len(best[0]):
                best = (mod, why)
    return best


def scan_file(path: Path) -> list[tuple[str, str, str]]:
    """(kind, symbol, detail) violations in one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [("parse", str(path), f"could not parse: {exc}")]

    found: list[tuple[str, str, str]] = []
    # `from divoom_lib.cloud import CloudClient` yields BOTH `divoom_lib.cloud`
    # and `divoom_lib.cloud.CloudClient`, and the prefix rule matches both — one
    # import, reported twice, which inflates the count and makes the list read
    # as worse than it is. Deduplicate on (kind, symbol, line).
    seen: set[tuple[str, str, int]] = set()

    def add(kind: str, symbol: str, lineno: int, detail: str) -> None:
        if (kind, symbol, lineno) in seen:
            return
        seen.add((kind, symbol, lineno))
        found.append((kind, symbol, f"line {lineno}: {detail}"))

    for node in ast.walk(tree):
        for dotted in _module_names(node):
            hit = _forbidden_import(dotted)
            if hit:
                mod, why = hit
                add("import", mod, node.lineno, why)

        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_MODULE_ATTRS:
            add("call", node.attr, node.lineno,
                "drawing surfaces belong to the daemon")

        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute):
            continue
        # `Image.<attr>(...)` — construction unless it is the decode shape.
        if isinstance(fn.value, ast.Name) and fn.value.id == "Image":
            if fn.attr not in IMAGE_ALLOWED_ATTRS:
                add("call", f"Image.{fn.attr}", node.lineno,
                    "the GUI must not build frames; only Image.frombytes over "
                    "daemon bytes is a decode")
            continue
        if fn.attr in FORBIDDEN_METHODS:
            add("call", fn.attr, node.lineno, FORBIDDEN_METHODS[fn.attr])
    return found


def main() -> int:
    if not GUI_DIR.is_dir():
        err(f"[gui-client] {GUI_DIR} does not exist")
        return 1

    allowed = {(p, k, s) for p, k, s, _ in ALLOWLIST}
    used: set[tuple[str, str, str]] = set()
    offenders: list[str] = []
    scanned = 0

    for path in sorted(GUI_DIR.rglob("*.py")):
        rel = path.relative_to(GUI_DIR).as_posix()
        scanned += 1
        for kind, symbol, detail in scan_file(path):
            key = (rel, kind, symbol)
            if key in allowed:
                used.add(key)
                continue
            offenders.append(f"divoom_gui/{rel} — {kind} `{symbol}` — {detail}")

    # A fixed violation must take its allowlist entry with it. An entry that
    # matches nothing is a hole standing open for the next violation to fall
    # into, and it reads as "still broken" to anyone auditing the list.
    stale = sorted(allowed - used)
    if stale:
        err(f"[gui-client] {len(stale)} stale allowlist entr(ies) — the code was "
            f"fixed but the exemption stayed")
        for rel, kind, symbol in stale:
            info(f"divoom_gui/{rel} — {kind} `{symbol}` no longer occurs; "
                 f"delete it from ALLOWLIST")
        return 1

    if offenders:
        err(f"[gui-client] {len(offenders)} violation(s) — the GUI is doing the "
            f"daemon's work")
        for o in offenders:
            info(o)
        info("The GUI is a client. Ask divoomd; do not reimplement it.")
        return 1

    remaining = len(ALLOWLIST)
    if remaining:
        ok(f"[gui-client] OK — {scanned} files, no new violations "
           f"({remaining} allowlisted, R70 in progress)")
    else:
        ok(f"[gui-client] OK — {scanned} files, allowlist EMPTY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
