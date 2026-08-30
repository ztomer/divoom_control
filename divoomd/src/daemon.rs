//! The daemon's request Handler — dispatches NDJSON commands to replies. Owns the
//! [`CommandQueue`] (exclusive mode / steal-reject) and, when built with the `ble`
//! feature, the connected device. Replies match the Python daemon's shapes so the
//! existing Python clients (and the conformance suite) drive this unchanged.
//!
//! Device commands are honest: when `ble` is built they hit the real transport;
//! otherwise (and for not-yet-ported commands) they return a clear error rather
//! than a fake success.

use std::future::Future;
use std::pin::Pin;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use std::sync::{Arc, OnceLock, Weak};

use crate::command_queue::CommandQueue;

use crate::native_encode::NativeEncoder;
use crate::protocol::{err_reply, Request};
use crate::socket_server::Handler;

#[cfg(feature = "ble")]
use crate::central::BleCentral;
use tokio::sync::Mutex;

mod dispatch;

const EXCLUSIVE_TIMEOUT: Duration = Duration::from_secs(30);
const ITEM_TIMEOUT: Duration = Duration::from_secs(60);

pub use crate::transport::DeviceTransport;

pub struct Daemon {
    pub(crate) queue: CommandQueue,
    started: Instant,
    pub(crate) device: Mutex<Option<Arc<DeviceTransport>>>,
    pub(crate) device_id: Mutex<Option<String>>,
    // the CoreBluetooth central, created once and kept alive for the daemon's
    // lifetime (dropping it stops notification delivery).
    #[cfg(feature = "ble")]
    pub(crate) central: Mutex<Option<BleCentral>>,
    /// True while a scan is running. A scan drives the one shared adapter's
    /// start/stop; two overlapping scans would clobber each other (one's
    /// stop_scan ends the other early → truncated results), so cmd_scan rejects
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
    /// back-to-back scans trip CoreBluetooth's scan-frequency throttle (which
    /// silently returns 0 devices until it resets).
    #[cfg(feature = "ble")]
    pub(crate) last_scan: Mutex<Option<(Instant, Vec<Value>)>>,
    // C image encoder (libdivoom_compact FFI); loaded once, cached for lifetime.
    encoder: OnceLock<Option<NativeEncoder>>,
    pub(crate) tx: tokio::sync::broadcast::Sender<Value>,
    pub live_jobs: Arc<crate::live_jobs::LiveJobCoordinator>,
    pub(crate) self_weak: OnceLock<Weak<Daemon>>,
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
    pub fn new() -> Self {
        Self::new_with_mac(None)
    }

    pub fn new_with_mac(default_mac: Option<String>) -> Self {
        let (tx, _) = tokio::sync::broadcast::channel(32);
        let tx_for_hot = tx.clone();
        Daemon {
            queue: CommandQueue::new(Some(EXCLUSIVE_TIMEOUT), Some(ITEM_TIMEOUT)),
            started: Instant::now(),
            device: Mutex::new(None),
            device_id: Mutex::new(default_mac),
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
            live_jobs: Arc::new(crate::live_jobs::LiveJobCoordinator::new()),
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

    /// Get (or lazy-init) the cached NativeEncoder. Returns None if the dylib is absent.
    pub(crate) fn encoder(&self) -> Option<&NativeEncoder> {
        self.encoder
            .get_or_init(|| {
                crate::native_encode::find_encoder_lib().and_then(|p| NativeEncoder::load(p).ok())
            })
            .as_ref()
    }

    pub fn initialize_self_weak(&self, weak: Weak<Daemon>) {
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

    /// device_call routes a method string to a protocol op. A small set is ported
    /// first to prove op-level parity (the read-back + a write); unported methods
    /// return an honest error. The device mutex serializes device access.
    pub(crate) async fn cmd_device_call(&self, req: &Request) -> Value {
        // The per-op token gates exclusive mode: if another session holds exclusive,
        // device_call is rejected immediately (Python parity: _cmd_queue.run(token)).
        let token = req.args.get("token").and_then(|v| v.as_str());
        if let Err(e) = self.queue.check_allowed(token) {
            return err_reply(&e.to_string());
        }

        // R67: `target` was NEVER READ. The Python client has always sent
        // `target: "wall"` for wall operations (DaemonDeviceProxy(target="wall")),
        // and the daemon ignored it and used the single device — so a configured
        // wall received nothing, and with no single device connected the GUI got
        // "no device connected" instead. Together with the address-casing bug in
        // ble/connect.rs, that is why the virtual wall did not work at all.
        if req.args.get("target").and_then(|v| v.as_str()) == Some("wall") {
            return self.wall_device_call(req).await;
        }

        let guard = self.device.lock().await;
        let dev = match guard.as_ref() {
            Some(d) => d,
            None => return err_reply("no device connected"),
        };

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
            .and_then(|v| v.as_f64())
            .unwrap_or(30.0)
            .clamp(1.0, 120.0);
        let timeout = Duration::from_secs_f64(req_timeout);

        match tokio::time::timeout(
            timeout,
            crate::device_call::handle_device_call(self, dev, req, timeout),
        )
        .await
        {
            Ok(reply) => {
                // R59/event-driven link health: a failed mid-session op (or a
                // timeout) means the link is unhealthy → push a `degraded` status
                // so the UI flips the dot amber immediately instead of waiting for
                // a poll. A successful op recovers it to `active`. The device is
                // still owned (`guard` holds the lock), so connected stays true.
                if guard.is_some() {
                    let id = self.device_id.lock().await.clone();
                    let degraded = reply.get("success").and_then(|v| v.as_bool()) != Some(true);
                    let st = if degraded { "degraded" } else { "active" };
                    let _ = self.tx.send(crate::daemon_connect::status_payload(
                        true,
                        id.as_deref(),
                        Some(st),
                    ));
                }
                reply
            }
            Err(_) => {
                let msg = format!("device op timed out after {req_timeout:.0}s");
                if guard.is_some() {
                    let id = self.device_id.lock().await.clone();
                    let _ = self.tx.send(crate::daemon_connect::status_payload(
                        true,
                        id.as_deref(),
                        Some("degraded"),
                    ));
                }
                err_reply(&msg)
            }
        }
    }

    async fn cmd_disconnect(&self) -> Value {
        crate::daemon_connect::cmd_disconnect(self).await
    }

    /// Delegates to `crate::wall::cmd_wall_configure` (kept there for 500-LOC rule).
    async fn cmd_wall_configure(&self, req: &Request) -> Value {
        crate::wall::cmd_wall_configure(self, req).await
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
        #[cfg(feature = "ble")]
        let (connected, id) = {
            let dev = self.device.try_lock().map(|g| g.is_some()).unwrap_or(false);
            let id = self.device_id.try_lock().ok().and_then(|g| g.clone());
            (dev, id)
        };
        #[cfg(not(feature = "ble"))]
        let (connected, id): (bool, Option<String>) = (false, None);
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
