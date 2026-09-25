//! Native MCP server — stdio JSON-RPC bridge to the running daemon.
//!
//! Ported from `divoom_lib/mcp_server.py` + `mcp_tools.py`. Run as `divoomd
//! mcp`: it does NOT own the device; it connects to the daemon's unix socket
//! (`DIVOOM_SOCKET`, default /tmp/divoom.sock) and forwards each `tools/call`
//! as a `device_call`/command — the same daemon-routed model as the Python R28
//! MCP-via-daemon.
//!
//! Protocol: line-delimited JSON-RPC 2.0 on stdin/stdout. Methods: initialize,
//! tools/list, tools/call, ping. Tool catalog + dispatch live in `mcp_tools`.

use serde_json::{json, Value};

use crate::daemon_target::DaemonTarget;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

/// Latest SEP-2575 protocol version: the default answer and the fallback
/// when a client asks for something unknown. Fleet reference: zinc's
/// `engine_client::PROTOCOL_VERSION`.
const PROTOCOL_VERSION: &str = "2026-07-28";

/// Every protocol version we can serve. A client asking for one of these
/// is answered in it; anything else (or nothing) gets the latest.
const SUPPORTED_PROTOCOL_VERSIONS: &[&str] = &[
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
];

/// SEP-2575 negotiation: echo `requested` when it is one we support,
/// else the latest. A missing/non-string request also gets the latest.
fn negotiate_protocol_version(requested: Option<&str>) -> &'static str {
    match requested {
        Some(v) if SUPPORTED_PROTOCOL_VERSIONS.contains(&v) => {
            // `v` is one of the table entries, so re-derive the static str.
            SUPPORTED_PROTOCOL_VERSIONS
                .iter()
                .find(|s| **s == v)
                .copied()
                .unwrap_or(PROTOCOL_VERSION)
        }
        _ => PROTOCOL_VERSION,
    }
}

/// True when `fd` is a pipe, socket or character device.
///
/// An MCP stdio server only works when stdin AND stdout are pipes owned by the
/// client that launched it. A regular file is not one: the GUI points our stdout
/// at a log file, and a user runs `divoom-control mcp-server > out.txt`. The
/// Python server this replaces detected that up front, because asyncio's
/// `connect_write_pipe` otherwise raised "Pipe transport is only for pipes,
/// sockets and character devices" — a traceback into the log the GUI's status
/// card surfaces.
///
/// A terminal is a character device, so an interactive run still serves, exactly
/// as it did before. A closed or invalid descriptor is not pipe-like.
fn fd_is_pipe_like(fd: std::os::fd::RawFd) -> bool {
    // SAFETY: `fstat` writes only the `stat` it is handed; it never closes `fd`
    // and takes no ownership of it, and `fd` is borrowed for the call.
    let mut st: libc::stat = unsafe { std::mem::zeroed() };
    // SAFETY: `st` is a valid, writable, aligned `libc::stat` and `fd` is live.
    if unsafe { libc::fstat(fd, &raw mut st) } != 0 {
        return false;
    }
    let kind = st.st_mode & libc::S_IFMT;
    kind == libc::S_IFIFO || kind == libc::S_IFSOCK || kind == libc::S_IFCHR
}

/// The diagnostic printed when stdio is not a client-owned pipe. One message,
/// naming both the cause and the fix, because this is what someone reads in a log
/// with no other context.
const NOT_A_PIPE: &str = "MCP server: stdin/stdout are not connected to an MCP client. \
The stdio transport needs pipes owned by the client, so launch this from your \
MCP client's config (Claude Desktop, Cursor, ...), not standalone or from the GUI. \
See docs/MCP_SERVER.md.";

/// # Errors
///
/// From the transport it serves on: stdin closed, or a reply could not be
/// written.
pub async fn run() -> std::io::Result<()> {
    if !fd_is_pipe_like(libc::STDIN_FILENO) || !fd_is_pipe_like(libc::STDOUT_FILENO) {
        eprintln!("{NOT_A_PIPE}");
        return Ok(());
    }
    // One target for the process, chosen from the environment exactly as the
    // Python shell chose it — so `DIVOOM_DAEMON_HOST`/`_PORT`/`_TOKEN` reach a
    // daemon on another machine, which is the one thing this server could not do
    // before and the reason a second implementation existed.
    let target = DaemonTarget::from_env();
    let mut reader = BufReader::new(tokio::io::stdin());
    let mut stdout = tokio::io::stdout();
    let mut line = String::new();
    loop {
        line.clear();
        if reader.read_line(&mut line).await? == 0 {
            break; // stdin closed
        }
        if line.trim().is_empty() {
            continue;
        }
        if let Some(resp) = handle_line(&line, &target).await {
            let mut out = serde_json::to_vec(&resp).unwrap_or_default();
            out.push(b'\n');
            stdout.write_all(&out).await?;
            stdout.flush().await?;
        }
    }
    Ok(())
}

fn ok(id: &Value, result: Value) -> Value {
    let mut reply = json!({ "jsonrpc": "2.0", "id": id });
    reply["result"] = result;
    reply
}

fn err(id: &Value, code: i64, message: &str) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "error": { "code": code, "message": message } })
}

async fn handle_line(line: &str, target: &DaemonTarget) -> Option<Value> {
    let req: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(e) => return Some(err(&Value::Null, -32700, &format!("parse error: {e}"))),
    };
    if req.get("jsonrpc").and_then(|v| v.as_str()) != Some("2.0") {
        return Some(err(
            &req.get("id").cloned().unwrap_or(Value::Null),
            -32600,
            "jsonrpc must be '2.0'",
        ));
    }
    let id = req.get("id").cloned();
    let method = req.get("method").and_then(|v| v.as_str()).unwrap_or("");
    // Notifications (no id) get no response.
    let is_notification = id.is_none();
    let id = id.unwrap_or(Value::Null);

    let result: Result<Value, (i64, String)> = match method {
        "initialize" => {
            // SEP-2575 negotiation: echo a supported request, else latest.
            // Extra params members (e.g. `_meta`) are tolerated — ignored here.
            let requested = req
                .get("params")
                .and_then(|p| p.get("protocolVersion"))
                .and_then(|v| v.as_str());
            Ok(json!({
                "protocolVersion": negotiate_protocol_version(requested),
                "capabilities": { "tools": {} },
                "serverInfo": { "name": "divoom-control", "version": env!("CARGO_PKG_VERSION") },
            }))
        }
        "notifications/initialized" => return None,
        "ping" => Ok(json!({})),
        "tools/list" => Ok(json!({ "tools": crate::mcp_tools::catalog() })),
        "tools/call" => {
            let params = req.get("params").cloned().unwrap_or_else(|| json!({}));
            let name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let args = params
                .get("arguments")
                .cloned()
                .unwrap_or_else(|| json!({}));
            match crate::mcp_tools::call_tool(name, &args, target).await {
                Ok(value) => Ok(tool_content(&value, false)),
                // Tool-level errors are returned as a result with isError, per MCP.
                Err(e) => Ok(tool_content(&json!({ "error": e }), true)),
            }
        }
        other => Err((-32601, format!("method not found: {other}"))),
    };

    if is_notification {
        return None;
    }
    Some(match result {
        Ok(r) => ok(&id, r),
        Err((code, msg)) => err(&id, code, &msg),
    })
}

/// Wrap a tool result value into the MCP tools/call result shape.
fn tool_content(value: &Value, is_error: bool) -> Value {
    let text = serde_json::to_string(value).unwrap_or_else(|_| "{}".to_string());
    json!({
        "content": [ { "type": "text", "text": text } ],
        "isError": is_error,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mcp_daemon::fake::{unreachable, FakeDaemon};

    fn req(method: &str, params: &Value) -> String {
        serde_json::to_string(&json!({
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params
        }))
        .expect("serialize request")
    }

    #[test]
    fn negotiation_echoes_supported_and_falls_back_to_latest() {
        for v in SUPPORTED_PROTOCOL_VERSIONS {
            assert_eq!(negotiate_protocol_version(Some(v)), *v);
        }
        assert_eq!(negotiate_protocol_version(Some("2026-07-28")), "2026-07-28");
        assert_eq!(
            negotiate_protocol_version(Some("2099-01-01")),
            PROTOCOL_VERSION
        );
        assert_eq!(negotiate_protocol_version(None), PROTOCOL_VERSION);
    }

    // ── the JSON-RPC envelope ────────────────────────────────────────────────
    //
    // These replace `tests/test_mcp_server.py`, which pinned the same
    // behaviours against the Python implementation this server replaced. A
    // protocol test that only ever ran on the implementation being deleted is
    // not coverage of the one that ships.

    #[tokio::test]
    async fn a_malformed_line_is_a_parse_error() {
        let reply = handle_line("{not json", &unreachable())
            .await
            .expect("a parse error is still a reply");
        assert_eq!(reply["error"]["code"], json!(-32700));
    }

    #[tokio::test]
    async fn a_wrong_jsonrpc_version_is_an_invalid_request() {
        let line = r#"{"jsonrpc":"1.0","id":7,"method":"ping"}"#;
        let reply = handle_line(line, &unreachable()).await.expect("reply");
        assert_eq!(reply["error"]["code"], json!(-32600));
        assert_eq!(reply["id"], json!(7), "the id must survive to be matched");
    }

    #[tokio::test]
    async fn an_unknown_method_is_method_not_found() {
        let reply = handle_line(&req("no/such/method", &json!({})), &unreachable())
            .await
            .expect("reply");
        assert_eq!(reply["error"]["code"], json!(-32601));
    }

    #[tokio::test]
    async fn a_notification_gets_no_reply_at_all() {
        // Both spellings: the MCP `notifications/initialized`, and any request
        // that simply omits `id`. Answering a notification corrupts the client's
        // request/response pairing, so "no reply" is the only correct answer.
        let init = r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#;
        assert!(handle_line(init, &unreachable()).await.is_none());
        let ping_without_id = r#"{"jsonrpc":"2.0","method":"ping"}"#;
        assert!(handle_line(ping_without_id, &unreachable()).await.is_none());
    }

    #[tokio::test]
    async fn ping_is_an_empty_result() {
        let reply = handle_line(&req("ping", &json!({})), &unreachable())
            .await
            .expect("reply");
        assert_eq!(reply["result"], json!({}));
        assert!(reply.get("error").is_none());
    }

    #[tokio::test]
    async fn initialize_reports_server_info_and_the_tools_capability() {
        let reply = handle_line(&req("initialize", &json!({})), &unreachable())
            .await
            .expect("reply");
        let result = &reply["result"];
        assert_eq!(result["serverInfo"]["name"], json!("divoom-control"));
        assert_eq!(result["serverInfo"]["version"], env!("CARGO_PKG_VERSION"));
        assert!(result["capabilities"]["tools"].is_object());
    }

    #[tokio::test]
    async fn initialize_negotiates_over_the_wire_and_tolerates_meta() {
        for v in SUPPORTED_PROTOCOL_VERSIONS {
            let line = req(
                "initialize",
                &json!({ "protocolVersion": v, "_meta": { "anything": [1, 2] } }),
            );
            let reply = handle_line(&line, &unreachable()).await.expect("reply");
            assert_eq!(reply["result"]["protocolVersion"], json!(*v));
        }
        // Unknown and absent both get the latest, and an unrecognised version
        // must NOT be echoed — a client sent a version we cannot honour.
        let unknown = req("initialize", &json!({ "protocolVersion": "2099-01-01" }));
        let reply = handle_line(&unknown, &unreachable()).await.expect("reply");
        assert_eq!(reply["result"]["protocolVersion"], json!(PROTOCOL_VERSION));
    }

    #[tokio::test]
    async fn tools_list_is_the_whole_catalog() {
        let reply = handle_line(&req("tools/list", &json!({})), &unreachable())
            .await
            .expect("reply");
        let tools = reply["result"]["tools"].as_array().expect("tools array");
        assert_eq!(tools.len(), 14);
        let names: Vec<&str> = tools
            .iter()
            .map(|t| t["name"].as_str().expect("tool name"))
            .collect();
        // `list_screens` is the tool the Python catalog never had: the strict
        // superset is why the Python one could go.
        assert!(names.contains(&"list_screens"), "{names:?}");
        for t in tools {
            assert!(
                t["description"].as_str().is_some_and(|d| !d.is_empty()),
                "every tool needs a description: {t}"
            );
            assert!(t["inputSchema"].is_object(), "{t}");
        }
    }

    // ── tools/call: the error contract ──────────────────────────────────────

    #[tokio::test]
    async fn an_unknown_tool_is_a_tool_error_not_a_protocol_error() {
        // MCP: an unknown tool is a RESULT with isError, not -32601. A client
        // showing "method not found" to a user is a worse failure than a tool
        // error it can attribute to the tool name.
        let line = req(
            "tools/call",
            &json!({ "name": "no_such_tool", "arguments": {} }),
        );
        let reply = handle_line(&line, &unreachable()).await.expect("reply");
        assert!(
            reply.get("error").is_none(),
            "must not be a protocol error: {reply}"
        );
        assert_eq!(reply["result"]["isError"], json!(true));
    }

    #[tokio::test]
    async fn a_missing_required_argument_is_a_tool_error() {
        let line = req(
            "tools/call",
            &json!({ "name": "set_volume", "arguments": {} }),
        );
        let reply = handle_line(&line, &unreachable()).await.expect("reply");
        assert_eq!(reply["result"]["isError"], json!(true));
        let text = reply["result"]["content"][0]["text"]
            .as_str()
            .unwrap_or_default();
        assert!(
            text.contains("level"),
            "the message must name the argument: {text}"
        );
    }

    #[tokio::test]
    async fn a_valid_call_reaches_the_daemon_and_returns_text_content() {
        let daemon = FakeDaemon::start(json!({}), None).await;
        let line = req(
            "tools/call",
            &json!({ "name": "set_volume", "arguments": { "level": 7 } }),
        );
        let reply = handle_line(&line, &daemon.target).await.expect("reply");
        assert_eq!(reply["result"]["isError"], json!(false));
        assert_eq!(reply["result"]["content"][0]["type"], json!("text"));

        let seen = daemon.requests();
        assert_eq!(seen.len(), 1, "exactly one daemon request");
        assert_eq!(seen[0]["command"], json!("device_call"));
        assert_eq!(seen[0]["args"]["method"], json!("music.set_volume"));
        assert_eq!(seen[0]["args"]["args"], json!([7]));
    }

    // ── the stdio guard ─────────────────────────────────────────────────────

    #[test]
    fn a_regular_file_is_not_a_pipe_but_the_pipe_kinds_are() {
        // Both directions. A guard that only ever accepted would also pass.
        use std::ffi::CString;
        use std::os::fd::FromRawFd;

        let dir = std::env::temp_dir().join(format!("divoom-pipe-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("temp dir");

        // A regular file: the `> out.txt` case the guard exists for.
        let file_path = dir.join("out.txt");
        std::fs::write(&file_path, b"x").expect("write file");
        let file = std::fs::File::open(&file_path).expect("open file");
        let fd = std::os::fd::AsRawFd::as_raw_fd(&file);
        assert!(
            !fd_is_pipe_like(fd),
            "a redirected stdout must be rejected, or the server tracebacks on write"
        );

        // A FIFO, opened read-write so opening it cannot block.
        let fifo_path = dir.join("pipe");
        let fifo_c = CString::new(fifo_path.to_str().expect("utf8 path")).expect("cstring");
        // SAFETY: creating a FIFO at a path this test owns, in a directory it
        // created; no memory is shared and `fifo_c` outlives the call.
        assert_eq!(unsafe { libc::mkfifo(fifo_c.as_ptr(), 0o600) }, 0);
        // SAFETY: `O_RDWR` on a FIFO does not block waiting for a peer, and the
        // returned descriptor is owned by the `File` that adopts it below.
        let fifo_fd = unsafe { libc::open(fifo_c.as_ptr(), libc::O_RDWR | libc::O_NONBLOCK) };
        assert!(fifo_fd >= 0, "open the fifo");
        // SAFETY: `fifo_fd` is a fresh descriptor from `open` above; handing it to
        // `File` transfers ownership, so it is closed exactly once, on drop.
        let fifo = unsafe { std::fs::File::from_raw_fd(fifo_fd) };
        assert!(
            fd_is_pipe_like(std::os::fd::AsRawFd::as_raw_fd(&fifo)),
            "a real pipe is exactly what an MCP client provides"
        );

        // A character device: /dev/null, and a terminal is one too.
        let null = std::fs::File::open("/dev/null").expect("open /dev/null");
        assert!(fd_is_pipe_like(std::os::fd::AsRawFd::as_raw_fd(&null)));

        // A socket: what a client on the other side of a socketpair gives us.
        // SAFETY: a socketpair is two descriptors; both are adopted by `File`s.
        let mut pair = [0 as libc::c_int; 2];
        assert_eq!(
            unsafe { libc::socketpair(libc::AF_UNIX, libc::SOCK_STREAM, 0, pair.as_mut_ptr()) },
            0
        );
        // SAFETY: `pair[0]` is a fresh descriptor from the socketpair above;
        // `File` takes ownership and closes it once, on drop.
        let sock = unsafe { std::fs::File::from_raw_fd(pair[0]) };
        assert!(fd_is_pipe_like(std::os::fd::AsRawFd::as_raw_fd(&sock)));

        // A closed descriptor: nothing to read, so not pipe-like. This is the
        // case that would otherwise be a panic or a hang.
        assert!(!fd_is_pipe_like(-1));

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_diagnostic_names_the_fix() {
        // Someone reading this in a bare log has to learn what to do next.
        assert!(NOT_A_PIPE.contains("MCP client"));
        assert!(NOT_A_PIPE.contains("docs/MCP_SERVER.md"));
    }
}
