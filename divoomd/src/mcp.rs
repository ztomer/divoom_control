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

/// # Errors
///
/// From the transport it serves on: stdin closed, or a reply could not be
/// written.
pub async fn run() -> std::io::Result<()> {
    let sock = std::env::var("DIVOOM_SOCKET").unwrap_or_else(|_| "/tmp/divoom.sock".to_string());
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
        if let Some(resp) = handle_line(&line, &sock).await {
            let mut out = serde_json::to_vec(&resp).unwrap_or_default();
            out.push(b'\n');
            stdout.write_all(&out).await?;
            stdout.flush().await?;
        }
    }
    Ok(())
}

#[expect(
    clippy::needless_pass_by_value,
    reason = "the result is moved into the reply object being built; borrowing it would mean cloning it straight back out"
)]
fn ok(id: &Value, result: Value) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "result": result })
}

fn err(id: &Value, code: i64, message: &str) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "error": { "code": code, "message": message } })
}

async fn handle_line(line: &str, sock: &str) -> Option<Value> {
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
            match crate::mcp_tools::call_tool(name, &args, sock).await {
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
}
