//! The monthly-best push's link to one panel.
//!
//! Connect, learn how big it is, let go. Split from `monthly_best_push.rs` (500-line rule). The size is
//! learned FIRST because it decides which art the gallery may offer (D14).

use serde_json::json;

use crate::daemon::Daemon;
use crate::protocol::Request;

/// Connect to `target` and learn its panel size, which decides the art it
/// may be offered.
///
/// # Errors
///
/// When the panel cannot be reached, or does not say how big it is.
pub async fn connect(daemon: &Daemon, target: &str) -> Result<u32, String> {
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
    let pixels = match daemon.fleet.get(target).await {
        Some(dev) => dev.panel_pixels().await,
        None => None,
    };
    if let Some(p) = pixels {
        Ok(p)
    } else {
        disconnect(daemon).await;
        Err(format!(
            "the panel {target} does not say how big it is, so no pixel art can be matched to it"
        ))
    }
}

/// Let go of the panel the push connected to.
pub async fn disconnect(daemon: &Daemon) {
    daemon
        .dispatch(Request {
            command: "disconnect".to_string(),
            args: json!({}),
            token: None,
        })
        .await;
}
