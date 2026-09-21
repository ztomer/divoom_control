//! The notification commands, defined once per platform. The monitor is a
//! macOS thing (`macos_notifications`); everywhere else the same five entry
//! points answer at once with an idle status, so the dispatch table keeps
//! one shape (a future per command) without any lint being quieted.

#[cfg(target_os = "macos")]
pub(super) use macos::*;
#[cfg(not(target_os = "macos"))]
pub(super) use other::*;

#[cfg(target_os = "macos")]
mod macos {
    use crate::daemon::Daemon;
    use crate::macos_notifications as notif;
    use crate::protocol::Request;
    use serde_json::{json, Value};

    /// The monitor's current state, merged into `get_status`.
    pub(in crate::daemon) async fn status_event() -> Value {
        notif::status_event().await
    }

    pub(in crate::daemon) async fn start(daemon: &Daemon) -> Value {
        if let Some(w) = daemon.self_weak.get().and_then(std::sync::Weak::upgrade) {
            notif::start_monitor(w).await;
            let mut status = notif::status_event().await;
            status["success"] = json!(true);
            return status;
        }
        json!({
            "success": false,
            "error": "daemon not initialized",
            "state": "idle",
            "counters": {"seen": 0, "routed": 0, "dropped": 0},
        })
    }

    pub(in crate::daemon) async fn stop() -> Value {
        notif::stop_monitor().await;
        let mut status = notif::status_event().await;
        status["success"] = json!(true);
        status
    }

    pub(in crate::daemon) async fn status() -> Value {
        notif::notification_status().await
    }

    pub(in crate::daemon) async fn set_routing(req: Request) -> Value {
        notif::set_routing(&req.args).await
    }
}

#[cfg(not(target_os = "macos"))]
mod other {
    use crate::daemon::Daemon;
    use crate::protocol::Request;
    use serde_json::{json, Value};
    use std::future::{ready, Future};

    fn idle() -> Value {
        json!({
            "state": "idle",
            "counters": {"seen": 0, "routed": 0, "dropped": 0}
        })
    }

    fn idle_with(success: bool) -> Value {
        let mut v = idle();
        v["success"] = json!(success);
        v
    }

    pub(in crate::daemon) fn status_event() -> impl Future<Output = Value> + Send {
        ready(idle())
    }

    /// Same arguments as the macOS entry point so the dispatch table needs
    /// no `cfg` of its own.
    pub(in crate::daemon) fn start(_daemon: &Daemon) -> impl Future<Output = Value> + Send {
        let mut v = idle_with(false);
        v["error"] = json!("notifications not available on this platform");
        v["unsupported"] = json!(true);
        ready(v)
    }

    pub(in crate::daemon) fn stop() -> impl Future<Output = Value> + Send {
        ready(idle_with(true))
    }

    pub(in crate::daemon) fn status() -> impl Future<Output = Value> + Send {
        ready(idle_with(true))
    }

    pub(in crate::daemon) fn set_routing(_req: Request) -> impl Future<Output = Value> + Send {
        ready(json!({"success": true}))
    }
}
