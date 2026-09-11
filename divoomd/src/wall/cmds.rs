//! `wall_configure` socket-command handler. Split out of wall.rs (which had
//! split it from daemon.rs) to keep every file under the 500-LOC ground rule.

use super::{DivoomWall, WallConfig};
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::{err_reply, Request};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

fn topology_path() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("DIVOOM_TOPOLOGY_PATH") {
        return Some(PathBuf::from(p));
    }
    let mut dir = crate::cloud::config_dir()?;
    dir.push("topology.json");
    Some(dir)
}

pub fn load_topology() -> Value {
    if let Some(path) = topology_path() {
        if let Ok(s) = std::fs::read_to_string(&path) {
            if let Ok(val) = serde_json::from_str::<Value>(&s) {
                return val;
            }
        }
    }
    json!({
        "devices": {},
        "wall_linked": true,
        "rooms": ["Desk"]
    })
}

pub fn save_topology(val: &Value) -> Result<(), String> {
    let path = topology_path().ok_or_else(|| "cannot find config directory".to_string())?;
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let s = serde_json::to_string_pretty(val).map_err(|e| e.to_string())?;
    std::fs::write(&path, s).map_err(|e| e.to_string())
}

pub async fn cmd_get_topology(daemon: &Daemon, _req: &Request) -> Value {
    let wall_guard = daemon.wall.lock().await;
    let wall_active = wall_guard.is_some();
    drop(wall_guard);
    let slots = daemon.wall_slots.lock().await.clone();
    let top = load_topology();
    let cur_dev = daemon.device_id.try_lock().ok().and_then(|g| g.clone());
    json!({
        "success": true,
        "wall_active": wall_active,
        "slots": slots,
        "current_device": cur_dev,
        "topology": top
    })
}

pub async fn cmd_set_topology(_daemon: &Daemon, req: &Request) -> Value {
    let top = req
        .args
        .get("topology")
        .cloned()
        .unwrap_or_else(|| req.args.clone());
    let mut current = load_topology();
    if let (Some(cur_obj), Some(new_obj)) = (current.as_object_mut(), top.as_object()) {
        for (k, v) in new_obj {
            if k == "devices" {
                if let (Some(cur_devs), Some(new_devs)) = (
                    cur_obj.get_mut("devices").and_then(Value::as_object_mut),
                    v.as_object(),
                ) {
                    for (dev_k, dev_v) in new_devs {
                        cur_devs.insert(dev_k.clone(), dev_v.clone());
                    }
                    continue;
                }
            }
            cur_obj.insert(k.clone(), v.clone());
        }
        match save_topology(&current) {
            Ok(()) => json!({"success": true}),
            Err(e) => err_reply(&format!("failed to save topology: {e}")),
        }
    } else {
        match save_topology(&top) {
            Ok(()) => json!({"success": true}),
            Err(e) => err_reply(&format!("failed to save topology: {e}")),
        }
    }
}

/// Handle `wall_configure` socket command.
/// Ports `owner_wall.py:wall_configure` including G7 delta reconfiguration:
/// when the new layout overlaps the current wall, reuse the shared panels.
#[expect(
    clippy::significant_drop_tightening,
    reason = "the guarded value is read by everything after this line; the explicit drops that could be added were placed where they helped and the borrow checker refused the rest"
)]
#[expect(
    clippy::cast_possible_truncation,
    reason = "wall dimensions from a caller's JSON, bounded by the number of panels a wall can hold"
)]
pub async fn cmd_wall_configure(daemon: &Daemon, req: &Request) -> Value {
    let raw_slots = if let Some(m) = req.args.get("slots").and_then(|v| v.as_object()) {
        m.clone()
    } else {
        let mut wall_guard = daemon.wall.lock().await;
        if let Some(old_wall) = wall_guard.take() {
            old_wall.disconnect().await;
        }
        *daemon.wall_slots.lock().await = serde_json::Map::new();
        return json!({"success": true, "wall": false});
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
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(16) as i32;
    let configs: Vec<WallConfig> = slots
        .iter()
        .map(|(mac, s)| WallConfig {
            mac: mac.clone(),
            x: s.get("x").and_then(serde_json::Value::as_i64).unwrap_or(0) as i32,
            y: s.get("y").and_then(serde_json::Value::as_i64).unwrap_or(0) as i32,
            size: s
                .get("size")
                .and_then(serde_json::Value::as_i64)
                .unwrap_or_else(|| i64::from(cell_size)) as i32,
            width: s
                .get("width")
                .and_then(serde_json::Value::as_i64)
                .map(|v| v as i32),
            height: s
                .get("height")
                .and_then(serde_json::Value::as_i64)
                .map(|v| v as i32),
        })
        .collect();
    // G7: delta reconfiguration.
    let old_wall_guard = daemon.wall.lock().await;
    let existing_by_mac: HashMap<String, Arc<DeviceTransport>> = {
        if let Some(ref old_wall) = *old_wall_guard {
            let old_slots_guard = daemon.wall_slots.lock().await;
            let old_macs: std::collections::HashSet<_> = old_slots_guard.keys().cloned().collect();
            drop(old_slots_guard);
            let new_macs: std::collections::HashSet<_> = slots.keys().cloned().collect();
            if old_macs.is_disjoint(&new_macs) {
                HashMap::new()
            } else {
                old_wall
                    .devices
                    .iter()
                    .filter_map(|s| s.device.as_ref().map(|d| (s.mac.clone(), d.clone())))
                    .collect()
            }
        } else {
            HashMap::new()
        }
    };
    if let Some(old_wall) = old_wall_guard.as_ref() {
        for slot in &old_wall.devices {
            if !existing_by_mac.contains_key(&slot.mac) {
                #[cfg(feature = "ble")]
                if let Some(ref d) = slot.device {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_topology_save_and_load() {
        let temp_dir = std::env::temp_dir().join("divoom_test_topology");
        let _ = std::fs::create_dir_all(&temp_dir);
        let file_path = temp_dir.join("test_topology.json");
        std::env::set_var("DIVOOM_TOPOLOGY_PATH", &file_path);

        let data = json!({
            "devices": {
                "11:22:33:44:55:01": {
                    "name": "Ditoo Left",
                    "model": "Ditoo Pro",
                    "x": 30,
                    "y": 40,
                    "brightness": 85
                }
            },
            "wall_linked": true,
            "rooms": ["Desk"]
        });

        assert!(save_topology(&data).is_ok());
        let loaded = load_topology();
        assert_eq!(loaded["wall_linked"], true);
        assert_eq!(loaded["devices"]["11:22:33:44:55:01"]["name"], "Ditoo Left");
        assert_eq!(loaded["devices"]["11:22:33:44:55:01"]["brightness"], 85);

        let _ = std::fs::remove_file(&file_path);
        std::env::remove_var("DIVOOM_TOPOLOGY_PATH");
    }
}
