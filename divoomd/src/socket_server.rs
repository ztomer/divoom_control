//! Unix-socket NDJSON server — the request/reply transport, ported from
//! the archived Python socket_server.py. This is the conformance seam: a client (the
//! Python GUI/menubar/CLI, or the Python test suite as an oracle) connects, sends
//! one `{"command","args","token"?}` line, and reads one reply line.
//!
//! The device/command logic is injected through the [`Handler`] trait so this
//! transport is fully testable without hardware: the real daemon plugs in the
//! device owner; tests plug in a stub.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixListener;
use tokio::sync::Semaphore;

use crate::protocol::{encode_message, err_reply, iter_messages, Request, MAX_REPLY_BYTES};

/// Max concurrent client connections. A 6th+ connection is back-pressured (the
/// accept loop waits for a free permit) rather than unbounded — a runaway or
/// hostile client can't exhaust fds/tasks. Tunable via `DIVOOMD_MAX_CONNECTIONS`.
pub const MAX_CONNECTIONS: usize = 64;

/// Drop a connection that sends nothing for this long (no newline-terminated
/// request). Closes the "connect and hold the socket open silently" wedge where a
/// dead client pins a permit + the device lock forever. Tunable via
/// `DIVOOMD_IDLE_TIMEOUT_SECS`.
pub const CONNECTION_IDLE_TIMEOUT: Duration = Duration::from_secs(300);

/// Dispatches a parsed request to a reply. Object-safe + Send-explicit so each
/// connection can be served on its own task. The real implementation routes to the
/// device owner / command queue; tests use a stub.
pub trait Handler: Send + Sync + 'static {
    fn handle<'a>(&'a self, req: Request) -> Pin<Box<dyn Future<Output = Value> + Send + 'a>>;
    /// Get a receiver for the broadcast event stream.
    fn subscribe(&self) -> Option<tokio::sync::broadcast::Receiver<Value>> {
        None
    }
    /// Get the initial status event to send immediately on subscribe.
    fn initial_status(&self) -> Value {
        serde_json::json!({
            "type": "status",
            "state": "idle",
            "connected": false,
            "counters": {}
        })
    }
}

/// Serve a single connection: accumulate bytes, split into NDJSON requests,
/// dispatch each, and write back one reply line per request. Returns when the peer
/// closes (EOF) or on an I/O error. A peer that never sends a newline can't grow
/// the buffer past `MAX_REPLY_BYTES` (the connection is dropped instead).
fn constant_time_eq(a: &str, b: &str) -> bool {
    let a_bytes = a.as_bytes();
    let b_bytes = b.as_bytes();
    if a_bytes.len() != b_bytes.len() {
        return false;
    }
    let mut result = 0;
    for (x, y) in a_bytes.iter().zip(b_bytes.iter()) {
        result |= x ^ y;
    }
    result == 0
}

/// Serve a single connection: accumulate bytes, split into NDJSON requests,
/// dispatch each, and write back one reply line per request. Returns when the peer
/// closes (EOF) or on an I/O error. A peer that never sends a newline can't grow
/// the buffer past `MAX_REPLY_BYTES` (the connection is dropped instead).
pub async fn serve_connection<S, H>(
    mut stream: S,
    handler: Arc<H>,
    require_auth: bool,
    token: Option<String>,
    idle_timeout: Duration,
) -> std::io::Result<()>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    H: Handler,
{
    let mut buf: Vec<u8> = Vec::new();
    let mut tmp = [0u8; 4096];
    loop {
        let n = match tokio::time::timeout(idle_timeout, stream.read(&mut tmp)).await {
            Ok(Ok(0)) => return Ok(()), // EOF — peer closed
            Ok(Ok(k)) => k,
            Ok(Err(e)) => return Err(e),
            Err(_) => return Ok(()), // idle: dead/silent peer, drop
        };
        buf.extend_from_slice(&tmp[..n]);
        if buf.len() > MAX_REPLY_BYTES {
            return Ok(()); // frame cap: a never-newline-terminated frame, drop it
        }
        let (msgs, remainder) = iter_messages(&buf);
        buf = remainder;
        for msg in msgs {
            // A line that failed to PARSE now gets an answer too. Silence was
            // indistinguishable from a hung daemon.
            let msg = match msg {
                Ok(v) => v,
                Err(reason) => {
                    let reply = err_reply(&format!("bad request: {reason}"));
                    stream.write_all(&encode_message(&reply)).await?;
                    continue;
                }
            };
            let req = match serde_json::from_value::<Request>(msg) {
                Ok(req) => req,
                Err(_) => {
                    let reply =
                        err_reply("bad request: expected an object with a 'command' string");
                    stream.write_all(&encode_message(&reply)).await?;
                    continue;
                }
            };
            if require_auth {
                let supplied = req.token.as_deref().unwrap_or("");
                let server_token = token.as_deref().unwrap_or("");
                if server_token.is_empty() || !constant_time_eq(supplied, server_token) {
                    let reply = err_reply("unauthorized");
                    stream.write_all(&encode_message(&reply)).await?;
                    continue;
                }
            }
            if req.command == "subscribe" {
                if let Some(mut rx) = handler.subscribe() {
                    let initial = handler.initial_status();
                    stream.write_all(&encode_message(&initial)).await?;
                    // Idle watchdog: a subscriber that receives no events for
                    // `idle_timeout` is dropped (releasing its permit), so a silent
                    // client can't pin a slot forever. Any delivered event resets it.
                    let mut deadline = tokio::time::Instant::now() + idle_timeout;
                    loop {
                        tokio::select! {
                            n = stream.read(&mut tmp) => {
                                match n {
                                    Ok(0) => break, // EOF
                                    Err(_) => break, // error
                                    Ok(_) => {}, // ignore client input after subscribe
                                }
                            }
                            msg = rx.recv() => {
                                match msg {
                                    Ok(event) => {
                                        stream.write_all(&encode_message(&event)).await?;
                                        deadline = tokio::time::Instant::now() + idle_timeout;
                                    }
                                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {}
                                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                                        break;
                                    }
                                }
                            }
                            _ = tokio::time::sleep_until(deadline) => break, // idle: drop
                        }
                    }
                    return Ok(());
                } else {
                    let reply = err_reply("subscriptions not supported");
                    stream.write_all(&encode_message(&reply)).await?;
                    continue;
                }
            }
            let reply = handler.handle(req).await;
            stream.write_all(&encode_message(&reply)).await?;
        }
    }
}

/// Accept connections forever on Unix socket, serving each on its own task. Runs until the
/// listener errors unrecoverably (callers normally `tokio::spawn` this). Concurrent connections
/// are capped by `max_connections` (back-pressure: the accept loop waits for a free permit).
///
/// Takes an `Arc` rather than the listener itself: the socket must outlive this
/// future so the daemon can still identify its own socket file at shutdown (see
/// [`crate::socket_owner`]). An earlier version borrowed it to force that, which
/// only moved the problem into every caller's lifetimes — `tokio::spawn` needs
/// `'static`, so the tests each had to `Box::leak` a listener to compile.
pub async fn serve<H: Handler>(
    listener: Arc<UnixListener>,
    handler: Arc<H>,
    max_connections: usize,
    idle_timeout: Duration,
) {
    let sem = Arc::new(Semaphore::new(max_connections.max(1)));
    loop {
        match listener.accept().await {
            Ok((stream, _addr)) => {
                let permit = match sem.clone().acquire_owned().await {
                    Ok(p) => p,
                    Err(_) => return, // semaphore closed
                };
                let h = handler.clone();
                tokio::spawn(async move {
                    let _permit = permit; // held for the connection's lifetime
                    let _ = serve_connection(stream, h, false, None, idle_timeout).await;
                });
            }
            Err(_) => continue,
        }
    }
}

/// Accept connections forever on TCP socket, serving each on its own task.
pub async fn serve_tcp<H: Handler>(
    listener: tokio::net::TcpListener,
    handler: Arc<H>,
    token: String,
    max_connections: usize,
    idle_timeout: Duration,
) {
    let sem = Arc::new(Semaphore::new(max_connections.max(1)));
    loop {
        match listener.accept().await {
            Ok((stream, _addr)) => {
                let permit = match sem.clone().acquire_owned().await {
                    Ok(p) => p,
                    Err(_) => return,
                };
                let h = handler.clone();
                let t = token.clone();
                tokio::spawn(async move {
                    let _permit = permit;
                    let _ = serve_connection(stream, h, true, Some(t), idle_timeout).await;
                });
            }
            Err(_) => continue,
        }
    }
}
