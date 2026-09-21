#!/usr/bin/env python3
"""Generate divoomd/src/commands.rs from divoom_lib.models.COMMANDS
(the authoritative command name -> id map). Re-run when COMMANDS changes:

    PYTHONPATH=<repo root> python3 scripts/codegen/gen_commands.py
"""
from pathlib import Path

from divoom_lib import models


def main():
    cmds = models.COMMANDS
    out = [
        "//! Command name -> protocol id, GENERATED from `divoom_lib.models.COMMANDS`.",
        "//! Do not edit by hand; regenerate via `scripts/codegen/gen_commands.py`.",
        "//! @generated",
        "",
        "/// Every command NAME and its protocol id: data, not a match, so the",
        "/// table is the size of the protocol and no function grows with it.",
        "pub const COMMANDS: &[(&str, u8)] = &[",
    ]
    for name, cid in cmds.items():
        if not isinstance(cid, int) or not (0 <= cid <= 255):
            raise ValueError(f"command {name!r} has non-u8 id {cid!r}")
        # command names are plain lowercase words/spaces; assert no quoting hazard
        if '"' in name or "\\" in name:
            raise ValueError(f"command name needs escaping: {name!r}")
        out.append(f'    ("{name}", 0x{cid:02x}),')
    out += [
        "];",
        "",
        "/// Resolve a command NAME to its protocol id, or `None` if unknown.",
        "#[must_use]",
        "pub fn command_id(name: &str) -> Option<u8> {",
        "    COMMANDS",
        "        .iter()",
        "        .find(|(n, _)| *n == name)",
        "        .map(|(_, id)| *id)",
        "}",
        "",
        "/// Number of known commands (parity check against Python).",
        f"pub const COMMAND_COUNT: usize = {len(cmds)};",
        "",
    ]
    # scripts/codegen/gen_commands.py -> repo root is three parents up (it was two,
    # which pointed at scripts/divoomd/: the generator had not been run since the
    # workspace layout).
    dest = Path(__file__).resolve().parent.parent.parent / "divoomd" / "src" / "commands.rs"
    dest.write_text("\n".join(out))
    print(f"wrote {len(cmds)} commands -> {dest}")


if __name__ == "__main__":
    main()
