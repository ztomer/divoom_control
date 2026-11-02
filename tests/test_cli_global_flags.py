"""A global flag reaches EVERY subcommand, before or after it (D.CLIMAC).

`divoom-control --mac X select` failed with "--mac is required": the shared
flags were attached to the top-level parser AND to each subparser, and a
subparser writes ITS defaults over the namespace -- so a flag given before
the subcommand was silently reset to None by the subcommand that should have
read it. The class is every shared flag on every subcommand, so this test
walks the parser itself rather than a list someone has to keep current.
"""
from __future__ import annotations

import argparse

import pytest

from divoom_lib.cli import build_parser

#: Each shared flag, the argv that sets it, and the value it must produce.
FLAGS = {
    "mac": (["--mac", "AA:BB:CC:DD:EE:FF"], "AA:BB:CC:DD:EE:FF"),
    "socket": (["--socket", "/tmp/dev.sock"], "/tmp/dev.sock"),
    "timeout": (["--timeout", "3.5"], 3.5),
    "device_type": (["--type", "TivooMax"], "TivooMax"),
    "json": (["--json"], True),
    "verbose": (["--verbose"], True),
}
#: The value each flag holds when it is NOT given, in either position.
DEFAULTS = {"mac": None, "socket": None, "timeout": 10.0, "device_type": None,
            "json": False, "verbose": False}

SAMPLE = {int: "1", float: "1.0"}


def _subcommands() -> dict[str, argparse.ArgumentParser]:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(sub.choices)


def _positionals(sub: argparse.ArgumentParser) -> list[str]:
    """Dummy values for a subcommand's required positionals."""
    out = []
    for action in sub._actions:
        if action.option_strings or isinstance(action, argparse._HelpAction):
            continue
        out.append("12:00" if action.dest == "time" else SAMPLE.get(action.type, "x"))
    return out


COMMANDS = sorted(_subcommands())


def test_the_walk_sees_every_subcommand():
    assert {"select", "capabilities", "set-volume", "preview", "pair"} <= set(COMMANDS)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("flag", sorted(FLAGS))
def test_a_global_flag_reaches_the_subcommand_before_or_after_it(command, flag):
    argv_flag, want = FLAGS[flag]
    rest = _positionals(_subcommands()[command])
    before = build_parser().parse_args([*argv_flag, command, *rest])
    after = build_parser().parse_args([command, *rest, *argv_flag])
    assert getattr(before, flag) == want, f"`{' '.join(argv_flag)} {command}` lost {flag}"
    assert getattr(after, flag) == want, f"`{command} {' '.join(argv_flag)}` lost {flag}"


@pytest.mark.parametrize("command", COMMANDS)
def test_an_absent_flag_keeps_its_default(command):
    args = build_parser().parse_args([command, *_positionals(_subcommands()[command])])
    for flag, default in DEFAULTS.items():
        assert getattr(args, flag) == default, f"{command}: {flag}"
