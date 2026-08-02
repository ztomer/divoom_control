//! `wall_configure` socket-command handler. Split out of wall.rs (which had
//! split it from daemon.rs) to keep every file under the 500-LOC ground rule.

use super::{DivoomWall, WallConfig};
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::Request;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;

/// Handle `wall_configure` socket command.
/// Ports `owner_wall.py:wall_configure` including G7 delta reconfiguration:
/// when the new layout overlaps the current wall, reuse the shared panels.
pub(crate) async fn cmd_wall_configure(daemon: &Daemon, req: &Request) -> Value {
    let raw_slots = match req.args.get("slots").and_then(|v| v.as_object()) {
        Some(m) => m.clone(),
        None => {
            let mut wall_guard = daemon.wall.lock().await;
            if let Some(old_wall) = wall_guard.take() {
                old_wall.disconnect().await;
            }
            *daemon.wall_slots.lock().await = serde_json::Map::new();
            return json!({"success": true, "wall": false});
        }
    };
    let mut slots: serde_json::Map<String, Value> = serde_json::Map::new();
    for (k, v) in &raw_slots {
        slots.insert(k.to_uppercase(), v.clone());
    }
    if slots.is_empty() {
        let mut wall_guard = daemon.wall.lock().await;
        if let Some(old_wall) = wall_guard.take() {
            old_wall.disconnect().await;
        }
        *daemon.wall_slots.lock().await = serde_json::Map::new();
        return json!({"success": true, "wall": false});
    }
    let cell_size = req
        .args
        .get("cell_size")
        .and_then(|v| v.as_i64())
        .unwrap_or(16) as i32;
    let configs: Vec<WallConfig> = slots
        .iter()
        .map(|(mac, s)| WallConfig {
            mac: mac.clone(),
            x: s.get("x").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
            y: s.get("y").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
            size: s
                .get("size")
                .and_then(|v| v.as_i64())
                .unwrap_or(cell_size as i64) as i32,
            width: s.get("width").and_then(|v| v.as_i64()).map(|v| v as i32),
            height: s.get("height").and_then(|v| v.as_i64()).map(|v| v as i32),
        })
        .collect();
    // G7: delta reconfiguration.
    let old_wall_guard = daemon.wall.lock().await;
    let existing_by_mac: HashMap<String, Arc<DeviceTransport>> = {
        if let Some(ref old_wall) = *old_wall_guard {
            let old_slots_guard = daemon.wall_slots.lock().await;
            let old_macs: std::collections::HashSet<_> = old_slots_guard.keys().cloned().collect();
            let new_macs: std::collections::HashSet<_> = slots.keys().cloned().collect();
            if !old_macs.is_disjoint(&new_macs) {
                old_wall
                    .devices
                    .iter()
                    .filter_map(|s| s.device.as_ref().map(|d| (s.mac.clone(), d.clone())))
                    .collect()
            } else {
                HashMap::new()
            }
        } else {
            HashMap::new()
        }
    };
    if let Some(old_wall) = old_wall_guard.as_ref() {
        for slot in &old_wall.devices {
            if !existing_by_mac.contains_key(&slot.mac) {
                if let Some(ref d) = slot.device {
                    #[cfg(feature = "ble")]
                    if let DeviceTransport::Ble(ref b) = **d {
                        let _ = b.disconnect().await;
                    }
                }
            }
        }
    }
    drop(old_wall_guard);
    match DivoomWall::connect(daemon, &configs, &existing_by_mac).await {
        Ok(new_wall) => {
            let degraded = new_wall.degraded_slots();
            *daemon.wall.lock().await = Some(new_wall);
            *daemon.wall_slots.lock().await = slots;
            if degraded.is_empty() {
                json!({"success": true, "wall": true})
            } else {
                json!({"success": true, "wall": true, "degraded": degraded})
            }
        }
        Err(e) => {
            *daemon.wall.lock().await = None;
            json!({"success": false, "error": e, "wall": false})
        }
    }
}
