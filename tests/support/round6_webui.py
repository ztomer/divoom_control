"""Shared web-UI source aggregates for the split round6 layout test
modules."""
from pathlib import Path


# (support module lives one level deeper than tests/)
REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "divoom_gui" / "web_ui" / "index.html"
GALLERY_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "gallery.css"
GALLERY_JS = REPO_ROOT / "divoom_gui" / "web_ui" / "gallery.js"
GUI_API_PY = REPO_ROOT / "divoom_gui" / "gui_api.py"
LIGHTING_FORWARD_PY = REPO_ROOT / "divoom_gui" / "lighting_forward.py"

def _cat(paths: list[Path]) -> str:
    """Read and concatenate multiple source files."""
    parts = []
    for p in paths:
        if p.exists():
            parts.append(p.read_text())
    return "\n".join(parts)

TEMPLATES_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_tools.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_gallery.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_hot_channel.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_widgets.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_settings.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_routines.js",
    # R40 §8: device settings (clock/temp/power/display/danger) moved here.
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_device_settings.js",
])
ROUTINES_JS = REPO_ROOT / "divoom_gui" / "web_ui" / "templates_routines.js"

SETTINGS_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "settings_hardware.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "settings_features.js",
])

APP_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "app_globals.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "app_init.js",
])

CHANNELS_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "channels_core.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "channels_grids.js",
])
