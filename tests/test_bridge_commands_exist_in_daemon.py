"""Every call the GUI makes to the daemon is one the daemon answers (P6.5).

After a wall push the GUI asked the wall for `get_last_previews`. The Rust
wall never had it -- the port from the Python wall dropped it -- so the call
was refused `unsupported`, logged as a warning, and the bench's per-panel
previews were empty from the day of the port. The GUI tests stayed green
because their fake daemon answered `get_last_previews` itself. A fake that
answers a command the daemon does not have is a green light bolted over a
missing feature; this holds every name the GUI sends, and every name a test
fake answers, to the daemon's own tables:

* the socket commands: `COMMAND_ARGS` in `divoomd/src/command_args.rs`, which
  the daemon holds to its dispatcher (P5.9);
* a panel's `device_call` methods: `ROUTES` in
  `divoomd/src/device_call/routing.rs`, and the `lan.*` arms of
  `divoomd/src/device_call/lan.rs`;
* the wall's `device_call` methods: `WALL_METHODS` in
  `divoomd/src/wall/dispatch.rs`, held to its arms by that file's test.

What the GUI sends is read two ways: the literal command names in the client
and GUI source, and what EVERY public bridge method actually sends when called
on a panel and on the wall (`tests/support/bridge_calls.py`).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.support.bridge_calls import (
    A, NOT_CALLED, WALL, args_for, call, public_methods, recorded_api,
)

ROOT = Path(__file__).resolve().parent.parent
RUST = ROOT / "divoomd" / "src"


def _block(path: Path, const: str) -> str:
    src = path.read_text(encoding="utf-8")
    start = src.index(f"const {const}:")
    return src[start:src.index("\n];", start)]


def socket_commands() -> set[str]:
    rows = _block(RUST / "command_args.rs", "COMMAND_ARGS")
    return set(re.findall(r'\(\s*"([a-z0-9_]+)",\s*&\[', rows))


def panel_methods() -> set[str]:
    routes = set(re.findall(r'"([a-z0-9_.]+)"', _block(RUST / "device_call" / "routing.rs", "ROUTES")))
    lan = (RUST / "device_call" / "lan.rs").read_text(encoding="utf-8")
    return routes | set(re.findall(r'"(lan\.[a-z0-9_]+)"\s*(?:=>|\|)', lan))


def wall_methods() -> set[str]:
    return set(re.findall(r'"([a-z0-9_]+)"', _block(RUST / "wall" / "dispatch.rs", "WALL_METHODS")))


def _bare(method: str) -> str:
    """The name the wall's dispatcher matches: a dotted path's last segment."""
    return method.rsplit(".", 1)[-1]


def test_the_tables_are_read():
    """Calibration: each walk finds its table, so an empty set never passes."""
    assert {"device_call", "wall_configure", "live_job_start"} <= socket_commands()
    assert {"display.show_image", "lan.set_brightness"} <= panel_methods()
    assert {"show_image", "set_brightness"} <= wall_methods()


# ── the literal command names in the client and the GUI ──────────────────

#: Client calls whose first argument is a socket command's name.
SENDERS = {"send_command", "cloud_call", "make_request"}


def _sent_literals() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pkg in ("divoom_client", "divoom_gui"):
        for path in (ROOT / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                first = node.args[0]
                if name in SENDERS and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    where = f"{path.relative_to(ROOT)}:{node.lineno}"
                    out.setdefault(first.value, []).append(where)
    return out


def test_every_socket_command_the_client_sends_is_one_the_daemon_answers():
    sent = _sent_literals()
    assert len(sent) > 30, f"the source walk found the senders: {sorted(sent)}"
    unknown = {cmd: where for cmd, where in sent.items() if cmd not in socket_commands()}
    assert unknown == {}, f"sent, and no COMMAND_ARGS row answers them: {unknown}"


# ── what every bridge method sends, on a panel and on the wall ────────────

@pytest.fixture
def api(tmp_path):
    with recorded_api(tmp_path) as gui:
        gui.wall_slots = {A: {"x": 0, "y": 0, "size": 16},
                          "BB:00:00:00:00:02": {"x": 1, "y": 0, "size": 16}}
        yield gui


METHODS = [m for m in public_methods() if m[0] not in NOT_CALLED]

#: Bridge methods that forward a method their CALLER names, checked on a panel
#: only: on the wall the name would be this test's choice, not the GUI's.
PASSTHROUGH = {
    "device_call": "forwards its caller's method; its one caller, the custom-art "
                   "page switch (web_ui/custom_art.js), never names the wall",
}


def _sends(api, name, fn, panel) -> list[tuple[str, str]]:
    call(api, name, args_for(fn, panel))
    daemon = api._daemon_client
    assert not daemon.missing, f"{name}({panel}) called DaemonClient.{sorted(daemon.missing)}, which does not exist"
    return [(kw["target"], kw["method"]) for r, kw in daemon.requests if r == "device_call"]


@pytest.mark.parametrize("name,fn", METHODS, ids=[m[0] for m in METHODS])
def test_every_device_call_a_bridge_method_makes_is_answered(api, name, fn):
    """Called on a panel and on the wall, each `device_call` it makes names a
    method the daemon routes for that target."""
    panel, wall = panel_methods(), wall_methods()
    unanswered = []
    for target in ((A,) if name in PASSTHROUGH else (A, WALL)):
        for kind, method in _sends(api, name, fn, target):
            known = _bare(method) in wall if kind == "wall" else method in panel
            if not known:
                unanswered.append(f"{kind} {method}")
    assert unanswered == [], f"{name} asks the daemon for {unanswered}, which it does not answer"


# ── what the tests' fakes answer ──────────────────────────────────────────

#: A fake keyed on a device_call method name, or on a socket command name.
_FAKE_METHOD = re.compile(r"\bmethod\s*(?:==\s*|in\s*[(\[{])\s*((?:[\"'][a-z0-9_.]+[\"']\s*,?\s*)+)")
_FAKE_COMMAND = re.compile(r"\b(?:cmd|command)\s*(?:==\s*|in\s*[(\[{])\s*((?:[\"'][a-z0-9_]+[\"']\s*,?\s*)+)")
_NAME = re.compile(r"[\"']([a-z0-9_.]+)[\"']")


def _faked(pattern) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in (ROOT / "tests").rglob("*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            for name in _NAME.findall(m.group(1)):
                out.setdefault(name, []).append(f"{path.relative_to(ROOT)}:{line}")
    return out


def test_no_test_fake_answers_a_device_call_the_daemon_does_not_have():
    known = panel_methods() | wall_methods()
    faked = _faked(_FAKE_METHOD)
    assert faked, "the scan finds the fakes keyed on a method"
    unknown = {m: where for m, where in faked.items() if m not in known and _bare(m) not in wall_methods()}
    assert unknown == {}, f"test fakes answer device_call methods the daemon has not got: {unknown}"


def test_no_test_fake_answers_a_socket_command_the_daemon_does_not_have():
    faked = _faked(_FAKE_COMMAND)
    assert faked, "the scan finds the fakes keyed on a command"
    unknown = {c: where for c, where in faked.items() if c not in socket_commands()}
    assert unknown == {}, f"test fakes answer socket commands the daemon has not got: {unknown}"
