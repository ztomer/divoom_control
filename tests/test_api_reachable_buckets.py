"""Three-bucket reachability classification (R71 P1.0).

**Why the gate needed a third bucket.** It asked "does `web_ui/` mention this
name" and reported one number: 20 allowlisted. That conflates two states
needing OPPOSITE fixes -- a method reached only from Python does not belong on
the pywebview bridge surface and should MOVE, while a method reached from
nowhere should GO. One number is why all 20 sat undecided for a round.

**Why AST and not a text scan.** Two gates in this repo were reddened by their
own prose (`check_no_allow`, `check_positional_args`); source text cannot tell
an attribute from a comment quoting one. It cuts the other way too: a text scan
of `batch_sync_artwork` "finds" a caller in `gallery_sync.py` that is a
DOCSTRING, and the allowlist entry asserting "called from Python (gallery_sync)"
was written from exactly that false hit. The method has no production caller.

**The delegation trap, which the first version of this scanner fell into.**
`DivoomGuiAPI.probe_lan` is `return self.connection.probe_lan()`. That inner
attribute access is the method forwarding to its implementation, not a caller
of it -- but it is an `ast.Attribute` named `probe_lan` like any other. Counting
those reported 13 methods as Python-reached when the true figure was 4. The
instrument was confident, repeatable, and measuring the wrong thing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

gate = pytest.importorskip("check_gui_api_reachable")


def _mod(tmp_path: Path, name: str, body: str) -> tuple[Path, ...]:
    pkg = tmp_path / "pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / f"{name}.py").write_text(body)
    return (pkg,)


def test_delegation_is_not_a_caller(tmp_path):
    """The trap: a method forwarding to its own implementation."""
    roots = _mod(tmp_path, "api", (
        "class Api:\n"
        "    def probe_lan(self):\n"
        "        return self.connection.probe_lan()\n"
    ))
    assert gate.python_callers({"probe_lan"}, roots)["probe_lan"] == []


def test_a_real_call_in_another_module_is_found(tmp_path):
    """Updated in P1.3 when the scan narrowed to `self.` bases.

    This used to assert that `api.probe_lan()` on a parameter counted. It no
    longer does, deliberately: DaemonClient mirrors these names, so an
    arbitrary base is ambiguous and `client.live_job_start()` was being read as
    a caller of the BRIDGE method. A test pinning the old behaviour is part of
    that defect, so it moves to the shape that is actually correct.
    """
    roots = _mod(tmp_path, "caller", (
        "class C:\n"
        "    def go(self):\n"
        "        return self.probe_lan()\n"
    ))
    hits = gate.python_callers({"probe_lan"}, roots)["probe_lan"]
    assert len(hits) == 1 and hits[0].endswith(":3")


def test_docstring_mention_is_not_a_caller(tmp_path):
    """The false hit that produced a wrong ALLOWLIST reason.

    `batch_sync_artwork`'s entry says "called from Python (gallery_sync)". The
    only thing in gallery_sync.py is a docstring saying the name.
    """
    roots = _mod(tmp_path, "gallery", (
        "def helper():\n"
        '    """Core of batch_sync_artwork that keeps the failure REASON."""\n'
        "    return None\n"
    ))
    assert gate.python_callers({"batch_sync_artwork"}, roots)["batch_sync_artwork"] == []


def test_comment_mention_is_not_a_caller(tmp_path):
    roots = _mod(tmp_path, "c", "# calls api.probe_lan() eventually\nx = 1\n")
    assert gate.python_callers({"probe_lan"}, roots)["probe_lan"] == []


def test_recursive_only_method_counts_as_dead(tmp_path):
    """Excluded deliberately: calling yourself is not being reached."""
    roots = _mod(tmp_path, "r", (
        "class A:\n"
        "    def loop(self):\n"
        "        return self.loop()\n"
    ))
    assert gate.python_callers({"loop"}, roots)["loop"] == []


def test_unparseable_file_does_not_abort_the_scan(tmp_path):
    """One bad file must not silently truncate the whole classification."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "broken.py").write_text("def (((\n")
    (pkg / "good.py").write_text(
        "class C:\n    def go(self):\n        return self.probe_lan()\n")
    assert len(gate.python_callers({"probe_lan"}, (pkg,))["probe_lan"]) == 1


def test_divoom_lib_is_outside_the_scanned_surface():
    """A reference-only module must not vouch for a live API method."""
    names = {p.name for p in gate.PY_SURFACE}
    assert "divoom_lib" not in names, (
        "divoom_lib is the protocol REFERENCE; counting a call from it would "
        "let obsolete code keep a bridge method alive"
    )
    assert names == {"divoom_gui", "divoom_client"}, names


# ── the web_ui side of the same class (R71 P1.3) ──────────────────────────────
#
# P1.0 stopped a Python DOCSTRING from vouching for a method and left the JS
# side scanning raw text -- half a class fixed. `live_job_start` stayed
# "reachable" on one `//` comment in app_globals.js and nothing else.

def test_js_line_comment_is_not_a_caller():
    blob = gate.strip_comments("// the daemon sets it on live_job_start\n")
    assert "live_job_start" not in blob


def test_js_block_and_html_comments_are_not_callers():
    assert "foo_method" not in gate.strip_comments("/* foo_method */")
    assert "bar_method" not in gate.strip_comments("<!-- bar_method -->")


def test_real_call_survives_stripping():
    src = "window.pywebview?.api?.hot_update_preview?.().then(j => j);\n"
    assert "hot_update_preview" in gate.strip_comments(src)


def test_url_double_slash_does_not_eat_the_rest_of_the_line():
    """Over-stripping would INVENT dead methods -- the expensive mistake."""
    src = 'const u = "https://example.com"; api.set_brightness(5);\n'
    out = gate.strip_comments(src)
    assert "set_brightness" in out, out


def test_known_live_callers_all_survive_the_real_scan():
    """Calibration against the real tree, not a synthetic string.

    If stripping ever gets too aggressive, these five go missing and the gate
    starts reporting live features as dead.
    """
    blob = gate.web_ui_blob()
    for name in ("custom_art_push", "hot_update_preview", "mcp_server_status",
                 "get_notification_listener_status", "live_job_list"):
        assert name in blob, f"{name} lost to comment stripping"


def test_daemon_client_call_is_not_an_api_caller(tmp_path):
    """`client.X()` is the DAEMON's method, not the bridge's.

    DaemonClient mirrors these names by design, so counting any base made both
    live_job wrappers look alive when nothing called either.
    """
    roots = _mod(tmp_path, "media", (
        "def toggle(self):\n"
        "    client = self._client()\n"
        "    return client.live_job_start('AA', 'sysmon', {})\n"
    ))
    assert gate.python_callers({"live_job_start"}, roots)["live_job_start"] == []


def test_self_call_is_an_api_caller(tmp_path):
    roots = _mod(tmp_path, "gal", (
        "class G:\n"
        "    def fetch(self):\n"
        "        return self.load_cached_gallery()\n"
    ))
    assert len(gate.python_callers({"load_cached_gallery"}, roots)["load_cached_gallery"]) == 1
