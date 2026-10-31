//! One connect at a time on the radio, and one owner per panel's link
//! (D.DV2c). Split from `daemon_connect.rs` (500-line rule).

use serde_json::{json, Value};
#[cfg(feature = "ble")]
use std::time::{Duration, Instant};

#[cfg(feature = "ble")]
use super::ConnectGuard;
use crate::daemon::Daemon;
use crate::protocol::Request;
#[cfg(feature = "ble")]
use crate::protocol::{err_code, ErrorCode};

/// How long a connect waits for another connect to finish before it gives up
/// with `busy`. A BLE connect is a few seconds; the daemon's own restore
/// links up to four panels one after another at startup.
#[cfg(feature = "ble")]
pub(super) const CONNECT_WAIT: Duration = Duration::from_secs(45);

/// How often a waiting connect looks again.
#[cfg(feature = "ble")]
pub(super) const CONNECT_POLL: Duration = Duration::from_millis(200);

/// The id a connect request names: `LAN:<ip>`, or the mac / id.
pub(super) fn requested_id(req: &Request) -> Option<String> {
    if let Some(ip) = req.args.get("lan_ip").and_then(Value::as_str) {
        return Some(format!("LAN:{ip}"));
    }
    req.args
        .get("mac")
        .or_else(|| req.args.get("id"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

/// The reply for a panel this daemon already holds: success, and the radio
/// untouched. ONE owner holds a panel's link (D.DV2c), so a second `connect`
/// for it -- the scheduler's, a client's relink, the restore -- is answered
/// from the fleet instead of opening a second connection over the first.
pub(super) async fn already_linked(daemon: &Daemon, id: &str) -> Option<Value> {
    daemon.fleet.connected(id).await?;
    let mut reply = json!({"success": true, "connected": true,
        "connection_state": "connected", "already_linked": true});
    if let Some(ip) = id.strip_prefix("LAN:") {
        reply["lan_ip"] = json!(ip);
    } else {
        reply["mac"] = json!(id);
    }
    Some(reply)
}

/// Take the radio for one connect, WAITING while another connect holds it --
/// and stopping the wait the moment the panel this one asks for is linked by
/// whoever held it.
///
/// It used to refuse at once with `busy`. The daemon's restore links its
/// panels one after another at startup, and the scheduled hot-channel run
/// asked for every one of those panels while the restore held the radio:
/// all four were refused "connect already in progress" (the owner's run of
/// 2026-10-26), though each was linked seconds later.
#[cfg(feature = "ble")]
pub(super) async fn take_radio<'a>(
    daemon: &'a Daemon,
    id: Option<&str>,
    wait: Duration,
) -> Result<ConnectGuard<'a>, Value> {
    use std::sync::atomic::Ordering;
    let deadline = Instant::now() + wait;
    loop {
        if daemon
            .connecting
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            return Ok(ConnectGuard(&daemon.connecting));
        }
        if let Some(id) = id {
            if let Some(reply) = already_linked(daemon, id).await {
                return Err(reply);
            }
        }
        if Instant::now() >= deadline {
            return Err(err_code(ErrorCode::Busy, "connect already in progress"));
        }
        tokio::time::sleep(CONNECT_POLL).await;
    }
}
