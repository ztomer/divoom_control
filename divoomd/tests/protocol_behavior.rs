//! NDJSON socket-protocol behavior + COMMANDS map parity. Mirrors the framing
//! semantics of divoom_client/daemon_protocol.py (iter_messages / encode_message /
//! make_request) and pins a few command ids against divoom_lib.models.COMMANDS.

use divoomd::commands::{command_id, COMMAND_COUNT};
use divoomd::protocol::{
    encode_message, err_reply, iter_messages, make_request, ok_reply, Request,
};
use serde_json::{json, Value};

// ── NDJSON framing ──────────────────────────────────────────────────────────

#[test]
fn encode_message_is_compact_with_newline() {
    let bytes = encode_message(&json!({"command": "scan", "args": {"timeout": 5}}));
    assert_eq!(*bytes.last().unwrap(), b'\n');
    // compact: no spaces after ':' or ','
    let s = std::str::from_utf8(&bytes).unwrap();
    assert!(!s.contains(", "), "must be compact JSON");
    assert!(!s.contains(": "), "must be compact JSON");
}

#[test]
fn encode_then_iter_round_trips() {
    let obj = json!({"command": "set_brightness", "args": {"value": 80}, "token": "t"});
    let (msgs, rem) = iter_messages(&encode_message(&obj));
    assert_eq!(msgs.len(), 1);
    assert_eq!(msgs[0], obj);
    assert!(rem.is_empty());
}

#[test]
fn iter_messages_multi_blank_and_malformed() {
    // two valid frames, a blank line, and a malformed line — all in one buffer
    let mut buf = Vec::new();
    buf.extend_from_slice(b"{\"a\":1}\n");
    buf.extend_from_slice(b"\n"); // blank -> skipped
    buf.extend_from_slice(b"{bad json\n"); // malformed -> skipped, not an error
    buf.extend_from_slice(b"{\"b\":2}\n");
    let (msgs, rem) = iter_messages(&buf);
    assert_eq!(msgs, vec![json!({"a": 1}), json!({"b": 2})]);
    assert!(rem.is_empty());
}

#[test]
fn iter_messages_keeps_partial_trailing_frame_as_remainder() {
    let buf = b"{\"a\":1}\n{\"b\":2"; // second frame has no trailing newline
    let (msgs, rem) = iter_messages(buf);
    assert_eq!(msgs, vec![json!({"a": 1})]);
    assert_eq!(
        rem,
        b"{\"b\":2".to_vec(),
        "incomplete frame is the remainder"
    );
}

#[test]
fn iter_messages_empty_buffer() {
    let (msgs, rem) = iter_messages(b"");
    assert!(msgs.is_empty());
    assert!(rem.is_empty());
}

// ── cross-language: parse bytes produced by the Python encoder ───────────────

#[test]
fn parses_python_encoded_request() {
    // exact bytes from divoom_client.daemon_protocol.encode_message(
    //   make_request("scan", {"timeout": 5}, "tok"))
    let py = b"{\"command\":\"scan\",\"args\":{\"timeout\":5},\"token\":\"tok\"}\n";
    let (msgs, rem) = iter_messages(py);
    assert!(rem.is_empty());
    assert_eq!(msgs.len(), 1);
    // parse into the typed Request
    let req: Request = serde_json::from_value(msgs[0].clone()).unwrap();
    assert_eq!(req.command, "scan");
    assert_eq!(req.args, json!({"timeout": 5}));
    assert_eq!(req.token.as_deref(), Some("tok"));
}

// ── constructors ────────────────────────────────────────────────────────────

#[test]
fn make_request_defaults_args_to_empty_object() {
    let r = make_request("scan", None, None);
    assert_eq!(r.command, "scan");
    assert_eq!(r.args, json!({}));
    assert!(r.token.is_none());
    // token omitted from the serialized form when None
    let v: Value = serde_json::to_value(&r).unwrap();
    assert!(v.get("token").is_none());
}

#[test]
fn replies_have_success_flag() {
    assert_eq!(
        ok_reply(json!({"result": 60})),
        json!({"success": true, "result": 60})
    );
    assert_eq!(
        err_reply("boom"),
        json!({"success": false, "error": "boom"})
    );
}

// ── COMMANDS map parity ─────────────────────────────────────────────────────

#[test]
fn command_ids_match_python() {
    assert_eq!(command_id("set brightness"), Some(0x74));
    assert_eq!(command_id("app new send gif cmd"), Some(0x8b));
    assert_eq!(command_id("app get user define info"), Some(0x8e));
    assert_eq!(command_id("set volume"), Some(0x08));
    assert_eq!(command_id("not a real command"), None);
    assert_eq!(COMMAND_COUNT, 109);
}
