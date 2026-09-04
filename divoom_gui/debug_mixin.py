"""Debug harness mixin for the pywebview JS api.

`js_log` is exposed to the web UI (window.pywebview.api.js_log). index.html's
early error handler forwards window.onerror / unhandledrejection here so a
blank/broken page is diagnosable even in the PACKAGED app — no WebKit inspector
needed; just read /tmp/divoom-gui-js.log.
"""
import logging

logger = logging.getLogger("divoom_gui")

JS_LOG_PATH = "/tmp/divoom-gui-js.log"


class DebugMixin:
    """Mixed into DivoomGuiAPI; methods here are callable from JS."""

    def js_log(self, message: str) -> bool:
        line = str(message)[:2000]
        try:
            with open(JS_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
        logger.warning("JS: %s", line[:500])
        return True
