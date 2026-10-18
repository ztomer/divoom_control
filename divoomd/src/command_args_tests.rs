//! A missing required argument is refused with a code, for every command
//! the daemon answers (P5.9).
//!
//! The command table is walked, not sampled: every arm of the dispatcher's
//! `match` must have a row in `COMMAND_ARGS` (and every row an arm), and
//! every requirement in a row is dropped in turn from an otherwise complete
//! request. A new command without a row fails here; a row whose requirement
//! is answered without `bad_request` fails here.

use std::collections::BTreeSet;
use std::sync::Arc;

use serde_json::{json, Map, Value};

use crate::command_args::{ArgType, Required, COMMAND_ARGS};
use crate::daemon::Daemon;
use crate::protocol::make_request;
use crate::socket_server::Handler as _;

/// Every command name the dispatcher's `match` answers, read from its source.
fn dispatched() -> BTreeSet<String> {
    let src = include_str!("daemon/dispatch.rs");
    let start = src
        .find("pub(super) async fn dispatch")
        .expect("the dispatch fn");
    let end = start
        + src[start..]
            .find("other => err_code")
            .expect("its fallback arm");
    let body = &src[start..end];
    let mut names = BTreeSet::new();
    let mut rest = body;
    while let Some(open) = rest.find('"') {
        let after = &rest[open + 1..];
        let Some(close) = after.find('"') else { break };
        let literal = &after[..close];
        let tail = after[close + 1..].trim_start();
        if tail.starts_with("=>") || tail.starts_with('|') {
            names.insert(literal.to_string());
        }
        rest = &after[close + 1..];
    }
    names
}

fn sample(t: ArgType) -> Value {
    match t {
        ArgType::Str => json!("x"),
        ArgType::Int => json!(1),
        ArgType::Bool => json!(true),
        ArgType::Object => json!({}),
        ArgType::Array | ArgType::Any => json!([]),
    }
}

/// A value of some other type, or `None` when every value is admitted.
fn wrong(t: ArgType) -> Option<Value> {
    match t {
        ArgType::Str => Some(json!(true)),
        ArgType::Int | ArgType::Bool => Some(json!("x")),
        ArgType::Object | ArgType::Array => Some(json!(1)),
        ArgType::Any => None,
    }
}

/// Every requirement but `skip` satisfied by its first key.
fn all_but(required: &[Required], skip: usize) -> Map<String, Value> {
    let mut args = Map::new();
    for (i, req) in required.iter().enumerate() {
        if i != skip {
            let (k, t) = req[0];
            args.insert(k.to_string(), sample(t));
        }
    }
    args
}

fn assert_refused(command: &str, key: &str, args: &Value, reply: &Value) {
    let ctx = format!("{command} {args} -> {reply}");
    assert_eq!(reply["success"], json!(false), "{ctx}");
    assert_eq!(reply["code"], json!("bad_request"), "no code: {ctx}");
    let prose = reply["error"].as_str().unwrap_or_default();
    assert!(
        prose.contains(command) && prose.contains(&format!("'{key}'")),
        "the refusal names the command and the argument: {ctx}"
    );
}

#[test]
fn the_table_has_a_row_for_every_command_the_dispatcher_answers() {
    let arms = dispatched();
    assert!(arms.len() > 40, "the source walk found the arms: {arms:?}");
    let rows: BTreeSet<String> = COMMAND_ARGS.iter().map(|(c, _)| (*c).to_string()).collect();
    let unlisted: Vec<_> = arms.difference(&rows).collect();
    let stale: Vec<_> = rows.difference(&arms).collect();
    assert!(
        unlisted.is_empty(),
        "commands with no COMMAND_ARGS row: {unlisted:?}"
    );
    assert!(
        stale.is_empty(),
        "COMMAND_ARGS rows no arm answers: {stale:?}"
    );
}

#[tokio::test]
async fn a_missing_required_argument_is_bad_request_for_every_command() {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let mut checked = 0;
    for (command, required) in COMMAND_ARGS {
        for (i, req) in required.iter().enumerate() {
            let args = Value::Object(all_but(required, i));
            let reply = d
                .handle(make_request(command, Some(args.clone()), None))
                .await;
            assert_refused(command, req[0].0, &args, &reply);
            checked += 1;

            // One key, the wrong type: refused the same way, not misread.
            let [(key, t)] = req else { continue };
            let Some(bad) = wrong(*t) else { continue };
            let mut args = all_but(required, i);
            args.insert((*key).to_string(), bad);
            let args = Value::Object(args);
            let reply = d
                .handle(make_request(command, Some(args.clone()), None))
                .await;
            assert_refused(command, key, &args, &reply);
        }
    }
    assert!(checked >= 20, "walked {checked} requirements");
}

/// The class, not just the table: no handler builds a missing-argument
/// refusal by hand, where it would carry no code. They go through
/// `command_args::missing`.
#[test]
fn no_handler_refuses_a_missing_argument_without_a_code() {
    fn walk(dir: &std::path::Path, out: &mut Vec<std::path::PathBuf>) {
        for e in std::fs::read_dir(dir).expect("readable src").flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, out);
            } else if p.extension().is_some_and(|x| x == "rs") {
                out.push(p);
            }
        }
    }
    let mut files = Vec::new();
    walk(
        &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src"),
        &mut files,
    );
    assert!(files.len() > 50, "walked the tree: {}", files.len());
    let mut hand_built = Vec::new();
    for f in &files {
        let src = std::fs::read_to_string(f).expect("utf-8 source");
        for (n, line) in src.lines().enumerate() {
            if line.trim_start().starts_with("//") {
                continue;
            }
            let refusal = line.contains("err_reply(") || line.contains("\"error\":");
            let says_missing = line.contains("requires '") || line.contains("missing '");
            if refusal && says_missing {
                hand_built.push(format!("{}:{}: {}", f.display(), n + 1, line.trim()));
            }
        }
    }
    assert!(
        hand_built.is_empty(),
        "missing-argument refusals with no code:\n{}",
        hand_built.join("\n")
    );
}
