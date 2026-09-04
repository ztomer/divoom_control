//! Connect / disconnect / scan command handlers for the native daemon.
//! Split from daemon.rs to keep that file under the 500-LOC ground rule.

use serde_json::{json, Value};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Minimum gap between BLE scans; a scan arriving sooner reuses the last result
/// instead of hitting the radio, so nothing (a retry, a script, a test) can
/// hammer the adapter into CoreBluetooth's scan-frequency throttle.
#[cfg(feature = "ble")]
const MIN_RESCAN_INTERVAL: Duration = Duration::from_secs(3);

#[cfg(feature = "ble")]
use crate::ble::{self, BleTransport, Discovered};
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::{err_reply, Request};

/// Build a full status event so subscribers (the GUI/web UI) can update
/// connection state directly from the push — `connected`, `mac`/`lan_ip`, and the
/// device id. Earlier the connect/disconnect events carried only `state`/`counters`,
/// which forced the UI to poll `device_status()` to learn *which* device (if any)
/// was connected; that poll lag is the "UI doesn't get the update" reliability gap.
/// `state` overrides the derived active/idle (used to push "degraded" on a failed
/// mid-session op — R59/event-driven link health).
pub(crate) fn status_payload(
    connected: bool,
    device_id: Option<&str>,
    state: Option<&str>,
) -> Value {
    let state = state
        .map(|s| s.to_string())
        .unwrap_or_else(|| if connected { "active" } else { "idle" }.to_string());
    let mut m = serde_json::Map::new();
    m.insert("type".into(), json!("status"));
    m.insert("state".into(), json!(state));
    m.insert("connected".into(), json!(connected));
    if let Some(id) = device_id {
        if let Some(ip) = id.strip_prefix("LAN:") {
            m.insert("lan_ip".into(), json!(ip));
        } else {
            m.insert("mac".into(), json!(id));
        }
    }
    m.insert("counters".into(), json!({}));
    Value::Object(m)
}

/// Owned-device list event (R59/event-driven). The daemon is the source of
/// truth for which devices it owns (connected, often non-advertising), so it
/// pushes the set on connect/disconnect instead of the UI polling
/// `get_device_activity` every 4s. `devices` mirrors `get_device_activity`'s
/// per-mac shape (`address`/`name`/`kind`/`state`) so the UI can reuse its merge.
pub(crate) fn owned_devices_payload(device_id: Option<&str>) -> Value {
    let devices = match device_id {
        Some(id) => vec![json!({
            "address": id,
            "name": "",
            "kind": "idle",
            "state": "active",
        })],
        None => vec![],
    };
    json!({ "type": "owned_devices", "devices": devices })
}

/// btleplug surfaces a dead CoreBluetooth central (its session ended after a
/// device disconnect or a Bluetooth toggle) as "Channel closed". The cached
/// Adapter can't recover, so we drop it and retry once with a fresh one.
#[cfg(feature = "ble")]
pub(crate) fn is_dead_central(err: &str) -> bool {
    // A dead CoreBluetooth session surfaces as "Channel closed", but can also
    // hang `start_scan`/`peripherals` until our timeout guard turns it into a
    // "...timed out: central may be stale..." error. Match both so the daemon
    // rebuilds the central and retries either way.
    err.contains("Channel closed")
        || err.contains("timed out")
        || err.contains("stale")
        || err.contains("central")
}

/// Get the (cached) central and run one scan; error as a String for retry logic.
#[cfg(feature = "ble")]
async fn run_scan(daemon: &Daemon, dur: Duration) -> Result<Vec<Discovered>, String> {
    let central = daemon.central().await?;
    ble::scan(&central, dur).await.map_err(|e| e.to_string())
}

/// Get the (cached) central and run one connect; error as a String for retry.
#[cfg(feature = "ble")]
async fn run_connect(daemon: &Daemon, id: &str) -> Result<BleTransport, String> {
    let central = daemon.central().await?;
    BleTransport::connect(&central, id)
        .await
        .map_err(|e| e.to_string())
}

/// Handle `probe_lan` — check whether the connected device is reachable over its
/// LAN HTTP API (Python-daemon parity). BLE/SPP devices report "no LAN configured".
pub(crate) async fn probe_lan(daemon: &Daemon) -> Value {
    let dev = {
        let guard = daemon.device.lock().await;
        match &*guard {
            Some(d) => d.clone(),
            None => {
                return json!({"success": true, "reachable": false, "detail": "no device connected"})
            }
        }
    };
    match dev.lan() {
        Some(lan) => {
            let reachable = lan.probe().await;
            json!({"success": true, "reachable": reachable, "device_ip": lan.device_ip})
        }
        None => json!({"success": true, "reachable": false, "detail": "no LAN configured"}),
    }
}

/// Resets the daemon's `scanning` flag on drop, so a scan that returns via ANY
/// path (incl. an early error) can't wedge the guard.
#[cfg(feature = "ble")]
struct ScanGuard<'a>(&'a std::sync::atomic::AtomicBool);
#[cfg(feature = "ble")]
impl Drop for ScanGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, std::sync::atomic::Ordering::SeqCst);
    }
}

/// Resets the daemon's `connecting` flag on drop, so a connect that returns via
/// ANY path (incl. an early error or a timeout) can't wedge the guard.
#[cfg(feature = "ble")]
struct ConnectGuard<'a>(&'a std::sync::atomic::AtomicBool);

#[cfg(feature = "ble")]
impl Drop for ConnectGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, std::sync::atomic::Ordering::SeqCst);
    }
}

/// Handle `scan` command (BLE only).
#[cfg(feature = "ble")]
pub(crate) async fn cmd_scan(daemon: &Daemon, req: &Request) -> Value {
    use std::sync::atomic::Ordering;
    // Reject a concurrent scan: two scans share the one adapter and would corrupt
    // each other (one's stop_scan cuts the other short → a truncated device list,
    // which is exactly how an overlapping probe made the GUI miss a device).
    if daemon
        .scanning
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return err_reply("scan already in progress");
    }
    let _guard = ScanGuard(&daemon.scanning);

    // Rapid re-scan short-circuit: a scan within MIN_RESCAN_INTERVAL of the last
    // returns the cached result instead of hitting the radio. Back-to-back scans
    // trip CoreBluetooth's scan-frequency throttle (which then returns 0 devices
    // until Bluetooth is toggled) — the failure mode that dogged this feature.
    {
        let last = daemon.last_scan.lock().await;
        if let Some((at, devices)) = last.as_ref() {
            if at.elapsed() < MIN_RESCAN_INTERVAL {
                return json!({"success": true, "devices": devices.clone(), "cached": true});
            }
        }
    }

    let timeout = req
        .args
        .get("timeout")
        .and_then(|v| v.as_f64())
        .unwrap_or(8.0);
    // `limit` is accepted but intentionally NOT used to truncate results: capping
    // could hide a real device (the "found 2 of 3" class of bug). ble::scan caps
    // an over-long timeout internally so a stray large value can't wedge things.
    let dur = Duration::from_secs_f64(timeout);
    let mut result = run_scan(daemon, dur).await;
    if matches!(&result, Err(e) if is_dead_central(e)) {
        daemon.reset_central().await; // stale CoreBluetooth session — rebuild + retry
        result = run_scan(daemon, dur).await;
    }
    match result {
        Ok(devs) => {
            let devices: Vec<Value> = devs
                .iter()
                .map(|d| json!({"name": d.name, "address": d.id}))
                .collect();
            *daemon.last_scan.lock().await = Some((Instant::now(), devices.clone()));
            json!({"success": true, "devices": devices})
        }
        Err(e) => err_reply(&format!("scan failed: {e}")),
    }
}

/// Handle `connect_device` command (BLE or LAN).
pub(crate) async fn cmd_connect(daemon: &Daemon, req: &Request) -> Value {
    // Reject a concurrent connect: two would clobber the one shared central and
    // overwrite the owned device. Held for the whole command via Drop-on-return.
    #[cfg(feature = "ble")]
    {
        if daemon
            .connecting
            .compare_exchange(
                false,
                true,
                std::sync::atomic::Ordering::SeqCst,
                std::sync::atomic::Ordering::SeqCst,
            )
            .is_err()
        {
            return err_reply("connect already in progress");
        }
    }
    #[cfg(feature = "ble")]
    let _guard = ConnectGuard(&daemon.connecting);
    let mock = req
        .args
        .get("mock")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    if mock {
        let mock_transport = crate::mock_transport::MockTransport::new();
        *daemon.device.lock().await = Some(Arc::new(DeviceTransport::Mock(mock_transport)));
        *daemon.device_id.lock().await = Some("MOCK_MAC".to_string());
        let _ = daemon.tx.send(status_payload(true, Some("MOCK_MAC"), None));
        let _ = daemon.tx.send(owned_devices_payload(Some("MOCK_MAC")));
        return json!({"success":true,"connected":true,"connection_state":"connected","mac":"MOCK_MAC"});
    }

    let lan_ip = req.args.get("lan_ip").and_then(|v| v.as_str());
    if let Some(ip) = lan_ip {
        let token = req
            .args
            .get("lan_token")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let lan = crate::lan::LanTransport::new(ip, token);
        if !lan.probe().await {
            return err_reply(&format!("LAN device at {ip} unreachable"));
        }
        *daemon.device.lock().await = Some(Arc::new(DeviceTransport::Lan(lan)));
        *daemon.device_id.lock().await = Some(format!("LAN:{ip}"));
        let _ = daemon
            .tx
            .send(status_payload(true, Some(&format!("LAN:{ip}")), None));
        let _ = daemon
            .tx
            .send(owned_devices_payload(Some(&format!("LAN:{ip}"))));
        return json!({"success":true,"connected":true,"connection_state":"connected","lan_ip":ip});
    }
    #[cfg(feature = "ble")]
    {
        let id = req
            .args
            .get("mac")
            .or_else(|| req.args.get("id"))
            .and_then(|v| v.as_str());
        let id = match id {
            Some(i) => i.to_string(),
            None => return err_reply("connect_device requires 'mac' or 'lan_ip'"),
        };
        let use_ios_le = req
            .args
            .get("use_ios_le_protocol")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);
        if !use_ios_le {
            match crate::spp::SppTransport::connect(&id, None, None).await {
                Ok(t) => {
                    *daemon.device.lock().await = Some(Arc::new(DeviceTransport::Spp(t)));
                    *daemon.device_id.lock().await = Some(id.clone());
                    let _ = daemon.tx.send(status_payload(true, Some(&id), None));
                    let _ = daemon.tx.send(owned_devices_payload(Some(&id)));
                    return json!({"success":true,"connected":true,"connection_state":"connected","mac":id});
                }
                Err(e) => return err_reply(&format!("connect SPP failed: {e}")),
            }
        }

        let mut result = run_connect(daemon, &id).await;
        if matches!(&result, Err(e) if is_dead_central(e)) {
            daemon.reset_central().await; // stale CoreBluetooth session — rebuild + retry
            result = run_connect(daemon, &id).await;
        }
        match result {
            Ok(t) => {
                *daemon.device.lock().await = Some(Arc::new(DeviceTransport::Ble(t)));
                *daemon.device_id.lock().await = Some(id.clone());
                let _ = daemon.tx.send(status_payload(true, Some(&id), None));
                let _ = daemon.tx.send(owned_devices_payload(Some(&id)));
                json!({"success":true,"connected":true,"connection_state":"connected","mac":id})
            }
            Err(e) => err_reply(&format!("connect failed: {e}")),
        }
    }
    #[cfg(not(feature = "ble"))]
    err_reply("BLE support is disabled, requires 'lan_ip'")
}

/// Handle `disconnect` command.
pub(crate) async fn cmd_disconnect(daemon: &Daemon) -> Value {
    if let Some(t) = daemon.device.lock().await.take() {
        match &*t {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => {
                let _ = b.disconnect().await;
            }
            DeviceTransport::Spp(s) => {
                let _ = s.disconnect().await;
            }
            DeviceTransport::Lan(_) => {}
            DeviceTransport::Mock(_) => {}
        }
    }
    *daemon.device_id.lock().await = None;
    let _ = daemon.tx.send(status_payload(false, None, None));
    let _ = daemon.tx.send(owned_devices_payload(None));
    json!({"success": true})
}

#[cfg(all(test, feature = "ble"))]
mod scan_guard_tests;
