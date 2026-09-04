"""Guard: every web_ui/*.js file must parse.

A single JS syntax error (e.g. a stray `});` left by a file split) halts that
whole <script>, so every function it defines silently never registers — which is
exactly how the R23 web_ui split blanked the Clock/EQ/VJ/Ambient channel grids
(2026-06-08 regression). This runs `node --check` on each file. Skipped if node
isn't installed.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

_WEB_UI = Path(__file__).resolve().parents[1] / "divoom_gui" / "web_ui"
_JS = sorted(_WEB_UI.glob("*.js"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("js", _JS, ids=lambda p: p.name)
def test_web_ui_js_parses(js: Path):
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, f"{js.name} has a JS syntax error:\n{r.stderr}"


def test_there_are_js_files():
    assert _JS, "no web_ui/*.js files found — path drift?"
