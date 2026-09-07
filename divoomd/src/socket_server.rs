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

use crate::subscriptions::{Registry, RENEGOTIATE_AFTER};

use crate::protocol::{encode_message, err_reply, iter_messages, Request, MAX_REPLY_BYTES};

/// Max concurrent client connections. Connection 65 onward is back-pressured
/// (the accept loop waits for a free permit) rather than unbounded — a runaway
/// or hostile client can't exhaust fds/tasks. Tunable via
/// `DIVOOMD_MAX_CONNECTIONS`.
///
/// The doc said "a 6th+ connection" while the constant was 64, left over from an
/// earlier value. Harmless as prose, but it is the number a reader uses to judge
/// whether saturation is plausible — and saturation is exactly what took a
/// daemon down for five days — back when reaching the cap stopped the accept
/// loop entirely instead of shedding (see [`refuse_at_capacity`]).
///
/// Saturation used to be TOTAL rather than partial: a full semaphore stopped
/// the accept loop, so the daemon answered nobody at all, not just the 65th
/// client. It now stays reachable and refuses the overflow explicitly.
pub const MAX_CONNECTIONS: usize = 64;

/// Most concurrent SUBSCRIPTIONS, as a share of the connection budget.
///
/// Subscriptions are the one connection kind that is long-lived BY DESIGN: a
/// subscriber holds its slot for as long as it is subscribed, while a
/// request/reply client closes as soon as it has its answer (the Python client
/// does exactly that — `with s:`). So the only connections that can pile up are
/// subscriptions, and with one shared budget enough of them starve every
/// request. That is how a daemon reached 64 held connections and stopped being
/// able to answer `get_status`.
///
/// Giving subscriptions their own smaller budget makes that impossible: however
/// many subscribers accumulate, request slots remain. A subscriber over the
/// budget is told so, which is a far better failure than a silent daemon.
pub const MAX_SUBSCRIPTIONS: usize = 8;

/// The subscription budget for a given connection budget.
///
/// At most HALF the connection budget, and never more than [`MAX_SUBSCRIPTIONS`].
/// The half matters as much as the cap: a first cut used
/// `min(max_connections, MAX_SUBSCRIPTIONS)`, which reserves nothing whenever the
/// connection budget is 8 or smaller — subscribers could still take every slot,
/// and the test written to prove requests survive saturation failed on exactly
/// that. Reserving a fraction, rather than a constant, keeps the guarantee true
/// at every budget.
pub fn subscription_budget(max_connections: usize) -> usize {
    (max_connections / 2).clamp(1, MAX_SUBSCRIPTIONS)
}

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
    subscriptions: Arc<Registry>,
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
                    // A subscription slot is separate from the connection slot,
                    // and scarcer: see MAX_SUBSCRIPTIONS. Refusing here keeps
                    // request capacity available no matter how many subscribers
                    // pile up, and tells the client why instead of hanging.
                    let lease = match subscriptions.admit() {
                        Some(l) => l,
                        None => {
                            let reply = err_reply(
                                "too many active subscriptions; every slot is held by a \
                                 client that is demonstrably still active",
                            );
                            stream.write_all(&encode_message(&reply)).await?;
                            continue;
                        }
                    };
                    let evict = lease.evict.clone();
                    let lease_id = lease.id;
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
                                    // Any byte from the client is liveness
                                    // evidence, and the only kind there is:
                                    // deliveries are a broadcast, so they move
                                    // every subscriber's clock together and
                                    // separate nobody. The payload is still
                                    // ignored; only the fact of it counts.
                                    Ok(_) => subscriptions.touch(lease_id),
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
                            _ = tokio::time::sleep_until(deadline) => break, // quiet channel: drop
                            _ = evict.notified() => {
                                // Our slot was reclaimed for a newcomer because
                                // this client had gone quiet. Say why, so it
                                // reads as a renegotiation and not a fault.
                                let notice = serde_json::json!({
                                    "type": "resubscribe",
                                    "reason": "subscription slot reclaimed after inactivity; reconnect to continue",
                                });
                                let _ = stream.write_all(&encode_message(&notice)).await;
                                break;
                            }
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

/// Refuse one connection at capacity: say so in a reply line, then close.
///
/// Shedding beats back-pressure here, and the difference is not academic. The
/// previous design stopped calling `accept()` when the cap was reached, so the
/// daemon became unreachable IN FULL: `connect()` still succeeded (the kernel
/// queues onto the listen backlog) and then nothing ever came back, for any
/// command, including `get_status`. A daemon sat in that state for five days
/// (2026-09-07) while every client and every diagnostic saw only silence, and
/// `socket_bind`'s prober concluded another program owned the socket.
///
/// A cap must bound WORK, never REACHABILITY. Answering "busy" costs one task
/// and one line, keeps the daemon identifiable and diagnosable at all times, and
/// gives the client something it can retry or show. Silence gives it nothing.
async fn refuse_at_capacity<S>(mut stream: S, max_connections: usize)
where
    S: tokio::io::AsyncWrite + Unpin,
{
    let mut reply = err_reply(&format!(
        "daemon is at its connection cap ({max_connections}); try again shortly"
    ));
    // Carry the identity marker even in a refusal. `socket_bind::probe` decides
    // what owns the socket from `daemon_version` (or a status event), so a
    // refusal without it would just move the misdiagnosis: a busy daemon would
    // read as "listening, but answers as something else" — a foreign program —
    // and a second daemon would refuse to start against a perfectly healthy one.
    // Being at capacity is a fact about load, never about identity.
    if let Some(obj) = reply.as_object_mut() {
        obj.insert(
            "daemon_version".into(),
            Value::String(env!("CARGO_PKG_VERSION").to_string()),
        );
    }
    let _ = stream.write_all(&encode_message(&reply)).await;
    let _ = stream.shutdown().await;
}

/// Accept connections forever on a Unix socket, serving each on its own task.
/// Runs until the listener errors unrecoverably (callers normally
/// `tokio::spawn` this).
///
/// `max_connections` bounds concurrent connections. It is a guard against fd and
/// task exhaustion by a runaway client — NOT a concurrency policy for device
/// work, which is serialised by the command queue behind the [`Handler`]. That
/// distinction is why the loop accepts unconditionally and sheds the overflow
/// (see [`refuse_at_capacity`]) instead of pausing: rationing connections was
/// rationing the wrong resource, and doing it by refusing to accept took the
/// whole daemon off the air.
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
    let subs = Registry::new(subscription_budget(max_connections), RENEGOTIATE_AFTER);
    loop {
        // ALWAYS accept. Nothing below this line may stop the loop.
        let (stream, _addr) = match listener.accept().await {
            Ok(v) => v,
            Err(_) => continue,
        };
        match sem.clone().try_acquire_owned() {
            Ok(permit) => {
                let h = handler.clone();
                let s = subs.clone();
                tokio::spawn(async move {
                    let _permit = permit; // held for the connection's lifetime
                    let _ = serve_connection(stream, h, false, None, idle_timeout, s).await;
                });
            }
            Err(_) => {
                eprintln!(
                    "divoomd: at the connection cap ({max_connections}); refusing a client. \
                     Something is holding connections open — check `lsof` on the socket. \
                     Raise DIVOOMD_MAX_CONNECTIONS if the cap is genuinely too low."
                );
                tokio::spawn(refuse_at_capacity(stream, max_connections));
            }
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
    let subs = Registry::new(subscription_budget(max_connections), RENEGOTIATE_AFTER);
    loop {
        // Accept unconditionally, shed the overflow — see the note in `serve`.
        let (stream, _addr) = match listener.accept().await {
            Ok(v) => v,
            Err(_) => continue,
        };
        match sem.clone().try_acquire_owned() {
            Ok(permit) => {
                let h = handler.clone();
                let t = token.clone();
                let s = subs.clone();
                tokio::spawn(async move {
                    let _permit = permit;
                    let _ = serve_connection(stream, h, true, Some(t), idle_timeout, s).await;
                });
            }
            Err(_) => {
                tokio::spawn(refuse_at_capacity(stream, max_connections));
            }
        }
    }
}
