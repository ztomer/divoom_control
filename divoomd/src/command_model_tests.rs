//! The command model's own tests, split out because the three model files are
//! GENERATED: a hand-written test module inside one of them would be erased by
//! the next `scripts/codegen/gen_commands.py` run, and a test that a
//! regeneration deletes is a test that stops running without ever failing. The
//! `#[path]` wiring in `command_model.rs` is emitted by the generator, so
//! regenerating keeps pointing here.
//!
//! These check the properties the enum exists for -- that every command
//! round-trips through its own id, that every NAME (aliases included) resolves
//! to the command the protocol means, and that an unknown name or id refuses
//! rather than inventing one. The two-sided Python check that the model matches
//! `divoom_lib.models.COMMANDS` is `tests/test_command_model_parity.py`.

use super::*;
use crate::command_names::{command, command_id, COMMAND_NAMES};
use crate::commands::{COMMANDS, COMMAND_COUNT, COMMAND_ID_COUNT};
use std::collections::BTreeMap;

#[test]
fn every_command_round_trips_through_its_id() {
    for cmd in ALL {
        assert_eq!(
            Command::try_from(cmd.id()),
            Ok(*cmd),
            "{cmd:?} does not resolve back from its own id"
        );
    }
}

#[test]
fn every_name_resolves_and_names_its_command() {
    for (name, cmd) in COMMAND_NAMES {
        assert_eq!(command(name), Some(*cmd), "{name:?} does not resolve");
        assert_eq!(command_id(name), Some(cmd.id()));
        // The canonical name is the one the variant reports; an alias
        // resolves to the same command but is not its `name()`.
        if *name == cmd.name() {
            assert_eq!(Command::try_from(*name), Ok(*cmd));
        }
    }
}

#[test]
fn the_aliased_ids_are_one_command_spelled_two_ways() {
    // Four ids, eight names, four commands. If this ever reports eight
    // commands, the enum has gone per-name and `TryFrom<u8>` has quietly
    // become partial.
    let mut by_id: BTreeMap<u8, Vec<&str>> = BTreeMap::new();
    for (name, cmd) in COMMAND_NAMES {
        by_id.entry(cmd.id()).or_default().push(name);
    }
    let aliased: Vec<_> = by_id.values().filter(|names| names.len() > 1).collect();
    let extra_spellings: usize = aliased.iter().map(|names| names.len() - 1).sum();
    assert_eq!(aliased.len(), 4, "expected four aliased ids");
    assert_eq!(
        extra_spellings, 4,
        "expected one extra spelling per aliased id"
    );
    for names in aliased {
        let first = command(names[0]).expect("resolves");
        for name in names {
            assert_eq!(
                command(name),
                Some(first),
                "{name:?} is a different command"
            );
        }
    }
}

#[test]
fn the_generic_ack_set_is_commands_and_nothing_else() {
    // The set that was `[0x45, 0x05, 0x8A, 0x46, 0x42]` — hand-typed bytes
    // sitting beside a generated model of the same protocol, with nothing
    // comparing them. Two things are worth pinning now that it is spelled as
    // variants: every entry resolves to a real command (a typo would be a
    // command that never matches), and no command is listed twice (a
    // duplicate would look like coverage and be one entry short).
    let mut seen: BTreeMap<u8, &str> = BTreeMap::new();
    for command in crate::models::GENERIC_ACK_COMMANDS {
        let id = command.id();
        assert!(
            seen.insert(id, command.name()).is_none(),
            "0x{id:02x} is listed twice as a generic-ACK command"
        );
        // Round-tripping proves the variant's id is in the model, not just that
        // the name compiles.
        assert_eq!(Command::try_from(id), Ok(command));
    }
    assert_eq!(seen.len(), 5, "the generic-ACK set changed size");
    // And the ids are the ones the daemon has always used: a reader comparing
    // against git history should find the same five bytes.
    assert_eq!(
        seen.keys().copied().collect::<Vec<u8>>(),
        vec![0x05, 0x42, 0x45, 0x46, 0x8A],
        "the generic-ACK id set changed"
    );
}

#[test]
fn an_unknown_name_and_an_unknown_id_both_refuse() {
    assert_eq!(command("set nothing"), None);
    assert_eq!(command(""), None);
    assert_eq!(command_id("SET VOLUME"), None, "lookup is case-sensitive");
    // 0x00 is not in the protocol; a `as u8` cast here would invent one.
    assert_eq!(Command::try_from(0x00_u8), Err(0x00));
    assert!(Command::try_from(0xff_u8).is_err());
}

#[test]
fn the_counts_agree_with_the_tables_they_describe() {
    assert_eq!(ALL.len(), COMMAND_ID_COUNT);
    assert_eq!(COMMAND_NAMES.len(), COMMAND_COUNT);
    assert_eq!(COMMANDS.len(), COMMAND_COUNT);
}
