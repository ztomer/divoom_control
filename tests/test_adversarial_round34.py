"""R53 round 34 — persona pass (Bob+Linus CONVERGED on the mcp NameError).

- mcp_tools.get_capabilities referenced `dataclasses` with no module-level import →
  NameError for a real Divoom (whose Capabilities dataclass has no to_dict).

(Hashimoto's notification-monitor health-error test lived here too, but it
depends on the archived divoom_daemon.notification_service server module and
moved to archive/tests/ (removed in R66; in git history) test_adversarial_round34.py.)
"""
import asyncio
import dataclasses
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))


# ── Bob+Linus: get_capabilities dataclass fallback ──────────────────────────

def test_get_capabilities_handles_real_dataclass_without_to_dict():
    from divoom_lib.mcp_tools import _make_handlers

    @dataclasses.dataclass
    class _Caps:
        size: int = 16
        model: str = "Pixoo"

    class _Divoom:
        capabilities = _Caps()

    handlers = _make_handlers(_Divoom())
    res = asyncio.run(handlers["get_capabilities"]())
    assert res == {"size": 16, "model": "Pixoo"}, "real-device dataclass fallback must work, not NameError"
