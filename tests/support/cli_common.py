"""Shared helpers for the split cli_commands test modules."""
from divoom_lib import cli as cli_module


def _parse(*argv: str):
    return cli_module.build_parser().parse_args(list(argv))
