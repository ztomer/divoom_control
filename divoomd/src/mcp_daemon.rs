//! Request/reply plumbing to the daemon, for the MCP tools.
//!
//! Split out of `mcp_tools.rs` on 2026-09-25 at the 500-line cap, at the seam
//! that had just become real: everything here speaks to a `DaemonTarget`
//! (local unix socket or remote TCP with a token), and everything there is the
//! MCP surface — the tool catalog and what each tool means. The two were one
//! file when the connection was a path in a string.
//!
//! The request/reply is one NDJSON line each way, with `token` added when the
//! target is remote and configured with one. The shape is the daemon's existing
//! RPC contract, not a new one; see `crate::daemon_target` and
//! `divoom_client/daemon_protocol.py`.

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpStream, UnixStream};

use crate::daemon_target::DaemonTarget;
use crate::error_code::ToolError;

/// The two halves of a connection, boxed so a unix socket and a TCP socket
/// share one signature. Boxed rather than an enum of half-pairs because
/// nothing downstream can tell them apart — this is a request, a reply, close.
type DaemonRead = Box<dyn tokio::io::AsyncRead + Send + Unpin>;
type DaemonWrite = Box<dyn tokio::io::AsyncWrite + Send + Unpin>;

/// Open a request/reply pair to the daemon, whichever way it is addressed.
async fn connect(target: &DaemonTarget) -> Result<(DaemonRead, DaemonWrite), String> {
    match target {
        DaemonTarget::Unix(path) => {
            let stream = UnixStream::connect(path)
                .await
                .map_err(|e| format!("daemon not reachable at {path}: {e}"))?;
            let (read, write) = stream.into_split();
            Ok((Box::new(read), Box::new(write)))
        }
        DaemonTarget::Remote { host, port, .. } => {
            let stream = TcpStream::connect((host.as_str(), *port))
                .await
                .map_err(|e| format!("daemon not reachable at {host}:{port}: {e}"))?;
            let (read, write) = stream.into_split();
            Ok((Box::new(read), Box::new(write)))
        }
    }
}

tokio::task_local! {
    /// The screen lease the current tool call carries (P4.6), if any.
    static LEASE: Option<String>;
}

/// Run one tool call with `lease` as the token on every `device_call` it
/// makes. A task-local rather than a parameter threaded through every tool:
/// the lease is a property of the CALL, and a tool that forgot to thread it
/// would be refused by its own lease -- the class this rules out.
pub(crate) async fn with_lease<F: std::future::Future>(lease: Option<String>, f: F) -> F::Output {
    LEASE.scope(lease, f).await
}

/// The one `device_call` request every tool sends: method, arguments, the
/// panel, and the current call's lease token.
fn device_call(method: &str, args: Value, kwargs: Option<Value>, mac: Option<&str>) -> Value {
    let mut payload = json!({ "method": method });
    payload["args"] = args;
    if let Some(k) = kwargs {
        payload["kwargs"] = k;
    }
    if let Some(m) = mac {
        payload["mac"] = json!(m);
    }
    if let Some(t) = LEASE.try_with(Clone::clone).ok().flatten() {
        payload["token"] = json!(t);
    }
    payload
}

/// `device_call` with positional args; errors if the daemon reports failure.
pub(crate) async fn dc(
    target: &DaemonTarget,
    method: &str,
    args: Value,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    check(cmd(target, "device_call", device_call(method, args, None, mac)).await?)
}

/// `device_call` with positional AND keyword args.
pub(crate) async fn dc_args_kw(
    target: &DaemonTarget,
    method: &str,
    args: Value,
    kwargs: Value,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    check(
        cmd(
            target,
            "device_call",
            device_call(method, args, Some(kwargs), mac),
        )
        .await?,
    )
}

/// `device_call` with keyword args.
pub(crate) async fn dc_kw(
    target: &DaemonTarget,
    method: &str,
    kwargs: Value,
    mac: Option<&str>,
) -> Result<Value, ToolError> {
    check(
        cmd(
            target,
            "device_call",
            device_call(method, json!([]), Some(kwargs), mac),
        )
        .await?,
    )
}

/// `device_call` returning the `result` value -- or the failure, never a
/// null value in its place (P2.8).
///
/// Three answers, kept apart because they mean three different things:
///
/// * `Ok(Some(v))` -- the panel answered, and this is its value;
/// * `Ok(None)` -- the daemon is not reachable at all: the client has no
///   data, and a read tool answers nulls for that (the shape the tool has
///   always had, and the reason a null is not a reading);
/// * `Err(e)` -- the daemon answered and REFUSED: the panel is there and did
///   not do what was asked. That used to come back as a null too, which made
///   a dropped panel and a panel with no value look the same.
pub(crate) async fn dc_result(
    target: &DaemonTarget,
    method: &str,
    args: Value,
    mac: Option<&str>,
) -> Result<Option<Value>, ToolError> {
    // The daemon is not reachable: no data, which is not a failure of
    // this read and is answered as such by the caller.
    let Ok(reply) = cmd(target, "device_call", device_call(method, args, None, mac)).await else {
        return Ok(None);
    };
    check(reply).and_then(|v| {
        v.get("result").cloned().map(Some).ok_or_else(|| {
            ToolError::from(format!("{method}: the daemon's reply carried no result"))
        })
    })
}

pub(crate) fn check(reply: Value) -> Result<Value, ToolError> {
    if reply.get("success").and_then(serde_json::Value::as_bool) == Some(true) {
        Ok(reply)
    } else {
        Err(ToolError::from_reply(&reply, "device call failed"))
    }
}

/// [`cmd`], refused unless the daemon said `success` -- its `code` kept.
pub(crate) async fn cmd_ok(
    target: &DaemonTarget,
    command: &str,
    args: Value,
) -> Result<Value, ToolError> {
    check(cmd(target, command, args).await?)
}

/// One NDJSON request/reply against the daemon, local socket or remote TCP.
///
/// The target is a `DaemonTarget` rather than a path so an editor's MCP config
/// pointing at a daemon on another machine works the same way it did through the
/// Python shell this replaced — see `crate::daemon_target`.
pub(crate) async fn cmd(
    target: &DaemonTarget,
    command: &str,
    args: Value,
) -> Result<Value, String> {
    let line = target.request_line(command, &args)?;
    let (read, mut write) = connect(target).await?;
    write.write_all(&line).await.map_err(|e| e.to_string())?;
    write.flush().await.map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(read);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .await
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&line).map_err(|e| format!("bad reply: {e}"))
}

#[cfg(test)]
pub(crate) mod fake {
    //! A real socket that speaks the daemon's NDJSON, for headless tests.
    //!
    //! Real listener, real framing, canned replies — and it RECORDS what it was
    //! sent, so a test can assert the bytes rather than only that a call
    //! returned. This is as close as a test without a device gets to a daemon,
    //! and it is what turns "the tool reached the wire" into a check instead of
    //! a hope.
    //!
    //! It serves indefinitely rather than for a declared number of requests, and
    //! [`FakeDaemon::requests`] never waits on the server task. The first
    //! version took a request count and joined the task, which meant a test that
    //! made one call fewer than it declared hung until the harness timed out
    //! rather than failing — the worst possible failure mode, because the
    //! assertion that would have explained it never ran.

    use super::DaemonTarget;
    use serde_json::{json, Value};
    use std::sync::{Arc, Mutex};
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    use tokio::net::TcpListener;

    /// A target nothing is listening on, for the paths that must reject input
    /// BEFORE any I/O. Validation has to be provable without a daemon, or it is
    /// only provable when a device is plugged in — and a test that reaches the
    /// network instead of failing locally is testing the wrong thing.
    pub fn unreachable() -> DaemonTarget {
        DaemonTarget::Unix("/nonexistent/divoom-test.sock".to_string())
    }

    pub struct FakeDaemon {
        /// A target pointing at this fake, ready to hand to `call_tool`.
        pub target: DaemonTarget,
        seen: Arc<Mutex<Vec<Value>>>,
    }

    impl FakeDaemon {
        /// Answer every request with `{"success": true, "result": <result>}`.
        pub async fn start(result: Value, token: Option<&str>) -> Self {
            Self::replying(json!({ "success": true, "result": result }), token).await
        }

        /// Answer request `i` with `replies[i]`, the last one for the rest:
        /// a daemon that grants the first steps of a sequence and refuses a
        /// later one, so the caller's clean-up path can be watched.
        pub async fn scripted(replies: Vec<Value>) -> Self {
            Self::serve(
                Box::new(move |i| {
                    replies
                        .get(i)
                        .or_else(|| replies.last())
                        .cloned()
                        .unwrap_or(Value::Null)
                }),
                None,
            )
            .await
        }

        /// Answer every request with exactly `reply`.
        ///
        /// Needed because a daemon that REFUSES is a different case from an
        /// unreachable one, and it is the case users actually hit: the socket is
        /// right there answering `{"success": false, "error": "no device
        /// connected"}`. Nothing covered it until a verb test needed it — a
        /// client that treats any parseable reply as success would pass every
        /// test written against the success shape.
        pub async fn replying(reply: Value, token: Option<&str>) -> Self {
            Self::serve(Box::new(move |_| reply.clone()), token).await
        }

        async fn serve(
            reply: Box<dyn Fn(usize) -> Value + Send + Sync>,
            token: Option<&str>,
        ) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0")
                .await
                .expect("bind an ephemeral port");
            let port = listener.local_addr().expect("local addr").port();
            let seen = Arc::new(Mutex::new(Vec::new()));
            let sink = Arc::clone(&seen);
            tokio::spawn(async move {
                while let Ok((stream, _)) = listener.accept().await {
                    let (read, mut write) = stream.into_split();
                    let mut reader = BufReader::new(read);
                    let mut line = String::new();
                    if reader.read_line(&mut line).await.is_err() {
                        continue;
                    }
                    let mut index = 0;
                    if let Ok(v) = serde_json::from_str(line.trim()) {
                        // Recorded BEFORE the reply: once a call has returned, its
                        // request is guaranteed to be visible to `requests()`.
                        if let Ok(mut guard) = sink.lock() {
                            index = guard.len();
                            guard.push(v);
                        }
                    }
                    let mut bytes = serde_json::to_vec(&reply(index)).unwrap_or_default();
                    bytes.push(b'\n');
                    // A client that hung up mid-reply ends the connection on
                    // its own; there is nothing to recover and nothing to report.
                    let _ = write.write_all(&bytes).await;
                }
            });
            Self {
                target: DaemonTarget::Remote {
                    host: "127.0.0.1".to_string(),
                    port,
                    token: token.map(str::to_string),
                },
                seen,
            }
        }

        /// What the daemon actually received, in order. Synchronous, and never
        /// blocks: the answer to everything this daemon was sent.
        #[must_use]
        pub fn requests(&self) -> Vec<Value> {
            self.seen.lock().map(|g| g.clone()).unwrap_or_default()
        }
    }
}
