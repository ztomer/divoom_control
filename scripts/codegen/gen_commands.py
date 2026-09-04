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
        "//! Command name -> protocol id, GENERATED from divoom_lib.models.COMMANDS.",
        "//! Do not edit by hand; regenerate via scripts/codegen/gen_commands.py.",
        "",
        "/// Resolve a command NAME to its protocol id, or `None` if unknown.",
        "pub fn command_id(name: &str) -> Option<u8> {",
        "    match name {",
    ]
    for name, cid in cmds.items():
        if not isinstance(cid, int) or not (0 <= cid <= 255):
            raise ValueError(f"command {name!r} has non-u8 id {cid!r}")
        # command names are plain lowercase words/spaces; assert no quoting hazard
        if '"' in name or "\\" in name:
            raise ValueError(f"command name needs escaping: {name!r}")
        out.append(f'        "{name}" => Some(0x{cid:02x}),')
    out += [
        "        _ => None,",
        "    }",
        "}",
        "",
        "/// Number of known commands (parity check against Python).",
        f"pub const COMMAND_COUNT: usize = {len(cmds)};",
        "",
    ]
    dest = Path(__file__).parent.parent / "divoomd" / "src" / "commands.rs"
    dest.write_text("\n".join(out))
    print(f"wrote {len(cmds)} commands -> {dest}")


if __name__ == "__main__":
    main()
