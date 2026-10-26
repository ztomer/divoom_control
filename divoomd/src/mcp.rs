//! Native MCP server, on rmcp (the official Rust MCP SDK) -- a stdio client
//! of the running daemon.
//!
//! Run as `divoomd mcp [--allow-destructive]`: it does NOT own a device; each
//! `tools/call` is forwarded to the daemon's unix socket (`DIVOOM_SOCKET`,
//! default /tmp/divoom.sock) or a remote daemon (`DIVOOM_DAEMON_HOST`/`_PORT`/
//! `_TOKEN`) as a `device_call` or a command -- the daemon-routed model the
//! Python R28 server had.
//!
//! Until lane MCP.DV this file was a hand-rolled JSON-RPC loop: its own
//! framing, version table and `tools/call` envelope. That is upstream's to
//! keep now (owner ruling OW.60). What is left is what only divoomd can say:
//! which tools exist and what each does to the world (`crate::mcp_catalog`,
//! declared beside each tool), and how a call reaches the daemon
//! (`crate::mcp_tools::call_tool`). The decisions are in [`DivoomMcp::tools`]
//! and [`DivoomMcp::call`]; the `ServerHandler` impl is a thin adapter.

use std::sync::Arc;

use rmcp::model::{
    CallToolRequestParams, CallToolResponse, CallToolResult, ContentBlock, Implementation,
    JsonObject, ListToolsResult, PaginatedRequestParams, ServerCapabilities, ServerConfig, Tool,
};
use rmcp::service::RequestContext;
use rmcp::{ErrorData, RoleServer, ServerHandler, ServiceExt};
use serde_json::{json, Value};

use crate::daemon_target::DaemonTarget;
use crate::error_code::ToolError;

/// What a started server offers.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Options {
    /// Offer the tools whose effect is `Destructive` (`crate::mcp_catalog`):
    /// they overwrite panel state the daemon cannot read back. Off unless
    /// the server is started with `--allow-destructive`.
    pub allow_destructive: bool,
}

/// The MCP face of the tool catalog, over one daemon target.
#[derive(Clone)]
pub struct DivoomMcp {
    target: Arc<DaemonTarget>,
    options: Options,
}

impl DivoomMcp {
    #[must_use]
    pub fn new(target: DaemonTarget, options: Options) -> Self {
        Self {
            target: Arc::new(target),
            options,
        }
    }

    /// The catalog entries this session offers, as MCP's JSON.
    fn offered(&self) -> Vec<Value> {
        let all = crate::mcp_tools::catalog();
        all.as_array()
            .into_iter()
            .flatten()
            .filter(|t| self.options.allow_destructive || !crate::mcp_catalog::is_destructive(t))
            .cloned()
            .collect()
    }

    /// The tools this server lists: the catalog minus the destructive ones
    /// unless opted in, each with its annotations and output schema.
    #[must_use]
    pub fn tools(&self) -> Vec<Tool> {
        self.offered()
            .into_iter()
            .filter_map(|t| serde_json::from_value(t).ok())
            .collect()
    }

    /// Run one tool call. A failure of the TOOL is an `isError` result the
    /// model can read -- the JSON `{"error", "code"}` the daemon's refusal
    /// carried -- never a protocol error.
    pub async fn call(&self, name: &str, arguments: Option<JsonObject>) -> CallToolResult {
        let all = crate::mcp_tools::catalog();
        let entry = all
            .as_array()
            .and_then(|a| a.iter().find(|t| t["name"] == json!(name)));
        if entry.is_some_and(crate::mcp_catalog::is_destructive) && !self.options.allow_destructive
        {
            return failure(&ToolError {
                message: format!(
                    "{name} overwrites panel state the daemon cannot read back and is not \
                     enabled on this server; start it with `divoomd mcp --allow-destructive`"
                ),
                code: Some("not_enabled".to_string()),
            });
        }
        let args = Value::Object(arguments.unwrap_or_default());
        let target = Arc::clone(&self.target);
        let tool = name.to_string();
        // On its own task, so a panic in one call is that call's error and
        // never ends the session.
        let ran = tokio::spawn(async move {
            if tool == crate::mcp_preview::NAME {
                crate::mcp_preview::call(&args, &target)
                    .await
                    .map(preview_result)
            } else {
                crate::mcp_tools::call_tool(&tool, &args, &target)
                    .await
                    .map(|v| success(v, Vec::new()))
            }
        })
        .await;
        match ran {
            Ok(Ok(result)) => result,
            Ok(Err(e)) => failure(&e),
            Err(e) => failure(&ToolError::from(format!("internal error in {name}: {e}"))),
        }
    }
}

/// A success: the compact JSON text every client reads (the text the
/// hand-rolled server sent), the same object as `structuredContent` for the
/// clients that validate it against the tool's `outputSchema`, then any
/// images. The schema promises an object, so anything else is wrapped.
fn success(value: Value, images: Vec<ContentBlock>) -> CallToolResult {
    let structured = match value {
        Value::Object(_) => value,
        other => json!({ "result": other }),
    };
    let mut content = vec![ContentBlock::text(structured.to_string())];
    content.extend(images);
    let mut result = CallToolResult::success(content);
    result.structured_content = Some(structured);
    result
}

fn preview_result(p: crate::mcp_preview::Preview) -> CallToolResult {
    let images = p
        .images
        .into_iter()
        .map(|i| ContentBlock::image(i.data, i.mime))
        .collect();
    success(p.structured, images)
}

fn failure(e: &ToolError) -> CallToolResult {
    CallToolResult::error(vec![ContentBlock::text(e.to_json().to_string())])
}

impl ServerHandler for DivoomMcp {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build()).with_server_info(
            Implementation::new("divoom-control", env!("CARGO_PKG_VERSION")),
        )
    }

    fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> impl std::future::Future<Output = Result<ListToolsResult, ErrorData>> {
        std::future::ready(Ok(ListToolsResult {
            tools: self.tools(),
            ..ListToolsResult::default()
        }))
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        Ok(self.call(&request.name, request.arguments).await.into())
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

/// Serve MCP on stdio until the client closes stdin.
///
/// # Errors
///
/// When the transport fails: the session could not start, or ended on an
/// I/O error rather than the client closing it.
pub async fn run(options: Options) -> std::io::Result<()> {
    if !fd_is_pipe_like(libc::STDIN_FILENO) || !fd_is_pipe_like(libc::STDOUT_FILENO) {
        eprintln!("{NOT_A_PIPE}");
        return Ok(());
    }
    // One target for the process, chosen from the environment, so
    // `DIVOOM_DAEMON_HOST`/`_PORT`/`_TOKEN` reach a daemon on another machine.
    let service = DivoomMcp::new(DaemonTarget::from_env(), options)
        .serve(rmcp::transport::stdio())
        .await
        .map_err(std::io::Error::other)?;
    service.waiting().await.map_err(std::io::Error::other)?;
    Ok(())
}

#[cfg(test)]
#[path = "mcp_tests.rs"]
mod tests;
