#!/usr/bin/env python3
"""Generate the divoomd command model from divoom_lib.models.COMMANDS
(the authoritative command name -> id map). Re-run when COMMANDS changes:

    PYTHONPATH=<repo root> python3 scripts/codegen/gen_commands.py
    cargo fmt -p divoomd

Three artefacts come out of one source, which is the point:

* `commands.rs`      — the name -> id table, unchanged, for string-keyed callers.
* `command_model.rs` — the same protocol as a TYPE: `Command`, one variant per
                       protocol ID, with `ALL` and the total conversions.
* `command_names.rs` — the name <-> command indexes both of those read.

The model is ID-FIRST because the protocol is: 109 names map to 105 ids, and
four ids carry two names each (`set light pic`/`set image`, `set animation
frame`/`set light phone gif`, `set light mode`/`set channel light`, `set
temp`/`send current temp`). A variant per NAME would give four pairs of
variants with equal discriminants, and then `TryFrom<u8>` could not be total --
two spellings, one answer, and the conversion would have to pick a winner in
the dark. One variant per ID, with the second spelling as `#[doc(alias)]`, keeps
`u8 -> Command` exact and keeps every name spellable (rust-analyzer resolves the
alias; `COMMAND_NAMES` resolves it at runtime).

Three files, not one, because of the repo's 500-line cap -- split at the seams
that mean something (the table callers use today, the type that replaces it, the
indexes both read), not to hit a number. The cap is a design gate: each of the
three is separately readable, and one 760-line generated file is not.

Every accessor is table-driven, deliberately: an arm per command is a function
that grows with the protocol, which is the thing these files exist to avoid.
clippy caught exactly that twice while this was being written.

`tests/test_command_model_parity.py` checks all three against Python in both
directions, so this file being the only writer is a convenience, not the
guarantee.
"""

import keyword
import subprocess
import sys
from pathlib import Path

from divoom_lib import models

# Rust keywords are all lower-case and variants are CamelCase, so a collision
# would need a command named e.g. "self". Asserted rather than assumed: the
# failure mode is a file that does not compile, discovered by cargo.
RESERVED = {"Self", "self", "crate", "super"}

HEADER = [
    "GENERATED from `divoom_lib.models.COMMANDS`.",
    "Do not edit by hand; regenerate via `scripts/codegen/gen_commands.py`.",
    "//! @generated",
]


def variant_name(command: str) -> str:
    """`set volume` -> `SetVolume`. The spelling both sides contract to."""
    if not command or not command[0].isalpha():
        raise ValueError(f"command name cannot start a Rust variant: {command!r}")
    if keyword.iskeyword(command):
        raise ValueError(f"command name is a Python keyword: {command!r}")
    variant = "".join(word.capitalize() for word in command.split())
    if variant in RESERVED:
        raise ValueError(f"command name collides with a reserved path: {command!r}")
    return variant


def id_first(cmds: dict) -> dict:
    """`{variant: (id, [names])}` — ONE variant per id, first name owning it.

    Keyed by id, not by spelling: four ids carry two names each, and giving
    each name its own variant would leave four pairs of variants with equal
    discriminants, so `TryFrom<u8>` could not be total — two spellings, one
    answer, and the conversion would pick a winner in the dark. The variant
    takes the FIRST name in table order and the rest ride as `#[doc(alias)]`.
    """
    out: dict[str, tuple] = {}
    by_id: dict[int, str] = {}
    for name, cid in cmds.items():
        if not isinstance(cid, int) or not 0 <= cid <= 255:
            raise ValueError(f"command {name!r} has non-u8 id {cid!r}")
        if '"' in name or "\\" in name:
            raise ValueError(f"command name needs escaping: {name!r}")
        variant = variant_name(name)
        owner = by_id.get(cid)
        if owner is None:
            by_id[cid] = variant
            out[variant] = (cid, [name])
            continue
        if owner == variant:
            raise ValueError(f"command {name!r} repeats a spelling already in the table")
        out[owner] = (out[owner][0], [*out[owner][1], name])
    return out


def emit_table(cmds: dict, model: dict) -> list:
    out = [
        f"//! Command name -> protocol id, {HEADER[0]}",
        f"//! {HEADER[1]}",
        HEADER[2],
        "",
        "/// Every command NAME and its protocol id: data, not a match, so the",
        "/// table is the size of the protocol and no function grows with it.",
        "pub const COMMANDS: &[(&str, u8)] = &[",
    ]
    for name, cid in cmds.items():
        out.append(f'    ("{name}", 0x{cid:02x}),')
    out += [
        "];",
        "",
        "/// Number of known command NAMES, checked by",
        "/// `tests/test_command_model_parity.py` against `len(COMMANDS)`.",
        f"pub const COMMAND_COUNT: usize = {len(cmds)};",
        "",
        "/// Number of distinct protocol ids, which is fewer than the name count:",
        "/// four ids are spelled two ways.",
        f"pub const COMMAND_ID_COUNT: usize = {len(model)};",
        "",
        "// The name lookups moved to `command_names` when the model was split out",
        "// (they need the type), and they are RE-EXPORTED here rather than",
        "// moved: `commands::command_id` was this crate's public spelling and an",
        "// integration test imports it. Both paths now route through the enum, so",
        "// a name and its id cannot come from different sources.",
        "pub use crate::command_names::{command, command_id};",
        "",
    ]
    return out


def emit_model(model: dict) -> list:
    out = [
        f"//! The command model as a TYPE, {HEADER[0]}",
        f"//! {HEADER[1]}",
        HEADER[2],
        "",
        "use crate::command_names::CANONICAL_NAMES;",
        "",
        "/// Every command as a TYPE: one variant per protocol id.",
        "///",
        "/// The protocol is id-first — 109 names, 105 ids, four ids with two",
        "/// names each — so the enum is too, and the second spelling is a",
        "/// `#[doc(alias)]`. A `match` over it is exhaustive: a command the",
        "/// protocol adds is a compile error at every dispatch site instead of a",
        "/// runtime `None` nobody reads.",
        "#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]",
        "#[repr(u8)]",
        "pub enum Command {",
    ]
    for variant, (cid, names) in model.items():
        for alias in names[1:]:
            out.append(f'    #[doc(alias = "{alias}")]')
        spelled = " / ".join(f"`{n}`" for n in names)
        out.append(f"    /// {spelled}")
        out.append(f"    {variant} = 0x{cid:02x},")
    out += [
        "}",
        "",
        "impl Command {",
        "    /// The protocol id this command is sent as.",
        "    #[must_use]",
        "    pub const fn id(self) -> u8 {",
        "        self as u8",
        "    }",
        "",
        "    /// The canonical name, as the Python table spells it.",
        "    ///",
        "    /// A lookup in the table rather than a `match`: one arm per command",
        "    /// is a function the size of the protocol, which is what the table",
        "    /// already is. Aliases are not returned -- they resolve to the same",
        "    /// command, and a command has one canonical spelling.",
        "    #[must_use]",
        "    pub fn name(self) -> &'static str {",
        "        CANONICAL_NAMES",
        "            .iter()",
        "            .find(|(_, cmd)| *cmd == self)",
        "            .map_or(\"\", |(name, _)| *name)",
        "    }",
        "}",
        "",
        "/// Every command, in protocol-table order. Iteration and exhaustive",
        "/// tests start here rather than from a range of ids.",
        "pub const ALL: &[Command] = &[",
    ]
    for variant in model:
        out.append(f"    Command::{variant},")
    out += [
        "];",
        "",
        "impl TryFrom<u8> for Command {",
        "    type Error = u8;",
        "",
        "    /// Total in the sense that matters: every id this crate can name",
        "    /// resolves, and an id outside the protocol is the error, not a",
        "    /// silent default. (`as u8` on a `u16` off the wire would invent one,",
        "    /// which is how a truncation becomes a command the device never",
        "    /// receives.)",
        "    ///",
        "    /// A scan of `ALL`, not a `match` with an arm per id, for the reason",
        "    /// `name()` gives. 105 comparisons of a `u8` is not a cost worth a",
        "    /// jump table's correctness risk.",
        "    fn try_from(value: u8) -> Result<Self, Self::Error> {",
        "        ALL.iter()",
        "            .find(|cmd| cmd.id() == value)",
        "            .copied()",
        "            .ok_or(value)",
        "    }",
        "}",
        "",
        "impl TryFrom<&str> for Command {",
        "    type Error = &'static str;",
        "",
        "    fn try_from(value: &str) -> Result<Self, Self::Error> {",
        "        crate::command_names::command(value).ok_or(\"unknown divoom command name\")",
        "    }",
        "}",
        "",
        "// The tests live in a sibling file: they are hand-written and these three",
        "// are generated, so a test module in here would be erased by the next",
        "// regeneration -- a test that stops running without ever failing.",
        "#[cfg(test)]",
        '#[path = "command_model_tests.rs"]',
        "mod tests;",
        "",
    ]
    return out


def emit_names(model: dict) -> list:
    out = [
        f"//! Name <-> command indexes, {HEADER[0]}",
        f"//! {HEADER[1]}",
        HEADER[2],
        "",
        "use crate::command_model::Command;",
        "",
        "/// One entry per command: the canonical name and the command it names.",
        "/// The same table `Command::name` reads, exposed so a caller can walk",
        "/// names and commands together without going through the aliases.",
        "pub const CANONICAL_NAMES: &[(&str, Command)] = &[",
    ]
    for variant, (_cid, names) in model.items():
        out.append(f'    ("{names[0]}", Command::{variant}),')
    out += [
        "];",
        "",
        "/// Every command NAME with the command it resolves to, aliases included.",
        "/// The name -> command direction is a scan, not a match, because the",
        "/// ids repeat and a match on them would silently drop three names.",
        "pub const COMMAND_NAMES: &[(&str, Command)] = &[",
    ]
    for variant, (_cid, names) in model.items():
        for name in names:
            out.append(f'    ("{name}", Command::{variant}),')
    out += [
        "];",
        "",
        "/// Resolve a command NAME to the command it is, or `None` if unknown.",
        "#[must_use]",
        "pub fn command(name: &str) -> Option<Command> {",
        "    COMMAND_NAMES",
        "        .iter()",
        "        .find(|(n, _)| *n == name)",
        "        .map(|(_, cmd)| *cmd)",
        "}",
        "",
        "/// Resolve a command NAME to its protocol id, or `None` if unknown.",
        "///",
        "/// The pre-L2 spelling, kept because callers hold it: it now routes",
        "/// through the type rather than the table, so a name and its id cannot",
        "/// come from different sources.",
        "#[must_use]",
        "pub fn command_id(name: &str) -> Option<u8> {",
        "    command(name).map(Command::id)",
        "}",
        "",
    ]
    return out


def main():
    model = id_first(models.COMMANDS)
    # scripts/codegen/gen_commands.py -> repo root is three parents up (it was two,
    # which pointed at scripts/divoomd/: the generator had not been run since the
    # workspace layout).
    src = Path(__file__).resolve().parent.parent.parent / "divoomd" / "src"
    artefacts = (
        ("commands.rs", emit_table(models.COMMANDS, model)),
        ("command_model.rs", emit_model(model)),
        ("command_names.rs", emit_names(model)),
    )
    for filename, lines in artefacts:
        (src / filename).write_text("\n".join(lines))

    # Format what we just wrote, in the crate, before saying we are done.
    #
    # The emitted text is not rustfmt-clean (a 105-arm enum and a 109-entry
    # table both have lines that want wrapping), so regenerating without this
    # left the tree failing `cargo fmt --all -- --check` — which is the gate the
    # repo runs. "Regenerate" is a documented single command; it has to leave a
    # tree that passes, or everyone learns to run two and then forget the second.
    formatted = subprocess.run(
        ["cargo", "fmt", "-p", "divoomd"],
        cwd=src.parent.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if formatted.returncode != 0:
        print(f"warning: cargo fmt did not run: {formatted.stderr.strip()}", file=sys.stderr)
    print(
        f"wrote {len(models.COMMANDS)} commands / {len(model)} ids -> "
        + " ".join(name for name, _ in artefacts)
    )


if __name__ == "__main__":
    main()
