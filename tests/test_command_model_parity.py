"""L2: the command model is a TYPE on both sides, and the two cannot drift.

`divoom_lib/models/commands.py` holds 109 command NAMES mapped to 105 protocol
ids (four ids carry two names each -- `set light pic`/`set image` and friends).
THREE Rust files are GENERATED from it -- `commands.rs` (the table callers use
today), `command_model.rs` (the `Command` type) and `command_names.rs` (the
indexes between them), split at the 500-line cap -- which is the right
arrangement, except that until this gate existed the generated `COMMAND_COUNT`
was read by nobody. A codegen that writes a constant no test consults is a comment with
syntax: delete a command from Python, forget to re-run the generator, and both
sides keep reporting success while the daemon answers a name the phone no longer
sends.

So this pins the model from BOTH ends:

* every Python name is a Rust variant, and every Rust variant is a Python name --
  an extra variant is as fatal as a missing one, because an id nobody sends is a
  lie the type system would then enforce;
* every id is the Python id, and an id with two names keeps BOTH (the alias is
  the protocol's, not a typo);
* `COMMAND_COUNT` is `len(COMMANDS)`, so the generated count is checked rather
  than emitted;
* the crate carries no `as u16` cast. A command id is a `u8` that came from a
  `u16` field somewhere in the decompiled protocol; `as u16` is how a truncation
  becomes a silently wrong device command, and the typed model is what makes the
  conversion a checked one instead.

Proven red-once: this file was written before the enum existed and failed on all
109 names, and it fails again the moment one variant is deleted from the
generator's output.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import models  # noqa: E402

REPO = Path(__file__).parent.parent
SRC = REPO / "divoomd" / "src"
# Three generated files, not one: the repo's 500-line cap is a design gate and a
# 760-line generated file is not one thing. The table callers use today, the
# type that replaces it, and the indexes both read.
COMMANDS_RS = SRC / "commands.rs"
MODEL_RS = SRC / "command_model.rs"
NAMES_RS = SRC / "command_names.rs"
DAEMON_SRC = SRC
GENERATED = (COMMANDS_RS, MODEL_RS, NAMES_RS)

# A variant line: `    SetVolume = 0x08,` possibly with a doc comment above.
VARIANT = re.compile(r"^    (?P<name>[A-Z][A-Za-z0-9]*) = 0x(?P<id>[0-9a-f]{2}),$", re.MULTILINE)
COUNT_CONST = re.compile(r"pub const COMMAND_COUNT: usize = (?P<n>\d+);")
COUNT_CONST_ID = re.compile(r"pub const COMMAND_ID_COUNT: usize = (?P<n>\d+);")


def _significant(source: str) -> str:
    """Rustfmt's footprint removed, so formatting is never mistaken for drift.

    Two normalisations, both pure formatting:

    * whitespace outside string literals — the command names' spaces are data
      ("set volume" is one name), but `COMMANDS\n.iter()` and
      `COMMANDS.iter()` are the same code;
    * a comma directly before a closing delimiter — rustfmt adds one when it
      wraps a long tuple across lines, and the generator's single-line form has
      none. Same tuple either way.

    Order and ids are NOT normalised: a reordered table is a real diff.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for char in source:
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            out.append(char)
            continue
        if not char.isspace():
            out.append(char)
    collapsed = "".join(out)
    return re.sub(r",(?=[\)\]\}])", "", collapsed)


def rust_variants() -> dict[str, int]:
    """`{variant: id}` for every enum variant the generated model declares."""
    return {
        m.group("name"): int(m.group("id"), 16)
        for m in VARIANT.finditer(MODEL_RS.read_text())
    }


def variant_name(command: str) -> str:
    """The Rust variant a command name generates, per `gen_commands.py`.

    Duplicated here on purpose: a test that imports the generator's own helper
    proves only that the helper agrees with itself. This is the spelling the
    generator is CONTRACTED to emit, so a change to either side has to be a
    deliberate change to both.
    """
    return "".join(word.capitalize() for word in command.split())


def expected_variants() -> dict[str, int]:
    """The variant set the Python table demands: ONE per id, first name wins.

    First-wins because that is the generator's documented contract, and the
    table is an insertion-ordered dict, so "first" is stable rather than
    arbitrary. A second name for the same id is an ALIAS, checked separately.
    """
    out: dict[str, int] = {}
    for name, cid in models.COMMANDS.items():
        out.setdefault(variant_name(name), cid)
    return out


def test_the_rust_command_model_exists() -> None:
    # Without this the rest of the file would compare two empty sets and pass,
    # which is the failure mode of a checker over an absent subject.
    assert VARIANT.search(MODEL_RS.read_text()), (
        f"{MODEL_RS.name} declares no command variants: the typed model the "
        "L2 phase exists to add is not there"
    )


def test_every_python_command_is_spellable_in_rust() -> None:
    """Every NAME resolves — as a variant, or as an alias of one."""
    source = NAMES_RS.read_text() + MODEL_RS.read_text()
    variants = rust_variants()
    unspellable = {
        name: variant_name(name)
        for name in models.COMMANDS
        if variant_name(name) not in variants
        and f'alias = "{name}"' not in source
    }
    assert not unspellable, f"commands with no Rust spelling: {unspellable}"


def test_one_variant_per_id_not_one_per_name() -> None:
    """The model is id-first, and that is a count, not a convention.

    109 names, 105 ids. One variant per NAME would leave four pairs with equal
    discriminants, so `TryFrom<u8>` could not be total — two spellings, one
    answer, and the conversion picks a winner in the dark. So the variant count
    must equal the DISTINCT id count, and every id must appear once.
    """
    variants = rust_variants()
    distinct_ids = {cid for cid in models.COMMANDS.values()}
    assert len(variants) == len(distinct_ids), (
        f"{len(variants)} variants for {len(distinct_ids)} distinct ids: "
        "the model is spelled per name instead of per id"
    )
    assert set(variants.values()) == distinct_ids, (
        f"ids in Rust but not Python: {sorted(set(variants.values()) - distinct_ids)}; "
        f"ids in Python but not Rust: {sorted(distinct_ids - set(variants.values()))}"
    )


def test_no_rust_variant_without_a_python_command() -> None:
    extra = sorted(set(rust_variants()) - set(expected_variants()))
    assert not extra, f"Rust variants no Python command backs: {extra}"


def test_every_variant_carries_the_python_id() -> None:
    want = expected_variants()
    wrong = {
        name: (got, want[name])
        for name, got in rust_variants().items()
        if name in want and got != want[name]
    }
    assert not wrong, f"variants whose id disagrees with Python: {wrong}"


def test_the_aliased_ids_keep_both_names() -> None:
    # Four ids carry two names each. The type is id-first, so the alias has to
    # live somewhere or the second name becomes unspellable in Rust -- and an
    # unspellable name is one the daemon stops accepting.
    aliased: dict[int, list[str]] = {}
    for name, cid in models.COMMANDS.items():
        aliased.setdefault(cid, []).append(name)
    multi = {cid: names for cid, names in aliased.items() if len(names) > 1}
    assert multi, "the Python table no longer has an aliased id: the alias test is now vacuous"
    source = NAMES_RS.read_text() + MODEL_RS.read_text()
    for cid, names in multi.items():
        for name in names:
            variant = variant_name(name)
            # Either its own variant, or documented as an alias of the one that
            # owns the id.
            assert re.search(
                rf"^    {variant} = 0x{cid:02x},$|alias = \"{re.escape(name)}\"",
                source,
                re.MULTILINE,
            ), f"no Rust spelling for {name!r} (id 0x{cid:02x})"


def test_command_count_is_the_python_count() -> None:
    # The generated constant nobody read, now read.
    found = COUNT_CONST.search(COMMANDS_RS.read_text())
    assert found, "COMMAND_COUNT is gone: the generated count is unchecked again"
    assert int(found.group("n")) == len(models.COMMANDS), (
        f"COMMAND_COUNT says {found.group('n')}, Python has {len(models.COMMANDS)}: "
        "re-run scripts/codegen/gen_commands.py"
    )
    ids_found = COUNT_CONST_ID.search(COMMANDS_RS.read_text())
    assert ids_found, "COMMAND_ID_COUNT is gone: the variant count is unchecked"
    assert int(ids_found.group("n")) == len({cid for cid in models.COMMANDS.values()}), (
        f"COMMAND_ID_COUNT says {ids_found.group('n')}, Python has "
        f"{len({cid for cid in models.COMMANDS.values()})} distinct ids"
    )


def test_no_as_u16_casts_in_the_daemon() -> None:
    # A command id is a u8 off the wire; `as u16` is how a truncation turns
    # into a command the device never receives, silently.
    offenders = {}
    for path in sorted(DAEMON_SRC.rglob("*.rs")):
        hits = [
            f"{path.relative_to(REPO)}:{n}"
            for n, line in enumerate(path.read_text().splitlines(), 1)
            if re.search(r"\bas\s+u16\b", line)
        ]
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"`as u16` casts: {offenders}"


def test_the_codegen_output_is_current() -> None:
    """Re-running the generator must change nothing that means anything.

    Whitespace is normalised out, deliberately. The committed file is
    `cargo fmt`-clean -- the gate runs `cargo fmt --check` -- while the
    generator emits unformatted code, so a byte comparison would report "stale"
    on a formatting difference alone. A gate that cries wolf over rustfmt gets
    ignored, and the next real drift goes with it. Order and ids are NOT
    normalised: a reordered table is a real diff a human should see.
    """
    import os
    import subprocess

    before = {path.name: _significant(path.read_text()) for path in GENERATED}
    subprocess.run(
        [sys.executable, "scripts/codegen/gen_commands.py"],
        cwd=REPO,
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    stale = [
        path.name
        for path in GENERATED
        if _significant(path.read_text()) != before[path.name]
    ]
    assert not stale, (
        f"stale after regeneration: {stale} — re-run "
        "scripts/codegen/gen_commands.py and cargo fmt -p divoomd"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
