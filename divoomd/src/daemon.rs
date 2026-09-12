//! The daemon's request Handler — dispatches NDJSON commands to replies.
//!
//! Owns the [`CommandQueue`] (exclusive mode / steal-reject) and, when built
//! with the `ble` feature, the connected device. Replies match the Python
//! daemon's shapes so the existing Python clients (and the conformance suite)
//! drive this unchanged.
//!
//! Device commands are honest: when `ble` is built they hit the real transport;
//! otherwise (and for not-yet-ported commands) they return a clear error rather
//! than a fake success.

use std::future::Future;
use std::pin::Pin;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use std::sync::{Arc, OnceLock, Weak};

use crate::native_encode::NativeEncoder;
use crate::protocol::{err_reply, Request};
use crate::socket_server::Handler;

#[cfg(feature = "ble")]
use crate::central::BleCentral;
use tokio::sync::Mutex;

mod dispatch;

pub(crate) const EXCLUSIVE_TIMEOUT: Duration = Duration::from_secs(30);
pub(crate) const ITEM_TIMEOUT: Duration = Duration::from_secs(60);

pub use crate::transport::DeviceTransport;

pub struct Daemon {
    started: Instant,
    /// Every device this daemon knows: identity, link, live job, activity.
    /// The single owner of per-device state -- see `crate::device`.
    pub fleet: Arc<crate::device::Fleet>,
    // the CoreBluetooth central, created once and kept alive for the daemon's
    // lifetime (dropping it stops notification delivery).
    #[cfg(feature = "ble")]
    pub(crate) central: Mutex<Option<BleCentral>>,
    /// True while a scan is running. A scan drives the one shared adapter's
    /// start/stop; two overlapping scans would clobber each other (one's
    /// `stop_scan` ends the other early → truncated results), so `cmd_scan` rejects
    /// a concurrent scan. Mirrors the Python daemon's single-scan model.
    #[cfg(feature = "ble")]
    pub(crate) scanning: std::sync::atomic::AtomicBool,
    /// True while a connect is running. Two concurrent connects would clobber the
    /// one shared central + overwrite the owned device, so `cmd_connect` rejects a
    /// second with a clear error (mirrors the `scanning` guard for scans).
    #[cfg(feature = "ble")]
    pub(crate) connecting: std::sync::atomic::AtomicBool,
    /// Last scan's completion time + result. A scan within `MIN_RESCAN_INTERVAL`
    /// of the last returns this cached list instead of hitting the radio —
    /// back-to-back scans trip `CoreBluetooth`'s scan-frequency throttle (which
    /// silently returns 0 devices until it resets).
    #[cfg(feature = "ble")]
    pub(crate) last_scan: Mutex<Option<(Instant, Vec<Value>)>>,
    // C image encoder (libdivoom_compact FFI); loaded once, cached for lifetime.
    encoder: OnceLock<Option<NativeEncoder>>,
    pub(crate) tx: tokio::sync::broadcast::Sender<Value>,
    pub live_jobs: Arc<crate::live_jobs::LiveJobCoordinator>,
    pub(crate) self_weak: OnceLock<Weak<Self>>,
    /// Shared progress state for the background hot-update task.
    pub hot_progress: Arc<crate::art::HotProgress>,
    /// Current wall coordinator (None when no wall is active).
    pub wall: Mutex<Option<crate::wall::DivoomWall>>,
    /// The slot config last used for the wall (for delta reconfiguration).
    pub wall_slots: Mutex<serde_json::Map<String, Value>>,
    /// Fired by the `shutdown` command; the main loop awaits this to exit cleanly
    /// (socket unlink) the same way it does for SIGINT/SIGTERM.
    pub shutdown: Arc<tokio::sync::Notify>,
}

impl Default for Daemon {
    fn default() -> Self {
        Self::new()
    }
}

impl Daemon {
    #[must_use]
    pub fn new() -> Self {
        let (tx, _) = tokio::sync::broadcast::channel(32);
        let tx_for_hot = tx.clone();
        let fleet = Arc::new(crate::device::Fleet::default());
        Self {
            started: Instant::now(),
            live_jobs: Arc::new(crate::live_jobs::LiveJobCoordinator::new(fleet.clone())),
            fleet,
            #[cfg(feature = "ble")]
            central: Mutex::new(None),
            #[cfg(feature = "ble")]
            scanning: std::sync::atomic::AtomicBool::new(false),
            #[cfg(feature = "ble")]
            connecting: std::sync::atomic::AtomicBool::new(false),
            #[cfg(feature = "ble")]
            last_scan: Mutex::new(None),
            encoder: OnceLock::new(),
            tx,
            self_weak: OnceLock::new(),
            // R67/C6: wired to the event bus, so every phase change is
            // BROADCAST as well as stored. A store-only cell is what left the
            // hot-channel button stuck on "Preparing...".
            hot_progress: Arc::new(crate::art::HotProgress::with_events(tx_for_hot)),
            wall: Mutex::new(None),
            wall_slots: Mutex::new(serde_json::Map::new()),
            shutdown: Arc::new(tokio::sync::Notify::new()),
        }
    }

    /// The transport a mac-less request means (the single linked panel), if
    /// any. Test-facing convenience over `fleet.resolve_target(None)`.
    pub async fn current_transport(&self) -> Option<Arc<DeviceTransport>> {
        match self.fleet.resolve_target(None).await {
            Ok(d) => d.transport().await,
            Err(_) => None,
        }
    }

    /// Get (or lazy-init) the cached `NativeEncoder`. Returns None if the dylib is absent.
    #[must_use]
    pub fn encoder(&self) -> Option<&NativeEncoder> {
        self.encoder
            .get_or_init(|| {
                crate::native_encode::find_encoder_lib().and_then(|p| NativeEncoder::load(p).ok())
            })
            .as_ref()
    }

    pub fn initialize_self_weak(&self, weak: Weak<Self>) {
        let _ = self.self_weak.set(weak);
    }

    pub(crate) async fn dispatch(&self, req: Request) -> Value {
        dispatch::dispatch(self, req).await
    }

    #[cfg(feature = "ble")]
    async fn cmd_scan(&self, req: &Request) -> Value {
        crate::daemon_connect::cmd_scan(self, req).await
    }

    async fn cmd_connect(&self, req: &Request) -> Value {
        crate::daemon_connect::cmd_connect(self, req).await
    }

    /// `device_call` routes a method string to a protocol op. A small set is ported
    /// first to prove op-level parity (the read-back + a write); unported methods
    /// return an honest error. The device mutex serializes device access.
    pub(crate) async fn cmd_device_call(&self, req: &Request) -> Value {
        // The per-op token gates exclusive mode: if another session holds exclusive,
        // device_call is rejected immediately (Python parity: _cmd_queue.run(token)).
        let token = req.args.get("token").and_then(|v| v.as_str());
        let target_mac = req
            .args
            .get("mac")
            .and_then(|v| v.as_str())
            .or_else(|| req.args.get("target_mac").and_then(|v| v.as_str()));

        // Validate the REQUEST before the connection. This used to check the
        // device first, so a device_call with no `method` was reported as
        // "no device connected" — a diagnosis that sends the caller to look at
        // the wrong thing entirely.
        if req.args.get("method").and_then(|v| v.as_str()).is_none() {
            return err_reply("device_call requires a 'method' string");
        }

        // R67: `target` was NEVER READ. The Python client has always sent
        // `target: "wall"` for wall operations (DaemonDeviceProxy(target="wall")),
        // and the daemon ignored it and used the single device — so a configured
        // wall received nothing, and with no single device connected the GUI got
        // "no device connected" instead. Together with the address-casing bug in
        // ble/connect.rs, that is why the virtual wall did not work at all.
        if req.args.get("target").and_then(|v| v.as_str()) == Some("wall") {
            if Self::is_display_disruptive(req) {
                self.live_jobs.stop_all(self).await;
            }
            return self.wall_device_call(req).await;
        }

        // The device's ONE link carries both the queue and the transport, so
        // a mac-less call and a live job on the same panel are serialized
        // together. A mac-less call with several panels linked is refused.
        let device = match self.fleet.resolve_target(target_mac).await {
            Ok(d) => d,
            Err(e) => return err_reply(&e),
        };
        let target_id = device.id.clone();
        let link = match self.resolve_target_link(Some(&target_id)).await {
            Ok(l) => l,
            Err(e) => return e,
        };
        self.preempt_conflicting_live_jobs(req, &target_id).await;

        let _permit = match link.queue.acquire(token.map(str::to_string)).await {
            Ok(p) => p,
            Err(e) => return err_reply(&e.to_string()),
        };
        let dev = link.transport.clone();

        // Honor a caller-requested timeout (clamped so a huge value can't wedge the
        // device lock forever), and ENFORCE it at the top level: if the whole
        // device op overruns, the timed-out future is dropped — which releases this
        // lock — instead of hanging and blocking every other device call.
        //
        // Default is generous (30s, matching connect_timeout) and the cap is high
        // (120s): this is a safety net against a *hung* op, NOT a cliff for
        // slow-but-valid ones (some ops — e.g. hotchannel updates — can run long;
        // verify exact durations on real hardware before tightening).
        let req_timeout = req
            .args
            .get("timeout")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(30.0)
            .clamp(1.0, 120.0);
        let timeout = Duration::from_secs_f64(req_timeout);

        if let Ok(reply) = tokio::time::timeout(
            timeout,
            crate::device_call::handle_device_call(self, &dev, req, timeout),
        )
        .await
        {
            // R59/event-driven link health: a failed mid-session op (or a
            // timeout) means the link is unhealthy → push a `degraded` status
            // so the UI flips the dot amber immediately instead of waiting for
            // a poll. A successful op recovers it to `active`.
            let id = Some(target_id.clone());
            let degraded = reply.get("success").and_then(serde_json::Value::as_bool) != Some(true);
            let st = if degraded { "degraded" } else { "active" };
            let _ = self.tx.send(crate::daemon_connect::status_payload(
                true,
                id.as_deref(),
                Some(st),
            ));
            if !degraded {
                if let Some(target) = id.as_deref() {
                    self.record_successful_call_activity(req, target).await;
                }
            }
            reply
        } else {
            let msg = format!("device op timed out after {req_timeout:.0}s");
            let id = Some(target_id.clone());
            let _ = self.tx.send(crate::daemon_connect::status_payload(
                true,
                id.as_deref(),
                Some("degraded"),
            ));
            err_reply(&msg)
        }
    }

    /// The connection a request addresses: an explicit `mac`, else the
    /// current device. The errors are the two things a caller can act on.
    pub(crate) async fn resolve_target_link(
        &self,
        target_mac: Option<&str>,
    ) -> Result<Arc<crate::device::Link>, Value> {
        let d = self
            .fleet
            .resolve_target(target_mac)
            .await
            .map_err(|e| err_reply(&e))?;
        d.link()
            .await
            .ok_or_else(|| err_reply(&format!("device '{}' not connected", d.id)))
    }

    async fn record_successful_call_activity(&self, req: &Request, target: &str) {
        let method = req
            .args
            .get("method")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let bare = method.split('.').next_back().unwrap_or(method);
        if bare == "switch_channel" {
            let ch = req
                .args
                .get("args")
                .and_then(|a| a.as_array())
                .and_then(|a| a.first())
                .and_then(|v| v.as_str())
                .or_else(|| {
                    req.args
                        .get("kwargs")
                        .and_then(|m| m.get("channel"))
                        .and_then(|v| v.as_str())
                })
                .unwrap_or("clock");
            self.live_jobs
                .set_device_activity(target.to_string(), ch.to_string(), None, None)
                .await;
            let _ = self.tx.send(json!({
                "type": "activity",
                "mac": target,
                "kind": ch,
            }));
        }
    }

    async fn cmd_disconnect(&self) -> Value {
        crate::daemon_connect::cmd_disconnect(self).await
    }

    /// Delegates to `crate::wall::cmd_wall_configure` (kept there for 500-LOC rule).
    async fn cmd_wall_configure(&self, req: &Request) -> Value {
        crate::wall::cmd_wall_configure(self, req).await
    }

    async fn cmd_get_topology(&self, req: &Request) -> Value {
        crate::wall::cmd_get_topology(self, req).await
    }

    async fn cmd_set_topology(&self, req: &Request) -> Value {
        crate::wall::cmd_set_topology(self, req).await
    }

    /// Methods that repaint the panel and therefore retire its live widget.
    fn is_display_disruptive(req: &Request) -> bool {
        let method = req
            .args
            .get("method")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let bare_method = method.split('.').next_back().unwrap_or(method);
        matches!(
            bare_method,
            "show_image"
                | "display_image"
                | "show_clock"
                | "set_clock"
                | "set_clock_rich"
                | "show_light"
                | "set_light"
                | "switch_channel"
                | "show_text"
                | "set_design"
                | "show_design"
                | "send_image"
                | "push_animation"
                | "stream_animation_8b"
                | "show_effects"
                | "show_visualization"
                | "show_scoreboard"
                | "show_hot_channel"
        )
    }

    async fn preempt_conflicting_live_jobs(&self, req: &Request, target_id: &str) {
        let method = req
            .args
            .get("method")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let bare_method = method.split('.').next_back().unwrap_or(method);
        let is_display_disruptive = Self::is_display_disruptive(req);
        let is_screen_off = match bare_method {
            "set_screen_on" | "on_off_screen" => {
                let on = req
                    .args
                    .get("args")
                    .and_then(|v| v.as_array())
                    .and_then(|a| a.first())
                    .and_then(|v| v.as_bool().or_else(|| v.as_i64().map(|n| n != 0)))
                    .or_else(|| {
                        req.args
                            .get("kwargs")
                            .and_then(|m| {
                                m.get("on")
                                    .or_else(|| m.get("OnOff"))
                                    .or_else(|| m.get("screen_on"))
                            })
                            .and_then(|v| v.as_bool().or_else(|| v.as_i64().map(|n| n != 0)))
                    })
                    .unwrap_or(true);
                !on
            }
            "set_brightness" => {
                let val = req
                    .args
                    .get("args")
                    .and_then(|v| v.as_array())
                    .and_then(|a| a.first())
                    .and_then(serde_json::Value::as_i64)
                    .or_else(|| {
                        req.args
                            .get("kwargs")
                            .and_then(|m| m.get("brightness").or_else(|| m.get("Brightness")))
                            .and_then(serde_json::Value::as_i64)
                    });
                val == Some(0)
            }
            _ => false,
        };
        if is_display_disruptive || is_screen_off {
            self.live_jobs.stop_all_for_device(self, target_id).await;
        }
    }
}

impl Handler for Daemon {
    fn handle<'a>(&'a self, req: Request) -> Pin<Box<dyn Future<Output = Value> + Send + 'a>> {
        Box::pin(async move { self.dispatch(req).await })
    }
    fn subscribe(&self) -> Option<tokio::sync::broadcast::Receiver<Value>> {
        Some(self.tx.subscribe())
    }
    fn initial_status(&self) -> Value {
        // Synchronous by trait contract; the fleet is read with try_lock, so
        // a contended lock reads as "not connected" for this one snapshot
        // (the subscribe stream corrects it on the next status event). The
        // id is the single linked panel's, or absent with several.
        let (connected, id) = self.fleet.status_now();
        let mut ev = json!({
            "type": "status",
            "state": if connected { "active" } else { "idle" },
            "connected": connected,
            "counters": {}
        });
        if let Some(id) = id {
            if let Some(ip) = id.strip_prefix("LAN:") {
                ev["lan_ip"] = json!(ip);
            } else {
                ev["mac"] = json!(id);
            }
        }
        ev
    }
}
