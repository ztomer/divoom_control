//! The monthly-best push's link to one panel: BORROWED, never owned.
//!
//! Connect, learn how big it is, give it back. Split from
//! `monthly_best_push.rs` (500-line rule). The size is learned FIRST because
//! it decides which art the gallery may offer (D14).
//!
//! # One owner holds a panel's link (D.DV2c)
//!
//! The scheduled run of 2026-10-26 failed on all four panels with "connect
//! already in progress", and had it got further it would have done worse.
//! The push treated every panel as its own: it sent `connect` for a panel the
//! fleet already held (racing the daemon's startup restore for the one radio,
//! which refused it), and when it was done it sent a bare `disconnect` -- the
//! FLEET-WIDE one, which drops every panel and forgets every saved link. One
//! scheduled run unlinked the whole bench and emptied `links.json` (the
//! owner's file holds no links today).
//!
//! So the push borrows: a panel the fleet holds is used as it is and left
//! linked; a panel it is not holding is linked through the daemon's own
//! `connect` (which waits for the radio), and given back -- that panel alone
//! -- only when nobody wanted it linked before. [`Lease`] is the only way to
//! let go, and it can let go of nothing but what it opened.

use serde_json::json;

use crate::daemon::Daemon;
use crate::protocol::Request;

/// A borrowed link to one panel.
#[derive(Debug, PartialEq, Eq)]
#[must_use = "a lease is given back with `release`"]
pub struct Lease {
    /// The panel.
    pub id: String,
    /// The push opened this link, and nobody wanted it linked before: the
    /// push closes it again. Otherwise the link is someone else's.
    opened: bool,
}

impl Lease {
    /// Whether giving this lease back closes the link.
    #[must_use]
    pub const fn closes_on_release(&self) -> bool {
        self.opened
    }
}

/// Borrow `target`'s link and learn its panel size, which decides the art it
/// may be offered.
///
/// # Errors
///
/// When the panel cannot be reached, or does not say how big it is.
pub async fn connect(daemon: &Daemon, target: &str) -> Result<(Lease, u32), String> {
    let mut held = daemon.fleet.connected(target).await.is_some();
    let wanted = daemon.links.remembers(target).await;
    if !held {
        let connect_args = target.strip_prefix("LAN:").map_or_else(
            || {
                json!({
                    "mac": target,
                    "use_ios_le_protocol": true
                })
            },
            |ip| json!({ "lan_ip": ip }),
        );
        let res = daemon
            .dispatch(Request {
                command: "connect".to_string(),
                args: connect_args,
                token: None,
            })
            .await;
        if !res
            .get("success")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
        {
            let err = res
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown connection error");
            return Err(format!("Connection to {target} failed: {err}"));
        }
        // Linked by someone else while ours waited for the radio: theirs.
        held = res
            .get("already_linked")
            .and_then(serde_json::Value::as_bool)
            == Some(true);
    }
    let lease = Lease {
        id: target.to_string(),
        opened: !held && !wanted,
    };
    let pixels = match daemon.fleet.get(target).await {
        Some(dev) => dev.panel_pixels().await,
        None => None,
    };
    if let Some(p) = pixels {
        Ok((lease, p))
    } else {
        release(daemon, lease).await;
        Err(format!(
            "the panel {target} does not say how big it is, so no pixel art can be matched to it"
        ))
    }
}

/// Give the lease back: close the link only if the push opened it, and only
/// that panel's.
pub async fn release(daemon: &Daemon, lease: Lease) {
    if lease.opened {
        let _ = crate::daemon_connect::cmd_disconnect_one(daemon, &lease.id).await;
    }
}
