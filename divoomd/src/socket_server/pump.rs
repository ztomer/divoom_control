//! One subscription's event pump. Split from `socket_server.rs` at the
//! file-length cap; `serve_connection` hands a subscriber here after the
//! initial status line.

use std::time::Duration;

use serde_json::Value;
use tokio::io::AsyncReadExt;

use super::{write_line, LAG_BUDGET, WRITE_TIMEOUT};
use crate::subscriptions::Registry;

/// Serve one subscription until the client leaves, goes quiet, falls too far
/// behind, or is evicted for a newcomer.
///
/// Idle watchdog: a subscriber that receives no events for `idle_timeout` is
/// dropped (releasing its permit), so a silent client cannot pin a slot
/// forever. Any delivered event resets it.
pub(super) async fn pump_events<S>(
    stream: &mut S,
    rx: &mut tokio::sync::broadcast::Receiver<Value>,
    lease: &crate::subscriptions::Lease,
    subscriptions: &Registry,
    tracked: &crate::connections::Tracked,
    idle_timeout: Duration,
    conflated: Option<&crate::events::Events>,
) -> std::io::Result<()>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
{
    let mut tmp = [0u8; 4096];
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
                    Ok(_) => {
                        subscriptions.touch(lease.id);
                        tracked.touch();
                    }
                }
            }
            msg = rx.recv() => {
                match msg {
                    Ok(event) => {
                        // Bounded: a peer that stops reading is
                        // disconnected, never allowed to stall
                        // this task (see WRITE_TIMEOUT).
                        match write_line(stream, &event).await {
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
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_))
                        if conflated.is_some() =>
                    {
                        // P2.5: a status subscriber wants the CURRENT
                        // truth. Re-attach at the tail and send the
                        // latest value of every key, in publish order:
                        // no hole to report and nothing to drop for.
                        let latest = conflated.map(|bus| bus.resync(rx)).unwrap_or_default();
                        for event in &latest {
                            if write_line(stream, event).await.is_err() {
                                eprintln!(
                                    "divoomd: subscriber did not drain its resync \
                                     within {}s; dropping it",
                                    WRITE_TIMEOUT.as_secs()
                                );
                                return Ok(());
                            }
                        }
                        deadline = tokio::time::Instant::now() + idle_timeout;
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                        // No conflating bus behind this handler: tell
                        // the client it has a GAP, so it can
                        // resync instead of trusting stale state,
                        // and drop it once it is hopeless.
                        dropped = dropped.saturating_add(n);
                        let gap = serde_json::json!({
                            "type": "lagged",
                            "dropped": n,
                            "dropped_total": dropped,
                        });
                        let _ = write_line(stream, &gap).await;
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
            () = lease.evict.notified() => {
                // Our slot was reclaimed: by this same client
                // reconnecting under its name (P2.4), or for a
                // newcomer because this client had gone quiet.
                // Say which, so it reads as a renegotiation and
                // not a fault -- and a `taken_over` client knows
                // its successor already holds the stream.
                let notice = if lease.taken_over() {
                    serde_json::json!({
                        "type": "resubscribe",
                        "code": "taken_over",
                        "reason": "a newer subscription under the same client_id replaced this one",
                    })
                } else {
                    serde_json::json!({
                        "type": "resubscribe",
                        "code": "inactive",
                        "reason": "subscription slot reclaimed after inactivity; reconnect to continue",
                    })
                };
                let _ = write_line(stream, &notice).await;
                break;
            }
        }
    }
    Ok(())
}
