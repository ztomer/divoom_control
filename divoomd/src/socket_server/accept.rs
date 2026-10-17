//! The accept loops: unix and TCP. Split from `socket_server.rs` at the
//! file-length cap when P2.6 added the heartbeat; `tools/check_bounded_writes.py`
//! reads this file too, so every write here still goes through `write_line`.

use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;
use tokio::sync::Semaphore;

use super::{serve_connection, subscription_budget, write_line, Handler, RETRY_AFTER_MS};
use crate::connections::Connections;
use crate::protocol::err_reply;
use crate::subscriptions::{Registry, RENEGOTIATE_AFTER};

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

/// The handler's shared connection table (or a private one), with this
/// listener's budgets recorded on it.
fn connection_table<H: Handler>(
    handler: &H,
    transport: &'static str,
    max_connections: usize,
) -> Arc<Connections> {
    let table = handler.connections().unwrap_or_default();
    table.set_limits(
        transport,
        max_connections.max(1),
        subscription_budget(max_connections),
    );
    table
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
    let table = connection_table(handler.as_ref(), "unix", max_connections);
    // P2.6: beat on every turn, and turn at least every `every()` even with no
    // client, so silence means the loop stopped, never that nobody called.
    let heartbeat = handler.heartbeat();
    let mut tick = tokio::time::interval(
        heartbeat
            .as_ref()
            .map_or(crate::watchdog::BEAT_EVERY, |h| h.every()),
    );
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        if let Some(h) = &heartbeat {
            h.beat();
        }
        // ALWAYS accept. Nothing below this line may stop the loop.
        let accepted = tokio::select! {
            r = listener.accept() => r,
            _ = tick.tick() => continue,
        };
        let Ok((stream, _addr)) = accepted else {
            continue;
        };
        if let Ok(permit) = sem.clone().try_acquire_owned() {
            let h = handler.clone();
            let s = subs.clone();
            // Who is on the other end: the peer's pid, the one fact that turns
            // "64 connections are held" into "process N holds them".
            let pid = stream.peer_cred().ok().and_then(|c| c.pid());
            let tracked = table.open("unix", pid);
            tokio::spawn(async move {
                let _permit = permit; // held for the connection's lifetime
                let _ = serve_connection(stream, h, false, None, idle_timeout, s, tracked).await;
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
    let table = connection_table(handler.as_ref(), "tcp", max_connections);
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
                let tracked = table.open("tcp", None);
                tokio::spawn(async move {
                    let _permit = permit;
                    let _ =
                        serve_connection(stream, h, true, Some(t), idle_timeout, s, tracked).await;
                });
            }
            Err(_) => {
                tokio::spawn(refuse_at_capacity(stream, max_connections));
            }
        }
    }
}
