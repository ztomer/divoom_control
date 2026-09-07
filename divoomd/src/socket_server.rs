//! Unix-socket NDJSON server — the request/reply transport, ported from the
//! archived Python `socket_server.py`.
//!
//! This is the conformance seam: a client (the Python GUI/menubar/CLI, or the
//! Python test suite as an oracle) connects, sends one
//! `{"command","args","token"?}` line, and reads one reply line.
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

/// Max concurrent client connections.
///
/// Connection 65 onward is back-pressured (the accept loop waits for a free
/// permit) rather than unbounded — a runaway or hostile client can't exhaust
/// fds/tasks. Tunable via `DIVOOMD_MAX_CONNECTIONS`.
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
#[must_use]
pub fn subscription_budget(max_connections: usize) -> usize {
    (max_connections / 2).clamp(1, MAX_SUBSCRIPTIONS)
}

/// Upper bound on the backoff we ask a refused client to randomise within.
///
/// Connections here are held for a connection's lifetime, not a request's, so a
/// slot frees when a client finishes — sub-second in normal use. This is a cap
/// for the client's Full-Jitter backoff (Brooker, AWS 2015), never a sleep
/// instruction: a refused burst that all slept the same interval would return in
/// lockstep and re-refuse itself.
pub const RETRY_AFTER_MS: u32 = 1_000;

/// Give up on a write that a peer will not drain within this long, and close.
///
/// A subscriber whose client stops READING is the case nothing else catches. It
/// is not idle (we have events for it), it has not closed (no EOF), and its
/// socket buffer absorbs writes until it fills -- after which `write_all` blocks
/// forever. That stall is not confined to the write: once the `rx.recv()` arm of
/// the subscriber `select!` is chosen, its body runs to completion, so the
/// eviction arm, the idle deadline and the read arm all become UNREACHABLE. The
/// subscriber pins its registry slot permanently and cannot be reclaimed -- the
/// same class of bug the registry was built to end, surviving inside the fix.
///
/// The method of record is a write deadline followed by disconnection, not an
/// ever-growing buffer: NATS's server "gives up on that client and closes the
/// whole connection"; Redis disconnects a pubsub client on
/// `client-output-buffer-limit`. Reactive Streams states the invariant the other
/// way round -- backpressure exists "to allow the queues which mediate between
/// threads to be bounded".
pub const WRITE_TIMEOUT: Duration = Duration::from_secs(10);

/// How many dropped events a subscriber may accumulate before it is dropped.
///
/// `tokio::sync::broadcast` overwrites the oldest value and hands the receiver
/// `Lagged(n)`; it deliberately does NOT disconnect, leaving the caller to
/// decide. Ignoring it is the one policy the field does not have: a subscriber
/// that cannot tell it has a hole in its state will act on stale truth. So we
/// count, tell the client so it can resync, and disconnect past this budget.
pub const LAG_BUDGET: u64 = 64;

/// Drop a connection that sends nothing for this long (no newline-terminated
/// request).
///
/// Closes the "connect and hold the socket open silently" wedge where a dead
/// client pins a permit + the device lock forever. Tunable via
/// `DIVOOMD_IDLE_TIMEOUT_SECS`.
pub const CONNECTION_IDLE_TIMEOUT: Duration = Duration::from_secs(300);

/// Dispatches a parsed request to a reply.
///
/// Object-safe + Send-explicit so each connection can be served on its own
/// task. The real implementation routes to the device owner / command queue;
/// tests use a stub.
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

/// Write one NDJSON line to a client, bounded by [`WRITE_TIMEOUT`].
///
/// EVERY write to a client socket in this module goes through here, and
/// `tools/check_bounded_writes.py` fails the build if a bare `write_all`
/// appears outside it. That gate is the point: bounding the two writes in the
/// subscriber loop by hand left ten unbounded ones, including the eviction
/// notice -- which is written to the one client we have already concluded is
/// not draining its socket, so it was the likeliest of the ten to block
/// forever. A per-site fix leaves the class alive; a seam every write must pass
/// through cannot be forgotten by the next edit.
///
/// A timeout surfaces as [`std::io::ErrorKind::TimedOut`] so a caller that
/// wants to drop the peer rather than propagate can tell the two apart.
async fn write_line<S>(stream: &mut S, msg: &Value) -> std::io::Result<()>
where
    S: tokio::io::AsyncWrite + Unpin,
{
    tokio::time::timeout(WRITE_TIMEOUT, stream.write_all(&encode_message(msg)))
        .await
        .unwrap_or_else(|_| {
            Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!(
                    "peer did not drain a write within {}s",
                    WRITE_TIMEOUT.as_secs()
                ),
            ))
        })
}

#[expect(
    clippy::too_many_lines,
    reason = "one connection, start to finish: read a request, dispatch it, write the reply, and handle subscribe as a long-lived stream instead. The subscription arm shares the socket and the loop state with the request arm, which is exactly what makes it one function"
)]
/// Serve a single connection: accumulate bytes, split into NDJSON requests,
/// dispatch each, and write back one reply line per request.
///
/// Returns when the peer closes (EOF) or on an I/O error. A peer that never
/// sends a newline can't grow the buffer past `MAX_REPLY_BYTES` (the connection
/// is dropped instead).
///
/// # Errors
///
/// When the connection cannot be read from or written to. A peer that simply
/// closes is `Ok(())`, not an error -- EOF is how a client says it is done.
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
            Ok(Ok(0)) | Err(_) => return Ok(()), // EOF — peer closed
            Ok(Ok(k)) => k,
            Ok(Err(e)) => return Err(e),
            // idle: dead/silent peer, drop
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
                    write_line(&mut stream, &reply).await?;
                    continue;
                }
            };
            let Ok(req) = serde_json::from_value::<Request>(msg) else {
                let reply = err_reply("bad request: expected an object with a 'command' string");
                write_line(&mut stream, &reply).await?;
                continue;
            };
            if require_auth {
                let supplied = req.token.as_deref().unwrap_or("");
                let server_token = token.as_deref().unwrap_or("");
                if server_token.is_empty() || !constant_time_eq(supplied, server_token) {
                    let reply = err_reply("unauthorized");
                    write_line(&mut stream, &reply).await?;
                    continue;
                }
            }
            if req.command == "subscribe" {
                if let Some(mut rx) = handler.subscribe() {
                    // A subscription slot is separate from the connection slot,
                    // and scarcer: see MAX_SUBSCRIPTIONS. Refusing here keeps
                    // request capacity available no matter how many subscribers
                    // pile up, and tells the client why instead of hanging.
                    let Some(lease) = subscriptions.admit() else {
                        let reply = err_reply(
                            "too many active subscriptions; every slot is held by a \
                             client that is demonstrably still active",
                        );
                        write_line(&mut stream, &reply).await?;
                        continue;
                    };
                    let evict = lease.evict.clone();
                    let lease_id = lease.id;
                    let initial = handler.initial_status();
                    write_line(&mut stream, &initial).await?;
                    // Idle watchdog: a subscriber that receives no events for
                    // `idle_timeout` is dropped (releasing its permit), so a silent
                    // client can't pin a slot forever. Any delivered event resets it.
                    let mut deadline = tokio::time::Instant::now() + idle_timeout;
                    let mut dropped: u64 = 0;
                    loop {
                        tokio::select! {
                            n = stream.read(&mut tmp) => {
                                match n {
                                    // EOF
                                    Ok(0) | Err(_) => break, // error
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
                                        // Bounded: a peer that stops reading is
                                        // disconnected, never allowed to stall
                                        // this task (see WRITE_TIMEOUT).
                                        match write_line(&mut stream, &event).await {
                                            Ok(()) => {}
                                            Err(e)
                                                if e.kind()
                                                    == std::io::ErrorKind::TimedOut =>
                                            {
                                                eprintln!(
                                                    "divoomd: subscriber did not drain a write \
                                                     within {}s; dropping it",
                                                    WRITE_TIMEOUT.as_secs()
                                                );
                                                break;
                                            }
                                            Err(e) => return Err(e),
                                        }
                                        deadline = tokio::time::Instant::now() + idle_timeout;
                                    }
                                    Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                                        // Tell the client it has a GAP, so it can
                                        // resync instead of trusting stale state,
                                        // and drop it once it is hopeless.
                                        dropped = dropped.saturating_add(n);
                                        let gap = serde_json::json!({
                                            "type": "lagged",
                                            "dropped": n,
                                            "dropped_total": dropped,
                                        });
                                        let _ = write_line(&mut stream, &gap).await;
                                        if dropped > LAG_BUDGET {
                                            eprintln!(
                                                "divoomd: subscriber lost {dropped} events \
                                                 (budget {LAG_BUDGET}); dropping it"
                                            );
                                            break;
                                        }
                                    }
                                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                                        break;
                                    }
                                }
                            }
                            () = tokio::time::sleep_until(deadline) => break, // quiet channel: drop
                            () = evict.notified() => {
                                // Our slot was reclaimed for a newcomer because
                                // this client had gone quiet. Say why, so it
                                // reads as a renegotiation and not a fault.
                                let notice = serde_json::json!({
                                    "type": "resubscribe",
                                    "reason": "subscription slot reclaimed after inactivity; reconnect to continue",
                                });
                                let _ = write_line(&mut stream, &notice).await;
                                break;
                            }
                        }
                    }
                    return Ok(());
                }
                {
                    let reply = err_reply("subscriptions not supported");
                    write_line(&mut stream, &reply).await?;
                    continue;
                }
            }
            let reply = handler.handle(req).await;
            write_line(&mut stream, &reply).await?;
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
    // A refusal a client can ACT on, not prose it has to string-match. Every
    // mature protocol pairs a machine-distinguishable transient class with
    // server-supplied retry timing: HTTP 503 + `Retry-After` (RFC 9110), gRPC
    // RESOURCE_EXHAUSTED plus `grpc-retry-pushback-ms` (gRFC A6), and — the
    // closest precedent for a line protocol — SMTP's 4yz transient class and
    // 421 "one-line refusal, then close" (RFC 5321 4.2.1).
    //
    // `retry_after_ms` is the CAP on the client's own Full-Jitter backoff, not a
    // sleep instruction: the client still randomises below it, or a refused
    // burst returns in lockstep and re-refuses itself.
    // Carry the identity marker even in a refusal. `socket_bind::probe` decides
    // what owns the socket from `daemon_version` (or a status event), so a
    // refusal without it would just move the misdiagnosis: a busy daemon would
    // read as "listening, but answers as something else" — a foreign program —
    // and a second daemon would refuse to start against a perfectly healthy one.
    // Being at capacity is a fact about load, never about identity.
    if let Some(obj) = reply.as_object_mut() {
        obj.insert(
            "code".into(),
            Value::String("resource_exhausted".to_string()),
        );
        obj.insert(
            "retry_after_ms".into(),
            Value::Number(RETRY_AFTER_MS.into()),
        );
        obj.insert(
            "daemon_version".into(),
            Value::String(env!("CARGO_PKG_VERSION").to_string()),
        );
    }
    let _ = write_line(&mut stream, &reply).await;
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
        let Ok((stream, _addr)) = listener.accept().await else {
            continue;
        };
        if let Ok(permit) = sem.clone().try_acquire_owned() {
            let h = handler.clone();
            let s = subs.clone();
            tokio::spawn(async move {
                let _permit = permit; // held for the connection's lifetime
                let _ = serve_connection(stream, h, false, None, idle_timeout, s).await;
            });
        } else {
            eprintln!(
                "divoomd: at the connection cap ({max_connections}); refusing a client. \
                 Something is holding connections open — check `lsof` on the socket. \
                 Raise DIVOOMD_MAX_CONNECTIONS if the cap is genuinely too low."
            );
            tokio::spawn(refuse_at_capacity(stream, max_connections));
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
        let Ok((stream, _addr)) = listener.accept().await else {
            continue;
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
