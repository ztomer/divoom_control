//! `divoomd mcp`'s wire behaviour, pinned against the REAL stdio binary.
//!
//! Written before the move onto rmcp (lane MCP.DV, owner ruling OW.60) and
//! run green on the hand-rolled loop first, so the move is proven rather than
//! assumed: every test spawns `divoomd mcp`, writes newline-delimited
//! JSON-RPC to its stdin and reads its stdout, exactly as an MCP host does.
//! Nothing here reaches into the library, so it survives the server being
//! rewritten underneath it.
//!
//! The daemon on the other side is a FAKE: a unix socket in a temp directory
//! that answers canned NDJSON and records what it was sent. No test can reach
//! a panel -- `DIVOOM_SOCKET` points at the fake (or at nothing) and the
//! remote-daemon variables are removed from the child's environment.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// A bound on every read: a hung server fails the test, it never hangs it.
const READ_TIMEOUT: Duration = Duration::from_secs(30);

/// The tools/list the hand-rolled server (v0.42.0) answered, captured from the
/// binary before the move. The port is checked against it tool by tool.
const V042_TOOLS: &str = include_str!("fixtures/mcp_tools_list_v0.42.json");

fn scratch(name: &str) -> PathBuf {
    // Short: a unix socket path is capped at 104 bytes on macOS.
    let dir = std::env::temp_dir().join(format!("dvmcp-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("scratch dir");
    dir
}

/// A daemon that answers every request with `reply` and records the requests.
struct FakeDaemon {
    socket: PathBuf,
    seen: Arc<Mutex<Vec<Value>>>,
}

impl FakeDaemon {
    fn replying(dir: &Path, reply: Value) -> Self {
        let socket = dir.join("d.sock");
        let listener = UnixListener::bind(&socket).expect("bind fake daemon");
        let seen = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&seen);
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let mut line = String::new();
                let Ok(read) = stream.try_clone() else {
                    continue;
                };
                if BufReader::new(read).read_line(&mut line).is_err() {
                    continue;
                }
                if let Ok(v) = serde_json::from_str::<Value>(line.trim()) {
                    if let Ok(mut g) = sink.lock() {
                        g.push(v);
                    }
                }
                let mut bytes = serde_json::to_vec(&reply).unwrap_or_default();
                bytes.push(b'\n');
                let _ = stream.write_all(&bytes);
            }
        });
        Self { socket, seen }
    }

    fn requests(&self) -> Vec<Value> {
        self.seen.lock().map(|g| g.clone()).unwrap_or_default()
    }
}

struct Session {
    child: Child,
    stdin: Option<ChildStdin>,
    lines: Receiver<String>,
    next_id: i64,
}

impl Drop for Session {
    fn drop(&mut self) {
        drop(self.stdin.take());
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Session {
    fn start(socket: &Path, extra: &[&str]) -> Self {
        let mut s = Self::spawn(socket, extra);
        let init = s.initialize();
        assert!(init.get("result").is_some(), "initialize: {init}");
        s.send(&json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }));
        s
    }

    fn initialize(&mut self) -> Value {
        self.request(
            "initialize",
            &json!({
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": { "name": "mcp_stdio", "version": "0" },
            }),
        )
    }

    fn spawn(socket: &Path, extra: &[&str]) -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_divoomd"))
            .arg("mcp")
            .args(extra)
            .env("DIVOOM_SOCKET", socket)
            .env_remove("DIVOOM_DAEMON_HOST")
            .env_remove("DIVOOM_DAEMON_PORT")
            .env_remove("DIVOOM_DAEMON_TOKEN")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn divoomd mcp");
        let stdin = child.stdin.take();
        let stdout = child.stdout.take().expect("stdout");
        let (tx, lines) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        Self {
            child,
            stdin,
            lines,
            next_id: 0,
        }
    }

    fn send(&mut self, msg: &Value) {
        let stdin = self.stdin.as_mut().expect("stdin open");
        writeln!(stdin, "{msg}").expect("write request");
        stdin.flush().expect("flush");
    }

    fn recv(&self) -> Value {
        let line = self
            .lines
            .recv_timeout(READ_TIMEOUT)
            .expect("the server answered in time");
        serde_json::from_str(&line).expect("each line is JSON")
    }

    fn request(&mut self, method: &str, params: &Value) -> Value {
        self.next_id += 1;
        let id = self.next_id;
        self.send(&json!({ "jsonrpc": "2.0", "id": id, "method": method, "params": params }));
        let reply = self.recv();
        assert_eq!(
            reply["id"],
            json!(id),
            "replies pair with requests: {reply}"
        );
        reply
    }

    fn call(&mut self, name: &str, arguments: &Value) -> Value {
        let reply = self.request(
            "tools/call",
            &json!({ "name": name, "arguments": arguments }),
        );
        assert!(
            reply.get("error").is_none(),
            "a tool call is a result: {reply}"
        );
        reply["result"].clone()
    }

    fn tools(&mut self) -> Vec<Value> {
        let reply = self.request("tools/list", &json!({}));
        reply["result"]["tools"]
            .as_array()
            .expect("tools array")
            .clone()
    }
}

/// The JSON a tool's first text block carries.
fn text_json(result: &Value) -> Value {
    assert_eq!(result["content"][0]["type"], json!("text"), "{result}");
    let text = result["content"][0]["text"].as_str().expect("text");
    serde_json::from_str(text).expect("the text is JSON")
}

fn no_daemon(dir: &Path) -> PathBuf {
    dir.join("none.sock")
}

#[test]
fn initialize_reports_identity_and_the_tools_capability() {
    let dir = scratch("init");
    let mut s = Session::spawn(&no_daemon(&dir), &[]);
    let reply = s.initialize();
    let r = &reply["result"];
    assert_eq!(r["protocolVersion"], json!("2025-11-25"), "{reply}");
    assert_eq!(r["serverInfo"]["name"], json!("divoom-control"));
    assert_eq!(r["serverInfo"]["version"], json!(env!("CARGO_PKG_VERSION")));
    assert!(r["capabilities"]["tools"].is_object(), "{reply}");
}

#[test]
fn ping_answers_empty_and_a_notification_gets_no_reply() {
    let dir = scratch("ping");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    // `start` sent notifications/initialized; had it been answered, that
    // answer would be the next line and pair with no id.
    let reply = s.request("ping", &json!({}));
    assert_eq!(reply["result"], json!({}), "{reply}");
}

#[test]
fn every_v042_tool_keeps_its_name_description_and_input_schema() {
    let dir = scratch("list");
    let mut s = Session::start(&no_daemon(&dir), &["--allow-destructive"]);
    let listed = s.tools();
    let old: Vec<Value> = serde_json::from_str(V042_TOOLS).expect("fixture parses");
    for t in &old {
        let name = &t["name"];
        let now = listed
            .iter()
            .find(|n| &n["name"] == name)
            .unwrap_or_else(|| panic!("{name} is gone"));
        assert_eq!(now["description"], t["description"], "{name}");
        assert_eq!(now["inputSchema"], t["inputSchema"], "{name}");
    }
}

#[test]
fn a_call_reaches_the_daemon_and_answers_text_json() {
    let dir = scratch("call");
    let daemon = FakeDaemon::replying(&dir, json!({ "success": true, "result": {} }));
    let mut s = Session::start(&daemon.socket, &[]);
    let result = s.call("set_volume", &json!({ "level": 7 }));
    assert_eq!(result["isError"], json!(false), "{result}");
    assert_eq!(text_json(&result), json!({ "ok": true, "level": 7 }));
    let seen = daemon.requests();
    assert_eq!(seen.len(), 1, "{seen:?}");
    assert_eq!(seen[0]["command"], json!("device_call"));
    assert_eq!(seen[0]["args"]["method"], json!("music.set_volume"));
    assert_eq!(seen[0]["args"]["args"], json!([7]));
}

#[test]
fn a_daemon_refusal_is_a_tool_error_carrying_its_code() {
    let dir = scratch("refuse");
    let daemon = FakeDaemon::replying(
        &dir,
        json!({ "success": false, "error": "no panel 'X'", "code": "unknown_device" }),
    );
    let mut s = Session::start(&daemon.socket, &[]);
    let result = s.call("set_volume", &json!({ "level": 7, "mac": "X" }));
    assert_eq!(result["isError"], json!(true), "{result}");
    assert_eq!(
        text_json(&result),
        json!({ "error": "no panel 'X'", "code": "unknown_device" })
    );
}

#[test]
fn a_missing_argument_is_a_tool_error_naming_it() {
    let dir = scratch("arg");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    let result = s.call("set_volume", &json!({}));
    assert_eq!(result["isError"], json!(true), "{result}");
    let text = result["content"][0]["text"].as_str().unwrap_or_default();
    assert!(text.contains("level"), "{text}");
}

#[test]
fn an_unknown_tool_is_a_tool_error_not_a_protocol_error() {
    let dir = scratch("unknown");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    let result = s.call("no_such_tool", &json!({}));
    assert_eq!(result["isError"], json!(true), "{result}");
}

#[test]
fn an_unknown_method_is_method_not_found() {
    let dir = scratch("method");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    let reply = s.request("no/such/method", &json!({}));
    assert_eq!(reply["error"]["code"], json!(-32601), "{reply}");
}

#[test]
fn a_read_with_no_daemon_answers_nulls_not_a_failure() {
    let dir = scratch("read");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    let result = s.call("get_device_state", &json!({}));
    assert_eq!(result["isError"], json!(false), "{result}");
    let state = text_json(&result);
    assert_eq!(state["volume"], Value::Null, "{state}");
    assert_eq!(state["brightness"], Value::Null, "{state}");
}

#[test]
fn eof_on_stdin_ends_the_server() {
    let dir = scratch("eof");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    drop(s.stdin.take());
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(status) = s.child.try_wait().expect("try_wait") {
            assert!(status.success(), "{status}");
            return;
        }
        assert!(Instant::now() < deadline, "the server outlived its stdin");
        std::thread::sleep(Duration::from_millis(50));
    }
}

// ── deliberate deltas of the move onto rmcp (lane MCP.DV), each pinned ──────

/// The `_meta` the newest protocol (2026-07-28) carries on every request in
/// place of a handshake.
fn newest_meta() -> Value {
    json!({
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": { "name": "mcp_stdio", "version": "0" },
    })
}

#[test]
fn the_newest_protocol_is_spoken_per_request_without_a_handshake() {
    // DELTA: the hand-rolled loop answered `initialize` in 2026-07-28. That
    // version has no `initialize`; it is spoken per request, and discovery
    // says so.
    let dir = scratch("newest");
    let mut s = Session::spawn(&no_daemon(&dir), &[]);
    let found = s.request("server/discover", &json!({ "_meta": newest_meta() }));
    let versions = found["result"]["supportedVersions"]
        .as_array()
        .expect("supported versions");
    assert!(versions.contains(&json!("2026-07-28")), "{found}");
    let listed = s.request("tools/list", &json!({ "_meta": newest_meta() }));
    assert!(listed["result"]["tools"].is_array(), "{listed}");
}

#[test]
fn initialize_asking_for_the_newest_names_the_newest_with_a_handshake() {
    // DELTA (upstream's): 2026-07-28 has no handshake, so a server answering
    // `initialize` names the newest version that has one.
    let dir = scratch("initnew");
    let mut s = Session::spawn(&no_daemon(&dir), &[]);
    let reply = s.request(
        "initialize",
        &json!({ "protocolVersion": "2026-07-28", "capabilities": {},
                 "clientInfo": { "name": "t", "version": "0" } }),
    );
    assert_eq!(
        reply["result"]["protocolVersion"],
        json!("2025-11-25"),
        "{reply}"
    );
}

#[test]
fn every_listed_tool_states_its_effect_and_its_reply_shape() {
    let dir = scratch("annot");
    let mut s = Session::start(&no_daemon(&dir), &["--allow-destructive"]);
    for t in s.tools() {
        let a = &t["annotations"];
        assert!(a["readOnlyHint"].is_boolean(), "{t}");
        assert!(a["destructiveHint"].is_boolean(), "{t}");
        assert_eq!(t["outputSchema"]["type"], json!("object"), "{t}");
    }
}

#[test]
fn destructive_tools_are_hidden_and_refused_unless_opted_in() {
    // DELTA: the four tools that overwrite panel state the daemon cannot read
    // back are not offered by a bare `divoomd mcp`, and a host that guesses
    // one is refused before anything reaches the daemon.
    let dir = scratch("destr");
    let daemon = FakeDaemon::replying(&dir, json!({ "success": true, "result": {} }));
    let mut s = Session::start(&daemon.socket, &[]);
    let listed = s.tools();
    for t in &listed {
        assert_eq!(t["annotations"]["destructiveHint"], json!(false), "{t}");
    }
    let old: Vec<Value> = serde_json::from_str(V042_TOOLS).expect("fixture parses");
    assert_eq!(
        listed.len(),
        old.len() - 4 + 1,
        "25 - 4 destructive + the preview"
    );
    let refused = s.call("set_low_power", &json!({ "enabled": true }));
    assert_eq!(refused["isError"], json!(true), "{refused}");
    assert_eq!(text_json(&refused)["code"], json!("not_enabled"));
    assert_eq!(daemon.requests().len(), 0, "nothing reached the daemon");
}

#[test]
fn a_success_carries_the_same_object_as_structured_content() {
    let dir = scratch("struct");
    let daemon = FakeDaemon::replying(&dir, json!({ "success": true, "result": {} }));
    let mut s = Session::start(&daemon.socket, &[]);
    let result = s.call("set_brightness", &json!({ "level": 40 }));
    assert_eq!(result["structuredContent"], text_json(&result), "{result}");
}

#[test]
fn the_preview_with_no_daemon_says_why_and_is_not_a_failure() {
    let dir = scratch("preview");
    let mut s = Session::start(&no_daemon(&dir), &[]);
    let result = s.call("get_screen_previews", &json!({}));
    assert_eq!(result["isError"], json!(false), "{result}");
    let p = &result["structuredContent"];
    assert_eq!(p["daemon"]["state"], json!("not_running"), "{p}");
    assert!(p["daemon"]["reason"].is_string(), "{p}");
}
