//! Native MCP server — stdio JSON-RPC bridge to the running daemon. Ported from
//! `divoom_lib/mcp_server.py` + `mcp_tools.py`. Run as `divoomd mcp`: it does NOT
//! own the device; it connects to the daemon's unix socket (DIVOOM_SOCKET, default
//! /tmp/divoom.sock) and forwards each `tools/call` as a `device_call`/command —
//! the same daemon-routed model as the Python R28 MCP-via-daemon.
//!
//! Protocol: line-delimited JSON-RPC 2.0 on stdin/stdout. Methods: initialize,
//! tools/list, tools/call, ping. Tool catalog + dispatch live in `mcp_tools`.

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

const PROTOCOL_VERSION: &str = "2024-11-05";

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

fn ok(id: Value, result: Value) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "result": result })
}

fn err(id: Value, code: i64, message: &str) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "error": { "code": code, "message": message } })
}

async fn handle_line(line: &str, sock: &str) -> Option<Value> {
    let req: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(e) => return Some(err(Value::Null, -32700, &format!("parse error: {e}"))),
    };
    if req.get("jsonrpc").and_then(|v| v.as_str()) != Some("2.0") {
        return Some(err(
            req.get("id").cloned().unwrap_or(Value::Null),
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
        "initialize" => Ok(json!({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": { "tools": {} },
            "serverInfo": { "name": "divoom-control", "version": env!("CARGO_PKG_VERSION") },
        })),
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
        Ok(r) => ok(id, r),
        Err((code, msg)) => err(id, code, &msg),
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
