"""P1.2: PyInstaller is pinned from a committed file.

`scripts/build_release.sh` used to build with whatever PyInstaller the
`.buildvenv` held (`pip install ... pyinstaller`, no version), so a clean
venv silently changed the bundle. The build now installs a pinned version
from a committed file, and moving the pin is its own commit carrying a bundle
diff (file list + sizes).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PIN_FILE = REPO / "requirements-build.txt"
SCRIPT = REPO / "scripts" / "build_release.sh"


def test_pin_file_exists_and_pins_pyinstaller():
    assert PIN_FILE.is_file(), "committed PyInstaller pin file is missing"
    text = PIN_FILE.read_text()
    match = re.search(r"^pyinstaller==(\d+\.\d+\.\d+)\s*$", text, re.IGNORECASE | re.MULTILINE)
    assert match is not None, "requirements-build.txt must pin pyinstaller==X.Y.Z (not a bare name)"


def test_build_release_reads_the_pin_file():
    script = SCRIPT.read_text()
    assert "requirements-build.txt" in script, "build_release.sh must name the pin file"
    assert "PYINSTALLER_PIN" in script, "build_release.sh must load the pin into a variable"


def test_build_release_enforces_the_pin():
    script = SCRIPT.read_text()
    # The installed version is compared against the pinned one, so a venv
    # carrying the wrong PyInstaller is refused rather than producing a bundle.
    assert "PyInstaller.__version__" in script, "installed version must be read"
    assert "!=" in script, "installed version must be compared to the pin"
