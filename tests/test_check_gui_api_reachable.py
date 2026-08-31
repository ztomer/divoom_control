"""The reachability gate must bite — this is the one that catches dead features.

R70 P5.0. Coverage cannot see an unreachable method: `toggle_audio_visualizer`
had 100% coverage on a 150-line pyaudio worker nothing could start, and
`push_weather` had four passing tests and no caller. A green suite was the
REASON they survived. Only reachability finds that shape, so this gate needs
the same both-directions proof as the others.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "tools" / "check_gui_api_reachable.py"


def _load():
    spec = importlib.util.spec_from_file_location("_api_reach_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, methods, blob, allowlist) -> int:
    mod.api_methods = lambda: methods
    mod.web_ui_blob = lambda: blob
    mod.ALLOWLIST = allowlist
    return mod.main()


def test_an_unreachable_method_fails():
    mod = _load()
    assert _run(mod, {"orphan"}, "window.pywebview.api.something_else()", {}) == 1


def test_a_reachable_method_passes():
    """Not always-red: without this, the failure above proves nothing."""
    mod = _load()
    assert _run(mod, {"wired"}, "window.pywebview.api.wired()", {}) == 0


def test_an_allowlisted_method_passes():
    mod = _load()
    assert _run(mod, {"orphan"}, "", {"orphan": "unreviewed"}) == 0


def test_a_stale_allowlist_entry_fails():
    """A method that gained a caller must lose its exemption, or the list rots
    into a place where names go to be forgotten."""
    mod = _load()
    assert _run(mod, {"wired"}, "api.wired()", {"wired": "unreviewed"}) == 1


def test_a_deleted_method_takes_its_exemption_with_it():
    """The P5 deletions must shrink this list, not leave holes behind."""
    mod = _load()
    assert _run(mod, set(), "", {"gone": "r70-delete P5.2"}) == 1


def test_word_boundaries_are_respected():
    """`set_clock` must not be counted as reached by `set_clock_rich`."""
    mod = _load()
    assert _run(mod, {"set_clock"}, "api.set_clock_rich()", {}) == 1


# ── the real tree ────────────────────────────────────────────────────────────

def test_the_shipping_tree_passes():
    assert _load().main() == 0


def test_every_allowlist_entry_carries_a_reason():
    mod = _load()
    for name, reason in mod.ALLOWLIST.items():
        assert reason.strip(), f"{name} has no reason"
        assert reason.startswith(("r70-delete", "unreviewed")), (
            f"{name}: {reason!r} must say which kind of decision it is")


def test_the_four_audit_findings_are_marked_for_deletion():
    """The methods R70 actually verified as dead are not filed as 'unreviewed'.

    Recording a confirmed finding as unexamined would lose exactly the work the
    audit did.
    """
    mod = _load()
    for name in ("push_weather", "trigger_notification",
                 "toggle_audio_visualizer", "get_audio_levels"):
        assert mod.ALLOWLIST[name].startswith("r70-delete"), name


def test_control_server_does_not_count_as_a_caller():
    """It dispatches by name from an HTTP request, so counting it would make
    this gate vacuous — and it is a test surface, not a user path."""
    src = GATE.read_text()
    assert "control_server" in src, "the reasoning must stay written down"
    # The gate reads only web_ui/, never the Python control surface.
    assert 'REPO / "divoom_gui" / "web_ui"' in src
