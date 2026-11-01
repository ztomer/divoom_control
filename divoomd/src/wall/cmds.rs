//! `wall_configure` socket-command handler. Split out of wall.rs (which had
//! split it from daemon.rs) to keep every file under the 500-LOC ground rule.

use super::{DivoomWall, WallConfig};
use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::{err_code, err_with, ErrorCode, Request};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

/// Where the layout lives, and whether the operator NAMED the file
/// (`DIVOOM_TOPOLOGY_PATH`) rather than it being the owner's default.
fn topology_location() -> Option<(PathBuf, bool)> {
    if let Ok(p) = std::env::var("DIVOOM_TOPOLOGY_PATH") {
        return Some((PathBuf::from(p), true));
    }
    let mut dir = crate::cloud::config_dir()?;
    dir.push("topology.json");
    Some((dir, false))
}

fn topology_path() -> Option<PathBuf> {
    topology_location().map(|(p, _)| p)
}

/// Drop every placement no real device ever reported (D.DV2), in the
/// owner's default layout only: a named layout is a test's, and its doubles
/// belong there. The dropped ids, for the caller to say.
fn drop_unreported(top: &mut Value, named: bool) -> Vec<String> {
    if named {
        return Vec::new();
    }
    retain_reported(top, &crate::reported_panels::Reported::load())
}

/// The layout's placements `reported` admits, the rest dropped and named.
fn retain_reported(top: &mut Value, reported: &crate::reported_panels::Reported) -> Vec<String> {
    top.get_mut("devices")
        .and_then(Value::as_object_mut)
        .map(|devices| reported.retain_admitted(devices))
        .unwrap_or_default()
}

/// The saved layout. In the owner's default location a placement no real
/// device ever reported is dropped on the way in, and the file is rewritten
/// without it -- the migration that took the invented fleet out of the
/// owner's `topology.json` is this read.
pub fn load_topology() -> Value {
    load_topology_at(topology_location())
}

/// `load_topology` from the location given: the seam its tests use, so no
/// test has to set the process-wide `DIVOOM_TOPOLOGY_PATH` another reads.
fn load_topology_at(location: Option<(PathBuf, bool)>) -> Value {
    if let Some((path, named)) = location {
        if let Ok(s) = std::fs::read_to_string(&path) {
            if let Ok(mut val) = serde_json::from_str::<Value>(&s) {
                let dropped = drop_unreported(&mut val, named);
                if !dropped.is_empty() {
                    eprintln!(
                        "divoomd: topology.json placed panels no device ever reported; dropped: {}",
                        dropped.join(", ")
                    );
                    if let Err(e) = save_topology(&val) {
                        eprintln!("divoomd: could not rewrite topology.json: {e}");
                    }
                }
                return val;
            }
        }
    }
    json!({
        "devices": {},
        "wall_linked": true,
        "rooms": ["Desk", "Shelf", "Wall"]
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
    // The single linked panel, or null: there is no "current" any more.
    let cur_dev = daemon
        .fleet
        .resolve_target(None)
        .await
        .ok()
        .map(|d| d.id.clone());
    let screens = screens(daemon, &top).await;
    json!({
        "success": true,
        "wall_active": wall_active,
        "slots": slots,
        "current_device": cur_dev,
        "screens": screens,
        "topology": top
    })
}

/// Every panel the daemon knows or the saved layout places, one entry each
/// (P4.2): the device entry `device_status` uses (link state, model, pixels,
/// features) plus its saved `x`/`y`/`room`. A placed panel the daemon has
/// never linked is listed too, `connected: false` and its size `null` --
/// unknown, not assumed 16.
async fn screens(daemon: &Daemon, top: &Value) -> Vec<Value> {
    let placed = top.get("devices").and_then(Value::as_object);
    let place = |entry: &mut Value, id: &str| {
        let spot = placed.and_then(|m| {
            m.iter()
                .find(|(addr, _)| addr.eq_ignore_ascii_case(id))
                .map(|(_, v)| v)
        });
        if let (Some(obj), Some(spot)) = (entry.as_object_mut(), spot) {
            for k in ["x", "y", "room"] {
                obj.insert(k.into(), spot.get(k).cloned().unwrap_or(Value::Null));
            }
        }
    };
    let mut out = Vec::new();
    for d in daemon.fleet.all().await {
        let mut e = daemon.device_entry(&d).await;
        place(&mut e, &d.id);
        out.push(e);
    }
    for addr in placed.into_iter().flat_map(serde_json::Map::keys) {
        if out.iter().any(|e| {
            e["mac"]
                .as_str()
                .is_some_and(|m| m.eq_ignore_ascii_case(addr))
        }) {
            continue;
        }
        let mut e = json!({"mac": addr, "connected": false, "selected": false});
        crate::daemon_status::merge(&mut e, &crate::panel_model::from_name(None).fields());
        place(&mut e, addr);
        out.push(e);
    }
    out
}

/// The room names in `v`, each once (case-insensitively), in order.
fn room_names(v: Option<&Value>) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for r in v.and_then(Value::as_array).into_iter().flatten() {
        if let Some(r) = r.as_str().map(str::trim).filter(|r| !r.is_empty()) {
            if !out.iter().any(|o| o.eq_ignore_ascii_case(r)) {
                out.push(r.to_string());
            }
        }
    }
    out
}

/// `new` merged over `current`: top-level keys replace, and each device entry
/// in `new` replaces the stored one for that panel WHOLE -- so an entry sent
/// without a `room` is how the GUI takes a panel out of every room (U.4). A
/// panel is one key whatever its letter case (`screens` matches without
/// regard to case): a stored entry spelled differently is replaced, not
/// kept beside the new one, where a lookup could find the stale one first.
///
/// The room list is the exception to "replace": it MERGES (2026-11-01, the
/// owner's "Ethan" erased by a GUI that sent its defaults before it had read
/// this copy). A room leaves the list only when `remove_rooms` names it, which
/// also takes every panel out of it; the operation itself is not stored.
fn merge_topology(mut current: Value, new: &Value) -> Value {
    let (Some(cur_obj), Some(new_obj)) = (current.as_object_mut(), new.as_object()) else {
        return new.clone();
    };
    for (k, v) in new_obj {
        if k == "remove_rooms" {
            continue;
        }
        if k == "rooms" {
            let mut rooms = room_names(cur_obj.get("rooms"));
            for r in room_names(Some(v)) {
                if !rooms.iter().any(|o| o.eq_ignore_ascii_case(&r)) {
                    rooms.push(r);
                }
            }
            cur_obj.insert(k.clone(), json!(rooms));
            continue;
        }
        if k == "devices" {
            if let (Some(cur_devs), Some(new_devs)) = (
                cur_obj.get_mut("devices").and_then(Value::as_object_mut),
                v.as_object(),
            ) {
                for (dev_k, dev_v) in new_devs {
                    cur_devs.retain(|stored, _| !stored.eq_ignore_ascii_case(dev_k));
                    cur_devs.insert(dev_k.clone(), dev_v.clone());
                }
                continue;
            }
        }
        cur_obj.insert(k.clone(), v.clone());
    }
    let removed = room_names(new_obj.get("remove_rooms"));
    if !removed.is_empty() {
        let gone = |r: &str| removed.iter().any(|x| x.eq_ignore_ascii_case(r));
        let kept: Vec<String> = room_names(cur_obj.get("rooms"))
            .into_iter()
            .filter(|r| !gone(r))
            .collect();
        cur_obj.insert("rooms".into(), json!(kept));
        if let Some(devs) = cur_obj.get_mut("devices").and_then(Value::as_object_mut) {
            for entry in devs.values_mut().filter_map(Value::as_object_mut) {
                if entry.get("room").and_then(Value::as_str).is_some_and(gone) {
                    entry.remove("room");
                }
            }
        }
    }
    current
}

pub async fn cmd_set_topology(_daemon: &Daemon, req: &Request) -> Value {
    let top = req
        .args
        .get("topology")
        .cloned()
        .unwrap_or_else(|| req.args.clone());
    let named = topology_location().is_some_and(|(_, named)| named);
    let mut merged = merge_topology(load_topology(), &top);
    // A placement for a panel no real device reported is not stored (D.DV2):
    // the reply names it, so the writer learns it was refused.
    let dropped = drop_unreported(&mut merged, named);
    match save_topology(&merged) {
        Ok(()) if dropped.is_empty() => json!({"success": true}),
        Ok(()) => json!({"success": true, "dropped": dropped}),
        Err(e) => err_code(
            ErrorCode::Internal,
            &format!("failed to save topology: {e}"),
        ),
    }
}

async fn teardown_wall(daemon: &Daemon) -> Value {
    let mut wall_guard = daemon.wall.lock().await;
    if let Some(old_wall) = wall_guard.take() {
        let preserved: Vec<String> = daemon.fleet.ids().await;
        old_wall.disconnect(&preserved).await;
    }
    drop(wall_guard);
    *daemon.wall_slots.lock().await = serde_json::Map::new();
    // The wall is gone: it must not come back on the next start.
    daemon.links.forget_wall().await;
    json!({"success": true, "wall": false})
}

fn parse_wall_configs(slots: &serde_json::Map<String, Value>, cell_size: i32) -> Vec<WallConfig> {
    // Wall geometry arrives as JSON integers and lives in `i32` fields.
    // Saturate on the way in: a caller asking for a trillion-pixel wall gets
    // the largest representable one, not a wrapped reinterpretation of it.
    fn narrow(v: i64) -> i32 {
        i32::try_from(v.clamp(i64::from(i32::MIN), i64::from(i32::MAX)))
            .expect("clamped to i32 range")
    }
    slots
        .iter()
        .map(|(mac, s)| WallConfig {
            mac: mac.clone(),
            x: narrow(s.get("x").and_then(serde_json::Value::as_i64).unwrap_or(0)),
            y: narrow(s.get("y").and_then(serde_json::Value::as_i64).unwrap_or(0)),
            size: narrow(
                s.get("size")
                    .and_then(serde_json::Value::as_i64)
                    .unwrap_or_else(|| i64::from(cell_size)),
            ),
            width: s
                .get("width")
                .and_then(serde_json::Value::as_i64)
                .map(narrow),
            height: s
                .get("height")
                .and_then(serde_json::Value::as_i64)
                .map(narrow),
        })
        .collect()
}

/// Handle `wall_configure` socket command.
/// Ports `owner_wall.py:wall_configure` including G7 delta reconfiguration:
/// when the new layout overlaps the current wall, reuse the shared panels.
pub async fn cmd_wall_configure(daemon: &Daemon, req: &Request) -> Value {
    let Some(raw_slots) = req.args.get("slots").and_then(Value::as_object) else {
        return teardown_wall(daemon).await;
    };
    let mut slots: serde_json::Map<String, Value> = serde_json::Map::new();
    for (k, v) in raw_slots {
        slots.insert(k.to_uppercase(), v.clone());
    }
    if slots.is_empty() {
        return teardown_wall(daemon).await;
    }
    let cell_size = req
        .args
        .get("cell_size")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(16)
        .clamp(i64::from(i32::MIN), i64::from(i32::MAX));
    let cell_size = i32::try_from(cell_size).expect("clamped to i32 range");
    let configs = parse_wall_configs(&slots, cell_size);
    // G7: delta reconfiguration.
    let old_wall_guard = daemon.wall.lock().await;
    let mut existing_by_mac: HashMap<String, Arc<DeviceTransport>> = HashMap::new();
    for d in daemon.fleet.linked().await {
        if let Some(t) = d.transport().await {
            existing_by_mac.insert(d.id.to_uppercase(), t);
        }
    }
    if let Some(ref old_wall) = *old_wall_guard {
        for slot in &old_wall.devices {
            if let Some(ref d) = slot.device {
                existing_by_mac
                    .entry(slot.mac.to_uppercase())
                    .or_insert_with(|| d.clone());
            }
        }
        let fleet_ids: Vec<String> = daemon
            .fleet
            .ids()
            .await
            .into_iter()
            .map(|i| i.to_uppercase())
            .collect();
        for slot in &old_wall.devices {
            let upper = slot.mac.to_uppercase();
            if !slots.contains_key(&upper) && !fleet_ids.contains(&upper) {
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
            let refused: serde_json::Map<String, Value> = new_wall
                .refused
                .iter()
                .map(|mac| (mac.clone(), json!(super::LAN_SLOT_REFUSAL)))
                .collect();
            *daemon.wall.lock().await = Some(new_wall);
            *daemon.wall_slots.lock().await = slots.clone();
            // Remember the slots: a wall is not a link, so nothing else would
            // bring it back after the daemon restarts (P2.7's remainder).
            daemon
                .links
                .remember_wall(slots, i64::from(cell_size))
                .await;
            let mut reply = json!({"success": true, "wall": true});
            if !degraded.is_empty() {
                reply["degraded"] = json!(degraded);
            }
            if !refused.is_empty() {
                reply["refused"] = Value::Object(refused);
            }
            reply
        }
        Err(e) => {
            *daemon.wall.lock().await = None;
            err_with(ErrorCode::DeviceFailed, &e, json!({"wall": false}))
        }
    }
}

#[cfg(test)]
#[path = "cmds_tests.rs"]
mod tests;
