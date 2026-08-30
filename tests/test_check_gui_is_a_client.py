"""The R70 gate must be able to FAIL — in every direction that matters.

`tools/check_gui_is_a_client.py` is the structural answer to twelve findings
that all passed a 2935-test suite. That makes it a gate, and an unverified gate
is exactly the defect it was written to close: a checker nobody has watched go
red is a checker nobody knows the subject of.

Four properties, and the last two are the ones usually skipped:

1. it FLAGS a violation that is not allowlisted;
2. it PASSES a clean tree — an always-red gate is as useless as an always-green
   one, and only this direction proves the first result meant anything;
3. it FAILS on a STALE allowlist entry, so a fixed violation cannot leave a
   permanent hole behind for the next one to fall into;
4. it DISCRIMINATES `Image.frombytes` (decoding daemon bytes — the correct
   `sysmon_widget.py` shape) from `Image.new` (building a frame). A gate that
   banned PIL outright could not express that difference and would be worked
   around within a week.

Plus a calibration against the real tree, which is what makes the whole thing
more than a self-test: with an empty allowlist it must find the actual R70
findings, in the actual `divoom_gui/` files the audit named.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "tools" / "check_gui_is_a_client.py"


def _load():
    """A fresh module each time — the tests mutate GUI_DIR and ALLOWLIST."""
    spec = importlib.util.spec_from_file_location("_gui_client_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path, **files: str) -> Path:
    """Write a fake `divoom_gui/` and return it."""
    gui = tmp_path / "divoom_gui"
    gui.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        path = gui / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return gui


def _run(gui_dir: Path, allowlist) -> int:
    mod = _load()
    mod.GUI_DIR = gui_dir
    mod.ALLOWLIST = allowlist
    return mod.main()


# ── 1. it bites ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body, why", [
    ("from divoom_lib.cloud import CloudClient\n", "cloud HTTP in the GUI"),
    ("import bleak\n", "the BLE stack in the GUI process"),
    ("import urllib.request\n", "outbound HTTP in the GUI"),
    ("import pyaudio\n", "audio capture in the GUI"),
    ("from divoom_lib.fonts.bitmap_font import get_default_font\n",
     "a second bitmap font"),
    ("from divoom_lib.utils import media_source\n", "a second widget renderer"),
    ("from PIL import Image\nx = Image.new('RGB', (16, 16))\n",
     "building a frame"),
    ("img = img.resize((16, 16))\n", "resampling that can drift"),
    ("out = font.render('hi')\n", "rasterising text"),
])
def test_flags_a_violation_that_is_not_allowlisted(tmp_path, body, why):
    gui = _tree(tmp_path, **{"panel.py": body})
    assert _run(gui, []) == 1, f"gate did not flag {why}"


# ── 2. it is not always-red ──────────────────────────────────────────────────

def test_passes_a_clean_tree(tmp_path):
    """Without this, a red result above proves nothing at all."""
    gui = _tree(tmp_path, **{"panel.py": (
        "from divoom_client.daemon_client import DaemonClient\n"
        "def get_dial_types(client):\n"
        "    return client.send_command('get_dial_types')\n"
    )})
    assert _run(gui, []) == 0


# ── 3. the ratchet cannot rot ────────────────────────────────────────────────

def test_a_stale_allowlist_entry_fails(tmp_path):
    """The violation is GONE but its exemption stayed.

    This is the property that separates a ratchet from a rug: an entry that
    matches nothing is a hole standing open for the next violation, and it
    reads as "still broken" to anyone auditing the list.
    """
    gui = _tree(tmp_path, **{"panel.py": "x = 1\n"})
    stale = [("panel.py", "import", "divoom_lib.cloud", "R70 P2.1")]
    assert _run(gui, stale) == 1


def test_an_allowlisted_violation_passes(tmp_path):
    gui = _tree(tmp_path, **{"panel.py": "from divoom_lib.cloud import CloudClient\n"})
    entry = [("panel.py", "import", "divoom_lib.cloud", "R70 P2.1")]
    assert _run(gui, entry) == 0


def test_the_allowlist_does_not_excuse_a_DIFFERENT_violation(tmp_path):
    """Allowlisting the cloud import must not also excuse a `bleak` import in
    the same file — otherwise one entry launders a whole file."""
    gui = _tree(tmp_path, **{"panel.py": (
        "from divoom_lib.cloud import CloudClient\n"
        "import bleak\n"
    )})
    entry = [("panel.py", "import", "divoom_lib.cloud", "R70 P2.1")]
    assert _run(gui, entry) == 1


# ── 4. it discriminates decode from construction ─────────────────────────────

def test_frombytes_over_daemon_bytes_is_legal(tmp_path):
    """`sysmon_widget.py`'s shape: the daemon rendered it, the GUI only encodes.

    If this failed, the gate would be telling the project to stop doing the one
    thing R67/C2 established as correct.
    """
    gui = _tree(tmp_path, **{"panel.py": (
        "from PIL import Image\n"
        "def encode(raw, sz, path):\n"
        "    Image.frombytes('RGB', (sz, sz), raw).save(path)\n"
    )})
    assert _run(gui, []) == 0


def test_image_new_is_not_legal(tmp_path):
    gui = _tree(tmp_path, **{"panel.py": (
        "from PIL import Image\n"
        "canvas = Image.new('RGB', (16, 16), (0, 0, 0))\n"
    )})
    assert _run(gui, []) == 1


# ── 5. calibration against the REAL tree ─────────────────────────────────────

# The files the R70 audit named. If the gate stops finding one of these while
# the violation is still there, the gate has gone blind to its own subject.
R70_FINDING_FILES = {
    "aid_sleep.py", "api/lighting.py", "audio_visualizer.py", "clock_faces.py",
    "gallery_download.py", "gallery_hot_api.py", "gallery_sync.py",
    "gui_main.py", "media_sync.py", "photo_albums.py", "playlists.py",
    "weather_city.py",
}


def test_an_empty_allowlist_finds_the_real_R70_findings():
    """The gate's subject is real, not a fixture.

    Run against the shipping tree with NO exemptions, it must name exactly the
    files the audit named — no fewer (it went blind) and no more (it acquired a
    false positive, which is how a gate stops being believed).
    """
    mod = _load()
    hits = set()
    for path in sorted(mod.GUI_DIR.rglob("*.py")):
        if mod.scan_file(path):
            hits.add(path.relative_to(mod.GUI_DIR).as_posix())
    assert hits == R70_FINDING_FILES


def test_the_shipping_tree_passes_with_its_seeded_allowlist():
    """Green today, and with no stale entries — the state each phase shrinks."""
    mod = _load()
    assert mod.main() == 0


def test_every_allowlist_entry_carries_a_reason():
    """An unexplained exemption is how this list rots into a rubber stamp."""
    mod = _load()
    for path, kind, symbol, reason in mod.ALLOWLIST:
        assert reason.strip(), f"{path} {kind} {symbol} has no reason"
        assert "R70" in reason, (
            f"{path} {kind} {symbol}: reason {reason!r} must name the phase "
            f"that removes it")
