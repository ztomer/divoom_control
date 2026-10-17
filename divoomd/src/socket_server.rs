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

mod accept;
mod pump;
pub use accept::{serve, serve_tcp};
use pump::pump_events;

use crate::connections::{Connections, Tracked};
use crate::subscriptions::Registry;

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
/// loop entirely instead of shedding (see `accept::refuse_at_capacity`).
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
///
/// Only for a handler WITHOUT a conflating bus ([`Handler::events`]). The
/// daemon has one (P2.5), so its subscribers are caught up to the latest value
/// of every key instead -- no client ever read the `lagged` notice, so a hole
/// was silently stale state until then.
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
    /// The conflating event bus behind [`Self::subscribe`], if there is one
    /// (P2.5). With it, a subscriber that falls behind the ring is caught up
    /// to the latest value of every key; without it (stub handlers), it is
    /// told how many events it lost and dropped past [`LAG_BUDGET`].
    fn events(&self) -> Option<Arc<crate::events::Events>> {
        None
    }
    /// The serving loop's proof of life (P2.6): the accept loop beats it on
    /// every turn, and a watchdog thread exits the daemon when it stops.
    fn heartbeat(&self) -> Option<Arc<crate::watchdog::Heartbeat>> {
        None
    }
    /// How long `req` may run before the server answers for it (P2.3).
    /// The per-command table in [`crate::deadlines`]; a test stub overrides it
    /// to stall in milliseconds rather than minutes.
    fn budget(&self, req: &Request) -> Duration {
        crate::deadlines::budget(&req.command)
    }
    /// The daemon's connection table, shared by every listener so
    /// `get_status` can say who holds the daemon. `None` (stub handlers)
    /// gives each listener a private one.
    fn connections(&self) -> Option<Arc<Connections>> {
        None
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
pub(crate) async fn write_line<S>(stream: &mut S, msg: &Value) -> std::io::Result<()>
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

/// Serve a single connection: accumulate bytes, split into NDJSON requests,
/// dispatch each, and write back one reply line per request.
///
/// Returns when the peer closes (EOF) or on an I/O error. A peer that never
/// sends a newline can't grow the buffer past `MAX_REPLY_BYTES` (the connection
/// is dropped instead).
///
/// `tracked` is this connection's entry in the daemon's table: it is touched
/// when the peer speaks, names the command in flight, and leaves the table
/// when this returns.
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
    tracked: Tracked,
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
        tracked.touch();
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
                    let reply = crate::protocol::err_code(
                        crate::protocol::ErrorCode::BadRequest,
                        &format!("bad request: {reason}"),
                    );
                    write_line(&mut stream, &reply).await?;
                    continue;
                }
            };
            let Ok(req) = serde_json::from_value::<Request>(msg) else {
                let reply = crate::protocol::err_code(
                    crate::protocol::ErrorCode::BadRequest,
                    "bad request: expected an object with a 'command' string",
                );
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
                    // A client that names itself takes its own old slot
                    // back (P2.4): a crash-and-reconnect is not a stranger.
                    let client_id = req.args.get("client_id").and_then(Value::as_str);
                    let Some(lease) = subscriptions.admit_as(client_id) else {
                        let reply = err_reply(
                            "too many active subscriptions; every slot is held by a \
                             client that is demonstrably still active",
                        );
                        write_line(&mut stream, &reply).await?;
                        continue;
                    };
                    tracked.mark_subscription();
                    let initial = handler.initial_status();
                    write_line(&mut stream, &initial).await?;
                    pump_events(
                        &mut stream,
                        &mut rx,
                        &lease,
                        &subscriptions,
                        &tracked,
                        idle_timeout,
                        handler.events().as_deref(),
                    )
                    .await?;
                    return Ok(());
                }
                {
                    let reply = err_reply("subscriptions not supported");
                    write_line(&mut stream, &reply).await?;
                    continue;
                }
            }
            tracked.running(Some(&req.command));
            let budget = handler.budget(&req);
            let command = req.command.clone();
            let reply = tokio::time::timeout(budget, handler.handle(req))
                .await
                .unwrap_or_else(|_| crate::deadlines::exceeded(&command, budget));
            tracked.running(None);
            write_line(&mut stream, &reply).await?;
        }
    }
}
