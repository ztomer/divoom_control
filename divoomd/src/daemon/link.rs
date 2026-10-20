//! A link that is gone: what the daemon does about it, and how it says so.
//!
//! Split out of `daemon.rs` at the house 500-line cap, at the seam that
//! names itself: everything here is about a panel whose link failed, and
//! nothing else in the daemon is.
//!
//! The rule (P2.8): a command that could not be SENT means the panel is not
//! there any more. The link is retired -- so the panel stops reading as
//! connected -- and the drop is reported, the same two broadcasts
//! `mock_simulate_drop` walks for a simulated one. A panel that is there and
//! did not answer is a different thing: the link stays, and the panel is
//! only degraded.

use serde_json::{json, Value};

use crate::daemon::Daemon;
use crate::protocol::ErrorCode;

impl Daemon {
    /// The panel's link is gone: retire it and report the drop.
    ///
    /// The same two broadcasts `mock_simulate_drop` walks for a simulated
    /// drop: the panel stops reading as connected (`device_status` says so,
    /// and the fleet no longer holds it as linked), and every client is told
    /// on the event bus (P2.8). The panel's IDENTITY is kept -- a live job
    /// waits for the panel to come back, exactly as it does after a
    /// simulated drop.
    ///
    /// `reason` says why, on the event, so a client can tell a drop from a
    /// user-initiated disconnect without asking.
    pub(crate) async fn link_failed(&self, mac: &str, reason: Option<&str>) {
        self.fleet.detach(mac).await;
        let mut event =
            crate::daemon_connect::status_payload(false, Some(mac), Some("disconnected"));
        if let Some(why) = reason {
            if let Some(o) = event.as_object_mut() {
                o.insert("reason".into(), json!(why));
            }
        }
        let _ = self.tx.send(event);
        let _ = self
            .tx
            .send(crate::daemon_connect::owned_devices_payload(self).await);
    }
}

/// Did this reply say the LINK is gone?
///
/// `device_disconnected` is the class the daemon acts on: the command could
/// not be sent, so the panel is not there any more and the link must be
/// retired (P2.8). `device_failed` is a different thing -- the panel is there
/// and did not do what was asked -- so the link stays and the panel is only
/// degraded.
pub fn link_is_gone(reply: &Value) -> bool {
    reply.get("code").and_then(serde_json::Value::as_str)
        == Some(ErrorCode::DeviceDisconnected.as_str())
}
