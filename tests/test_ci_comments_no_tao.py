"""P1.3: CI comments no longer describe the menubar's `tao` era.

The menubar moved off `tao`/`tray-icon` to winit + a target-gated `ksni`
(2026-09-20), so comments claiming it needs `tao`/`tray-icon` system packages
no Linux runner ships are stale: they decide what the next person skips. The
comments now name the real dependency (winit/ksni) and state the actual reason
the menubar is macOS-only (Apple-target code, no Linux build), rather than a
system-packages claim that was never proven.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"


def test_workflow_does_not_reference_the_retired_tao_dependency():
    text = WORKFLOW.read_text()
    assert "tao" not in text.lower(), (
        ".github/workflows/tests.yml still references the retired `tao` dependency "
        "in a comment; name the real dependency (winit/ksni) instead"
    )
