//! Daemon socket protocol — newline-delimited JSON ("NDJSON"), ported from
//! `divoom_client/daemon_protocol.py`. This is the language-agnostic seam: the
//! Python GUI/menubar/CLI clients talk to either daemon over it unchanged, and the
//! Python test suite becomes the conformance oracle for the Rust server.
//!
//! JSON is order-independent, so messages are matched semantically (not byte-for-
//! byte on key order); the Python client parses, it does not byte-compare.

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DEFAULT_SOCKET_PATH: &str = "/tmp/divoom.sock";
pub const SUBSCRIBE_COMMAND: &str = "subscribe";

/// Frame cap: a client/peer that never sends a newline can't grow the read buffer
/// without bound. Matches the Python server + client cap.
pub const MAX_REPLY_BYTES: usize = 16 * 1024 * 1024;

/// One NDJSON line: compact JSON + `\n`. (`serde_json` is compact by default,
/// matching Python's `json.dumps(separators=(",", ":"))`.)
pub fn encode_message(obj: &Value) -> Vec<u8> {
    let mut v = serde_json::to_vec(obj).expect("a serde_json::Value always serializes");
    v.push(b'\n');
    v
}

/// Split a byte buffer into complete JSON messages + the trailing remainder.
/// Blank lines are skipped; a malformed line is skipped (not an error) so one bad
/// frame can't wedge the stream. Mirrors `iter_messages`: `*lines, remainder =
/// buffer.split(b"\n")`.
pub fn iter_messages(buffer: &[u8]) -> (Vec<Result<Value, String>>, Vec<u8>) {
    let mut parts: Vec<&[u8]> = buffer.split(|&b| b == b'\n').collect();
    // split always yields >= 1 element; the last is the bytes after the final '\n'.
    let remainder = parts.pop().unwrap_or(&[]).to_vec();
    let mut messages = Vec::new();
    for line in parts {
        let trimmed = line.trim_ascii();
        if trimmed.is_empty() {
            continue;
        }
        // R67: a line that does not parse yields an Err rather than being
        // DROPPED. It used to be silently discarded, so a client that sent
        // malformed JSON got no reply at all and blocked until its own read
        // timeout — while every other error returned a clean
        // {"success":false,"error":...} immediately. Measured: a truncated
        // frame produced a TimeoutError on the client and nothing on the wire.
        match std::str::from_utf8(trimmed) {
            Err(_) => messages.push(Err("line is not valid UTF-8".to_string())),
            Ok(s) => match serde_json::from_str::<Value>(s) {
                Ok(v) => messages.push(Ok(v)),
                Err(e) => messages.push(Err(format!("line is not valid JSON: {e}"))),
            },
        }
    }
    (messages, remainder)
}

/// The NDJSON protocol version this daemon speaks.
///
/// R67: there was no version and no capability signal of any kind, so a client
/// could not tell an OLD daemon from a new one except by calling a command and
/// reading the "command not implemented in the native daemon yet" error. That
/// is exactly how this round wasted a debugging cycle: a `players` call
/// returned an empty list because the installed app was running a daemon built
/// before that command existed, and nothing in the reply said so.
///
/// Bump the MINOR when adding a command or a reply field (backwards
/// compatible); bump the MAJOR when changing or removing one.
pub const PROTOCOL_VERSION: &str = "1.1";

/// Commands this daemon can answer, for capability negotiation.
///
/// A client that wants a feature can ASK instead of calling and interpreting an
/// error string — error text is not an API, and matching on it is how clients
/// break when a message is reworded.
pub fn protocol_capabilities() -> Vec<&'static str> {
    vec![
        "device_call",
        "hot_update",
        "live_jobs",
        "notifications",
        "now_playing",
        "players",
        "wall",
        "weather",
    ]
}

/// A client request: `{"command": ..., "args": {...}, "token"?: ...}`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Request {
    pub command: String,
    #[serde(default)]
    pub args: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
}

/// Build a request (args defaults to an empty object, like Python's make_request).
pub fn make_request(command: &str, args: Option<Value>, token: Option<String>) -> Request {
    Request {
        command: command.to_string(),
        args: args.unwrap_or_else(|| Value::Object(serde_json::Map::new())),
        token,
    }
}

/// A successful reply `{"success": true, ...extra}`.
pub fn ok_reply(extra: Value) -> Value {
    merge_success(true, extra, None)
}

/// An error reply `{"success": false, "error": msg}`.
pub fn err_reply(msg: &str) -> Value {
    merge_success(false, Value::Object(serde_json::Map::new()), Some(msg))
}

fn merge_success(success: bool, extra: Value, error: Option<&str>) -> Value {
    let mut map = serde_json::Map::new();
    map.insert("success".into(), Value::Bool(success));
    if let Some(e) = error {
        map.insert("error".into(), Value::String(e.to_string()));
    }
    if let Value::Object(extra) = extra {
        for (k, v) in extra {
            map.insert(k, v);
        }
    }
    Value::Object(map)
}
